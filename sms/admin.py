import sqlite3
from datetime import date

from flask import Blueprint, abort, flash, redirect, render_template, request, url_for

from .db import get_db
from .security import hash_password, remove_uploads, require_role
from .services import (
    attendance_breakdown, attendance_records, get_student, get_threshold, is_low, list_students,
    list_submissions, marks_for, pending_counts, scalar, set_threshold,
)
from .validators import CODE_RE, PHONE_RE, USERNAME_RE, Form

bp = Blueprint("admin", __name__, url_prefix="/admin")


@bp.before_request
def _guard():
    return require_role("admin")


def _filters():
    q = request.args.get("q", "").strip()[:60]
    course_id = request.args.get("course", type=int)
    low = request.args.get("low") == "1"
    return q, course_id, low


def _unique(db, form, field, label, sql, value, own_id):
    if value and not form.errors.get(field):
        row = db.execute(sql, (value,)).fetchone()
        if row and row["id"] != own_id:
            form.error(field, f"That {label} is already in use.")


# --------------------------------------------------------------------------
# Dashboard
# --------------------------------------------------------------------------
@bp.get("/")
def dashboard():
    db = get_db()
    threshold = get_threshold(db)
    alerts = sorted(
        (s for s in list_students(db) if is_low(s, threshold)), key=lambda s: s["attendance_pct"]
    )
    counts = {
        "students": scalar(db, "SELECT COUNT(*) FROM students"),
        "staff": scalar(db, "SELECT COUNT(*) FROM staff"),
        "courses": scalar(db, "SELECT COUNT(*) FROM courses"),
    }
    return render_template(
        "admin/dashboard.html", counts=counts, alerts=alerts, threshold=threshold, pending=pending_counts(db)
    )


# --------------------------------------------------------------------------
# Students
# --------------------------------------------------------------------------
@bp.get("/students")
def students():
    db = get_db()
    q, course_id, low = _filters()
    threshold = get_threshold(db)
    rows = list_students(db, q=q, course_id=course_id)
    if low:
        rows = [s for s in rows if is_low(s, threshold)]
    return render_template(
        "admin/students.html", students=rows, q=q, course_id=course_id, low=low, threshold=threshold,
        courses=db.execute("SELECT id, code, name FROM courses ORDER BY name").fetchall(),
    )


def _student_choices(db):
    courses = db.execute("SELECT id, code, name FROM courses ORDER BY name").fetchall()
    staff = db.execute(
        "SELECT st.id, u.full_name FROM staff st JOIN users u ON u.id = st.user_id ORDER BY u.full_name"
    ).fetchall()
    return courses, staff


def _validate_student(db, data, courses, staff, existing=None):
    form = Form(data)
    own_user = existing["user_id"] if existing else None
    own_id = existing["id"] if existing else None
    v = {
        "full_name": form.text("full_name", "Full name", min_len=2, max_len=100),
        "username": form.text("username", "Username", regex=USERNAME_RE,
                              message="Username must be 3-30 letters, numbers, dots, dashes or underscores."),
        "email": form.email(),
        "password": form.password(required=existing is None),
        "student_code": form.text("student_code", "Student ID", regex=CODE_RE,
                                  message="Student ID must be 2-20 letters, numbers, dashes or underscores."),
        "phone": form.text("phone", "Phone", required=False, regex=PHONE_RE, message="Enter a valid phone number."),
        "address": form.text("address", "Address", required=False, max_len=300),
        "course_id": form.ref("course_id", "Course", {c["id"] for c in courses}),
        "staff_id": form.ref("staff_id", "Assigned staff", {s["id"] for s in staff}),
        "is_active": form.checkbox("is_active"),
    }
    dob = form.date("date_of_birth", "Date of birth", required=False,
                    min_date=date(1900, 1, 1), max_date=date.today())
    v["date_of_birth"] = dob.isoformat() if dob else None
    _unique(db, form, "username", "username", "SELECT id FROM users WHERE username = ?", v["username"], own_user)
    _unique(db, form, "email", "email", "SELECT id FROM users WHERE email = ?", v["email"], own_user)
    _unique(db, form, "student_code", "student ID", "SELECT id FROM students WHERE student_code = ?",
            v["student_code"], own_id)
    return form, v


@bp.route("/students/new", methods=["GET", "POST"])
def student_new():
    db = get_db()
    courses, staff = _student_choices(db)
    form = Form(prefill={"is_active": 1})
    if request.method == "POST":
        form, v = _validate_student(db, request.form, courses, staff)
        if form.ok:
            try:
                with db:
                    cur = db.execute(
                        "INSERT INTO users (username, email, full_name, password_hash, role, is_active) "
                        "VALUES (?, ?, ?, ?, 'student', ?)",
                        (v["username"], v["email"], v["full_name"], hash_password(v["password"]), v["is_active"]),
                    )
                    db.execute(
                        "INSERT INTO students (user_id, student_code, phone, date_of_birth, address, course_id, staff_id) "
                        "VALUES (?, ?, ?, ?, ?, ?, ?)",
                        (cur.lastrowid, v["student_code"], v["phone"], v["date_of_birth"], v["address"],
                         v["course_id"], v["staff_id"]),
                    )
                flash(f"Student {v['full_name']} added.", "success")
                return redirect(url_for("admin.students"))
            except sqlite3.IntegrityError:
                form.error("username", "Username, email or student ID already exists.")
        return render_template("admin/student_form.html", form=form, courses=courses, staff=staff, student=None), 400
    return render_template("admin/student_form.html", form=form, courses=courses, staff=staff, student=None)


@bp.get("/students/<int:student_id>")
def student_view(student_id):
    db = get_db()
    student = get_student(db, student_id)
    if student is None:
        abort(404)
    counts = {
        kind: scalar(db, f"SELECT COUNT(*) FROM {meta} WHERE student_id = ?", (student_id,))
        for kind, meta in (("certificates", "certificate_submissions"), ("completions", "course_completions"),
                           ("leaves", "leave_requests"))
    }
    return render_template(
        "admin/student_detail.html", student=student, threshold=get_threshold(db), counts=counts,
        breakdown=attendance_breakdown(db, student_id), attendance=attendance_records(db, student_id, limit=60),
        marks=marks_for(db, student_id),
    )


@bp.route("/students/<int:student_id>/edit", methods=["GET", "POST"])
def student_edit(student_id):
    db = get_db()
    student = get_student(db, student_id)
    if student is None:
        abort(404)
    courses, staff = _student_choices(db)
    form = Form(prefill={**student, "date_of_birth": student["date_of_birth"] or ""})
    if request.method == "POST":
        form, v = _validate_student(db, request.form, courses, staff, existing=student)
        if form.ok:
            try:
                with db:
                    db.execute(
                        "UPDATE users SET username = ?, email = ?, full_name = ?, is_active = ?, "
                        "updated_at = datetime('now') WHERE id = ?",
                        (v["username"], v["email"], v["full_name"], v["is_active"], student["user_id"]),
                    )
                    if v["password"]:
                        db.execute("UPDATE users SET password_hash = ? WHERE id = ?",
                                   (hash_password(v["password"]), student["user_id"]))
                    db.execute(
                        "UPDATE students SET student_code = ?, phone = ?, date_of_birth = ?, address = ?, "
                        "course_id = ?, staff_id = ?, updated_at = datetime('now') WHERE id = ?",
                        (v["student_code"], v["phone"], v["date_of_birth"], v["address"], v["course_id"],
                         v["staff_id"], student_id),
                    )
                flash("Student updated.", "success")
                return redirect(url_for("admin.student_view", student_id=student_id))
            except sqlite3.IntegrityError:
                form.error("username", "Username, email or student ID already exists.")
        return render_template("admin/student_form.html", form=form, courses=courses, staff=staff, student=student), 400
    return render_template("admin/student_form.html", form=form, courses=courses, staff=staff, student=student)


@bp.route("/students/<int:student_id>/delete", methods=["GET", "POST"])
def student_delete(student_id):
    db = get_db()
    student = get_student(db, student_id)
    if student is None:
        abort(404)
    if request.method == "POST":
        files = [r[0] for r in db.execute(
            "SELECT stored_filename FROM certificate_submissions WHERE student_id = ? "
            "UNION ALL SELECT stored_filename FROM course_completions WHERE student_id = ?",
            (student_id, student_id))]
        with db:
            db.execute("DELETE FROM users WHERE id = ?", (student["user_id"],))  # cascades to the student row
        remove_uploads(files)
        flash(f"Student {student['full_name']} was deleted.", "success")
        return redirect(url_for("admin.students"))
    return render_template(
        "confirm_delete.html",
        heading="Delete student?",
        subject=f"{student['full_name']} ({student['student_code']})",
        consequences=["Their login account will be removed.",
                      "All attendance, marks, certificates, course completions and leave requests will be deleted.",
                      "Uploaded files will be erased. This cannot be undone."],
        cancel_url=url_for("admin.student_view", student_id=student_id),
    )


# --------------------------------------------------------------------------
# Staff
# --------------------------------------------------------------------------
@bp.get("/staff")
def staff_list():
    db = get_db()
    q = request.args.get("q", "").strip()[:60]
    sql = ("SELECT st.id, st.employee_code, st.department, st.phone, u.full_name, u.email, u.username, u.is_active, "
           "(SELECT COUNT(*) FROM students s WHERE s.staff_id = st.id) AS student_count "
           "FROM staff st JOIN users u ON u.id = st.user_id")
    params = []
    if q:
        like = "%" + q.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"
        sql += " WHERE u.full_name LIKE ? ESCAPE '\\' OR st.employee_code LIKE ? ESCAPE '\\' OR u.email LIKE ? ESCAPE '\\'"
        params = [like] * 3
    rows = db.execute(sql + " ORDER BY u.full_name COLLATE NOCASE", params).fetchall()
    return render_template("admin/staff_list.html", staff=rows, q=q)


def _get_staff(db, staff_id):
    row = db.execute(
        "SELECT st.id, st.user_id, st.employee_code, st.department, st.phone, u.full_name, u.email, u.username, u.is_active "
        "FROM staff st JOIN users u ON u.id = st.user_id WHERE st.id = ?", (staff_id,)).fetchone()
    if row is None:
        abort(404)
    return row


def _validate_staff(db, data, existing=None):
    form = Form(data)
    own_user = existing["user_id"] if existing else None
    own_id = existing["id"] if existing else None
    v = {
        "full_name": form.text("full_name", "Full name", min_len=2, max_len=100),
        "username": form.text("username", "Username", regex=USERNAME_RE,
                              message="Username must be 3-30 letters, numbers, dots, dashes or underscores."),
        "email": form.email(),
        "password": form.password(required=existing is None),
        "employee_code": form.text("employee_code", "Employee ID", regex=CODE_RE,
                                   message="Employee ID must be 2-20 letters, numbers, dashes or underscores."),
        "department": form.text("department", "Department", required=False, max_len=80),
        "phone": form.text("phone", "Phone", required=False, regex=PHONE_RE, message="Enter a valid phone number."),
        "is_active": form.checkbox("is_active"),
    }
    _unique(db, form, "username", "username", "SELECT id FROM users WHERE username = ?", v["username"], own_user)
    _unique(db, form, "email", "email", "SELECT id FROM users WHERE email = ?", v["email"], own_user)
    _unique(db, form, "employee_code", "employee ID", "SELECT id FROM staff WHERE employee_code = ?",
            v["employee_code"], own_id)
    return form, v


@bp.route("/staff/new", methods=["GET", "POST"])
def staff_new():
    db = get_db()
    form = Form(prefill={"is_active": 1})
    if request.method == "POST":
        form, v = _validate_staff(db, request.form)
        if form.ok:
            try:
                with db:
                    cur = db.execute(
                        "INSERT INTO users (username, email, full_name, password_hash, role, is_active) "
                        "VALUES (?, ?, ?, ?, 'staff', ?)",
                        (v["username"], v["email"], v["full_name"], hash_password(v["password"]), v["is_active"]))
                    db.execute("INSERT INTO staff (user_id, employee_code, department, phone) VALUES (?, ?, ?, ?)",
                               (cur.lastrowid, v["employee_code"], v["department"], v["phone"]))
                flash(f"Staff account for {v['full_name']} created.", "success")
                return redirect(url_for("admin.staff_list"))
            except sqlite3.IntegrityError:
                form.error("username", "Username, email or employee ID already exists.")
        return render_template("admin/staff_form.html", form=form, member=None), 400
    return render_template("admin/staff_form.html", form=form, member=None)


@bp.route("/staff/<int:staff_id>/edit", methods=["GET", "POST"])
def staff_edit(staff_id):
    db = get_db()
    member = _get_staff(db, staff_id)
    form = Form(prefill=dict(member))
    if request.method == "POST":
        form, v = _validate_staff(db, request.form, existing=member)
        if form.ok:
            try:
                with db:
                    db.execute("UPDATE users SET username = ?, email = ?, full_name = ?, is_active = ?, "
                               "updated_at = datetime('now') WHERE id = ?",
                               (v["username"], v["email"], v["full_name"], v["is_active"], member["user_id"]))
                    if v["password"]:
                        db.execute("UPDATE users SET password_hash = ? WHERE id = ?",
                                   (hash_password(v["password"]), member["user_id"]))
                    db.execute("UPDATE staff SET employee_code = ?, department = ?, phone = ?, "
                               "updated_at = datetime('now') WHERE id = ?",
                               (v["employee_code"], v["department"], v["phone"], staff_id))
                flash("Staff account updated.", "success")
                return redirect(url_for("admin.staff_list"))
            except sqlite3.IntegrityError:
                form.error("username", "Username, email or employee ID already exists.")
        return render_template("admin/staff_form.html", form=form, member=member), 400
    return render_template("admin/staff_form.html", form=form, member=member)


@bp.route("/staff/<int:staff_id>/delete", methods=["GET", "POST"])
def staff_delete(staff_id):
    db = get_db()
    member = _get_staff(db, staff_id)
    assigned = scalar(db, "SELECT COUNT(*) FROM students WHERE staff_id = ?", (staff_id,))
    if request.method == "POST":
        with db:
            db.execute("DELETE FROM users WHERE id = ?", (member["user_id"],))  # students.staff_id -> NULL
        flash(f"Staff account {member['full_name']} was deleted.", "success")
        return redirect(url_for("admin.staff_list"))
    consequences = ["Their login account will be removed.", "This cannot be undone."]
    if assigned:
        consequences.insert(1, f"{assigned} assigned student(s) will become unassigned.")
    return render_template("confirm_delete.html", heading="Delete staff account?",
                           subject=f"{member['full_name']} ({member['employee_code']})",
                           consequences=consequences, cancel_url=url_for("admin.staff_list"))


# --------------------------------------------------------------------------
# Courses and settings
# --------------------------------------------------------------------------
@bp.get("/courses")
def courses():
    db = get_db()
    rows = db.execute(
        "SELECT c.id, c.code, c.name, c.description, "
        "(SELECT COUNT(*) FROM students s WHERE s.course_id = c.id) AS student_count "
        "FROM courses c ORDER BY c.name COLLATE NOCASE").fetchall()
    return render_template("admin/courses.html", courses=rows, threshold=get_threshold(db),
                           form=Form(prefill={"attendance_threshold": f"{get_threshold(db):g}"}))


@bp.post("/settings/threshold")
def update_threshold():
    db = get_db()
    form = Form(request.form)
    value = form.number("attendance_threshold", "Attendance threshold", minimum=0, maximum=100)
    if not form.ok:
        flash(form.first_error(), "danger")
    else:
        set_threshold(db, value)
        flash(f"Attendance threshold set to {value:g}%.", "success")
    return redirect(url_for("admin.courses"))


def _validate_course(db, data, existing=None):
    form = Form(data)
    v = {
        "code": form.text("code", "Course code", regex=CODE_RE,
                          message="Course code must be 2-20 letters, numbers, dashes or underscores."),
        "name": form.text("name", "Course name", min_len=2, max_len=120),
        "description": form.text("description", "Description", required=False, max_len=500),
    }
    _unique(db, form, "code", "course code", "SELECT id FROM courses WHERE code = ?", v["code"],
            existing["id"] if existing else None)
    return form, v


@bp.route("/courses/new", methods=["GET", "POST"])
def course_new():
    db = get_db()
    form = Form(prefill={})
    if request.method == "POST":
        form, v = _validate_course(db, request.form)
        if form.ok:
            with db:
                db.execute("INSERT INTO courses (code, name, description) VALUES (?, ?, ?)",
                           (v["code"], v["name"], v["description"]))
            flash("Course added.", "success")
            return redirect(url_for("admin.courses"))
        return render_template("admin/course_form.html", form=form, course=None), 400
    return render_template("admin/course_form.html", form=form, course=None)


def _get_course(db, course_id):
    row = db.execute("SELECT * FROM courses WHERE id = ?", (course_id,)).fetchone()
    if row is None:
        abort(404)
    return row


@bp.route("/courses/<int:course_id>/edit", methods=["GET", "POST"])
def course_edit(course_id):
    db = get_db()
    course = _get_course(db, course_id)
    form = Form(prefill=dict(course))
    if request.method == "POST":
        form, v = _validate_course(db, request.form, existing=course)
        if form.ok:
            with db:
                db.execute("UPDATE courses SET code = ?, name = ?, description = ?, updated_at = datetime('now') "
                           "WHERE id = ?", (v["code"], v["name"], v["description"], course_id))
            flash("Course updated.", "success")
            return redirect(url_for("admin.courses"))
        return render_template("admin/course_form.html", form=form, course=course), 400
    return render_template("admin/course_form.html", form=form, course=course)


@bp.route("/courses/<int:course_id>/delete", methods=["GET", "POST"])
def course_delete(course_id):
    db = get_db()
    course = _get_course(db, course_id)
    in_use = (scalar(db, "SELECT COUNT(*) FROM students WHERE course_id = ?", (course_id,))
              + scalar(db, "SELECT COUNT(*) FROM marks WHERE course_id = ?", (course_id,))
              + scalar(db, "SELECT COUNT(*) FROM course_completions WHERE course_id = ?", (course_id,)))
    if in_use:
        flash("This course is in use by students, marks or completion records and cannot be deleted.", "danger")
        return redirect(url_for("admin.courses"))
    if request.method == "POST":
        with db:
            db.execute("DELETE FROM courses WHERE id = ?", (course_id,))
        flash("Course deleted.", "success")
        return redirect(url_for("admin.courses"))
    return render_template("confirm_delete.html", heading="Delete course?",
                           subject=f"{course['name']} ({course['code']})",
                           consequences=["This cannot be undone."], cancel_url=url_for("admin.courses"))


# --------------------------------------------------------------------------
# Attendance & marks overview
# --------------------------------------------------------------------------
@bp.get("/attendance")
def attendance():
    db = get_db()
    q, course_id, low = _filters()
    threshold = get_threshold(db)
    rows = list_students(db, q=q, course_id=course_id)
    if low:
        rows = [s for s in rows if is_low(s, threshold)]
    return render_template(
        "admin/attendance.html", students=rows, q=q, course_id=course_id, low=low, threshold=threshold,
        courses=db.execute("SELECT id, code, name FROM courses ORDER BY name").fetchall())

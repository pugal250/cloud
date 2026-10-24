from datetime import date

from flask import Blueprint, abort, flash, g, redirect, render_template, request, url_for

from .db import get_db
from .security import require_role
from .services import (
    KINDS, STATUSES, attendance_breakdown, attendance_records, get_staff_by_user, get_student,
    get_threshold, is_low, list_students, list_submissions, marks_for, pending_counts,
)
from .validators import Form

bp = Blueprint("staff", __name__, url_prefix="/staff")


@bp.before_request
def _guard():
    resp = require_role("staff")
    if resp is not None:
        return resp
    g.staff = get_staff_by_user(get_db(), g.user["id"])
    if g.staff is None:
        abort(403)


def _my_student_or_404(db, student_id):
    student = get_student(db, student_id)
    if student is None or student["staff_id"] != g.staff["id"]:
        abort(404)  # staff only see students assigned to them
    return student


@bp.get("/")
def dashboard():
    db = get_db()
    sid = g.staff["id"]
    q = request.args.get("q", "").strip()[:60]
    threshold = get_threshold(db)
    return render_template(
        "staff/dashboard.html",
        students=list_students(db, q=q, staff_id=sid),
        q=q,
        threshold=threshold,
        pending=pending_counts(db, staff_id=sid),
        pending_items={
            kind: list_submissions(db, kind, staff_id=sid, status="pending", limit=5) for kind in KINDS
        },
        kinds=KINDS,
    )


@bp.get("/students/<int:student_id>")
def student_detail(student_id):
    db = get_db()
    student = _my_student_or_404(db, student_id)
    return render_template(
        "staff/student_detail.html",
        student=student,
        threshold=get_threshold(db),
        breakdown=attendance_breakdown(db, student_id),
        attendance=attendance_records(db, student_id, limit=60),
        marks=marks_for(db, student_id),
        form=Form(prefill={"attendance_date": date.today().isoformat(), "status": "present"}),
    )


@bp.post("/students/<int:student_id>/attendance")
def record_attendance(student_id):
    db = get_db()
    _my_student_or_404(db, student_id)
    form = Form(request.form)
    day = form.date("attendance_date", "Date", min_date=date(2000, 1, 1), max_date=date.today())
    status = form.choice("status", "Status", ("present", "absent", "late", "excused"))
    if not form.ok:
        flash(form.first_error(), "danger")
    else:
        with db:
            db.execute(
                "INSERT INTO attendance (student_id, attendance_date, status, recorded_by) VALUES (?, ?, ?, ?) "
                "ON CONFLICT(student_id, attendance_date) DO UPDATE SET status = excluded.status, "
                "recorded_by = excluded.recorded_by",
                (student_id, day.isoformat(), status, g.user["id"]),
            )
        flash("Attendance saved.", "success")
    return redirect(url_for("staff.student_detail", student_id=student_id))


@bp.post("/students/<int:student_id>/marks")
def record_marks(student_id):
    db = get_db()
    student = _my_student_or_404(db, student_id)
    form = Form(request.form)
    assessment = form.text("assessment", "Assessment", min_len=2, max_len=80)
    score = form.number("score", "Score", minimum=0, maximum=100000)
    max_score = form.number("max_score", "Maximum score", minimum=0.01, maximum=100000)
    if score is not None and max_score is not None and score > max_score:
        form.error("score", "Score cannot be higher than the maximum score.")
    if not form.ok:
        flash(form.first_error(), "danger")
    else:
        with db:
            db.execute(
                "INSERT INTO marks (student_id, course_id, assessment, score, max_score, recorded_by) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (student_id, student["course_id"], assessment, score, max_score, g.user["id"]),
            )
        flash("Marks saved.", "success")
    return redirect(url_for("staff.student_detail", student_id=student_id))


@bp.get("/reviews/<kind>")
def reviews(kind):
    if kind not in KINDS:
        abort(404)
    status = request.args.get("status", "pending")
    if status not in STATUSES and status != "all":
        status = "pending"
    q = request.args.get("q", "").strip()[:60]
    db = get_db()
    items = list_submissions(
        db, kind, staff_id=g.staff["id"], status=None if status == "all" else status, q=q
    )
    return render_template(
        "staff/reviews.html", kind=kind, meta=KINDS[kind], items=items, status=status, q=q,
        pending=pending_counts(db, staff_id=g.staff["id"]),
    )


@bp.post("/reviews/<kind>/<int:item_id>")
def review(kind, item_id):
    if kind not in KINDS:
        abort(404)
    table = KINDS[kind]["table"]
    db = get_db()
    row = db.execute(
        f"SELECT x.id, x.status, s.staff_id FROM {table} x JOIN students s ON s.id = x.student_id WHERE x.id = ?",
        (item_id,),
    ).fetchone()
    if row is None or row["staff_id"] != g.staff["id"]:
        abort(404)

    back = redirect(url_for("staff.reviews", kind=kind, status=request.form.get("return_status") if request.form.get("return_status") in STATUSES + ("all",) else "pending"))
    form = Form(request.form)
    decision = form.choice("decision", "Decision", ("approved", "rejected"))
    note = form.text("note", "Review note", min_len=3, max_len=500)
    if not form.ok:
        flash(form.first_error(), "danger")
        return back
    with db:
        cur = db.execute(
            f"UPDATE {table} SET status = ?, review_note = ?, reviewed_by = ?, reviewed_at = datetime('now'), "
            "updated_at = datetime('now') WHERE id = ? AND status = 'pending'",
            (decision, note, g.user["id"], item_id),
        )
    if cur.rowcount == 0:
        flash("That submission has already been reviewed.", "warning")
    else:
        flash(f"Submission {decision}.", "success")
    return back

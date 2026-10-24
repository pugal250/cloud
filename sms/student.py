from datetime import date, timedelta

from flask import Blueprint, abort, flash, g, redirect, render_template, request, url_for

from .db import get_db
from .security import UploadError, remove_uploads, require_role, save_upload
from .services import (
    attendance_breakdown, attendance_records, get_student_by_user, get_threshold,
    list_submissions, marks_for,
)
from .validators import Form

bp = Blueprint("student", __name__, url_prefix="/student")


@bp.before_request
def _guard():
    resp = require_role("student")
    if resp is not None:
        return resp
    g.student = get_student_by_user(get_db(), g.user["id"])  # always the logged-in student's own record
    if g.student is None:
        abort(403)


@bp.get("/")
def dashboard():
    db = get_db()
    me = g.student
    sid = me["id"]
    completions = list_submissions(db, "completions", student_id=sid)
    # Completion status for the enrolled course (latest submission wins)
    course_completion = next((c for c in completions if c["course_id"] == me["course_id"]), None)
    return render_template(
        "student/dashboard.html",
        student=me,
        threshold=get_threshold(db),
        breakdown=attendance_breakdown(db, sid),
        attendance=attendance_records(db, sid, limit=30),
        marks=marks_for(db, sid),
        course_completion=course_completion,
        certificates=list_submissions(db, "certificates", student_id=sid, limit=3),
        leaves=list_submissions(db, "leaves", student_id=sid, limit=3),
    )


@bp.route("/certificates", methods=["GET", "POST"])
def certificates():
    db = get_db()
    form = Form(prefill={})
    if request.method == "POST":
        form = Form(request.form)
        title = form.text("title", "Certificate title", min_len=3, max_len=120)
        issuer = form.text("issuer", "Issuing organisation", required=False, max_len=120)
        issued_on = form.date("issued_on", "Issue date", required=False, max_date=date.today())
        stored = None
        if form.ok:
            try:
                stored, original = save_upload(request.files.get("file"), "Certificate file")
            except UploadError as exc:
                form.error("file", str(exc))
        if form.ok:
            try:
                with db:
                    db.execute(
                        "INSERT INTO certificate_submissions "
                        "(student_id, title, issuer, issued_on, stored_filename, original_filename) "
                        "VALUES (?, ?, ?, ?, ?, ?)",
                        (g.student["id"], title, issuer, issued_on.isoformat() if issued_on else None, stored, original),
                    )
            except Exception:
                remove_uploads([stored])
                raise
            flash("Certificate uploaded. Staff will review it soon.", "success")
            return redirect(url_for("student.certificates"))
        return render_template(
            "student/certificates.html", form=form,
            items=list_submissions(db, "certificates", student_id=g.student["id"]),
        ), 400
    return render_template(
        "student/certificates.html", form=form,
        items=list_submissions(db, "certificates", student_id=g.student["id"]),
    )


@bp.route("/completions", methods=["GET", "POST"])
def completions():
    db = get_db()
    courses = db.execute("SELECT id, code, name FROM courses ORDER BY name").fetchall()
    form = Form(prefill={"course_id": g.student["course_id"] or ""})
    if request.method == "POST":
        form = Form(request.form)
        course_id = form.ref("course_id", "Course", {c["id"] for c in courses}, required=True)
        completed_on = form.date("completed_on", "Completion date", max_date=date.today())
        details = form.text("details", "Completion details", min_len=10, max_len=1000)
        stored = None
        if form.ok:
            try:
                stored, original = save_upload(request.files.get("file"), "Completion certificate")
            except UploadError as exc:
                form.error("file", str(exc))
        if form.ok:
            try:
                with db:
                    db.execute(
                        "INSERT INTO course_completions "
                        "(student_id, course_id, completed_on, details, stored_filename, original_filename) "
                        "VALUES (?, ?, ?, ?, ?, ?)",
                        (g.student["id"], course_id, completed_on.isoformat(), details, stored, original),
                    )
            except Exception:
                remove_uploads([stored])
                raise
            flash("Course completion submitted for review.", "success")
            return redirect(url_for("student.completions"))
        return render_template(
            "student/completions.html", form=form, courses=courses,
            items=list_submissions(db, "completions", student_id=g.student["id"]),
        ), 400
    return render_template(
        "student/completions.html", form=form, courses=courses,
        items=list_submissions(db, "completions", student_id=g.student["id"]),
    )


@bp.route("/leaves", methods=["GET", "POST"])
def leaves():
    db = get_db()
    form = Form(prefill={})
    if request.method == "POST":
        form = Form(request.form)
        today = date.today()
        start = form.date("start_date", "Start date", min_date=today - timedelta(days=30), max_date=today + timedelta(days=365))
        end = form.date("end_date", "End date", max_date=today + timedelta(days=365))
        reason = form.text("reason", "Reason", min_len=5, max_len=500)
        if start and end:
            if end < start:
                form.error("end_date", "End date cannot be before the start date.")
            elif (end - start).days > 90:
                form.error("end_date", "A leave request cannot be longer than 90 days.")
        if form.ok:
            with db:
                db.execute(
                    "INSERT INTO leave_requests (student_id, start_date, end_date, reason) VALUES (?, ?, ?, ?)",
                    (g.student["id"], start.isoformat(), end.isoformat(), reason),
                )
            flash("Leave request submitted.", "success")
            return redirect(url_for("student.leaves"))
        return render_template(
            "student/leaves.html", form=form, items=list_submissions(db, "leaves", student_id=g.student["id"]),
        ), 400
    return render_template(
        "student/leaves.html", form=form, items=list_submissions(db, "leaves", student_id=g.student["id"]),
    )

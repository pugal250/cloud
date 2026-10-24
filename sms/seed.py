"""Demo data. Demo passwords are for local testing only - change or delete these accounts in real use."""
import os
import random
import uuid
from datetime import date, timedelta

from flask import current_app

from .security import hash_password

DEMO_PASSWORDS = {"admin": "Admin@123", "staff": "Staff@123", "student": "Student@123"}

COURSES = [
    ("CS101", "Computer Science", "Programming, data structures and databases."),
    ("BUS201", "Business Administration", "Management, marketing and finance basics."),
    ("ME301", "Mechanical Engineering", "Mechanics, thermodynamics and design."),
]
STAFF = [
    ("staff1", "Priya Nair", "priya.nair@example.edu", "EMP001", "Computer Science"),
    ("staff2", "Rahul Mehta", "rahul.mehta@example.edu", "EMP002", "Business & Engineering"),
]
# username, name, student id, course index, staff index, attendance probability
STUDENTS = [
    ("student1", "Aarav Sharma", "STU001", 0, 0, 0.95),
    ("student2", "Diya Patel", "STU002", 0, 0, 0.88),
    ("student3", "Kabir Singh", "STU003", 0, 0, 0.62),   # low attendance
    ("student4", "Meera Iyer", "STU004", 1, 1, 0.91),
    ("student5", "Rohan Gupta", "STU005", 1, 1, 0.70),   # low attendance
    ("student6", "Sneha Reddy", "STU006", 2, 1, 0.82),
    ("student7", "Vikram Das", "STU007", 2, 1, 0.55),    # low attendance
    ("student8", "Ananya Roy", "STU008", 0, 0, 0.93),
]


def _tiny_pdf(text):
    text = "".join(ch for ch in text if ch.isalnum() or ch == " ")
    stream = f"BT /F1 16 Tf 20 70 Td ({text}) Tj ET".encode()
    objs = [
        b"<</Type/Catalog/Pages 2 0 R>>",
        b"<</Type/Pages/Kids[3 0 R]/Count 1>>",
        b"<</Type/Page/Parent 2 0 R/MediaBox[0 0 360 144]/Contents 4 0 R/Resources<</Font<</F1 5 0 R>>>>>>",
        b"<</Length %d>>\nstream\n" % len(stream) + stream + b"\nendstream",
        b"<</Type/Font/Subtype/Type1/BaseFont/Helvetica>>",
    ]
    out, offsets = b"%PDF-1.4\n", []
    for i, obj in enumerate(objs, 1):
        offsets.append(len(out))
        out += b"%d 0 obj\n" % i + obj + b"\nendobj\n"
    xref = len(out)
    out += b"xref\n0 %d\n0000000000 65535 f \n" % (len(objs) + 1)
    for off in offsets:
        out += b"%010d 00000 n \n" % off
    out += b"trailer<</Size %d/Root 1 0 R>>\nstartxref\n%d\n%%%%EOF\n" % (len(objs) + 1, xref)
    return out


def _write_demo_file(label):
    name = f"{uuid.uuid4().hex}.pdf"
    folder = current_app.config["UPLOAD_FOLDER"]
    os.makedirs(folder, exist_ok=True)
    with open(os.path.join(folder, name), "wb") as fh:
        fh.write(_tiny_pdf(label))
    return name


def seed_demo(db):
    """Returns False if demo data already exists."""
    if db.execute("SELECT 1 FROM users WHERE username = 'admin'").fetchone():
        return False
    rng = random.Random(42)
    hashes = {role: hash_password(pw) for role, pw in DEMO_PASSWORDS.items()}  # one hash per role (demo only)
    today = date.today()

    with db:
        db.execute("INSERT INTO users (username, email, full_name, password_hash, role) VALUES (?, ?, ?, ?, 'admin')",
                   ("admin", "admin@example.edu", "Site Administrator", hashes["admin"]))
        course_ids = [db.execute("INSERT INTO courses (code, name, description) VALUES (?, ?, ?)", c).lastrowid
                      for c in COURSES]

        staff_ids, staff_users = [], []
        for username, name, email, code, dept in STAFF:
            uid = db.execute("INSERT INTO users (username, email, full_name, password_hash, role) "
                             "VALUES (?, ?, ?, ?, 'staff')", (username, email, name, hashes["staff"])).lastrowid
            staff_users.append(uid)
            staff_ids.append(db.execute("INSERT INTO staff (user_id, employee_code, department, phone) "
                                        "VALUES (?, ?, ?, '9876500000')", (uid, code, dept)).lastrowid)

        days = [today - timedelta(days=i) for i in range(1, 45) if (today - timedelta(days=i)).weekday() < 5][:30]
        for n, (username, name, code, ci, si, p_present) in enumerate(STUDENTS, 1):
            uid = db.execute("INSERT INTO users (username, email, full_name, password_hash, role) "
                             "VALUES (?, ?, ?, ?, 'student')",
                             (username, f"{username}@example.edu", name, hashes["student"])).lastrowid
            sid = db.execute(
                "INSERT INTO students (user_id, student_code, phone, date_of_birth, address, course_id, staff_id) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                (uid, code, f"98765000{n:02d}", f"2005-0{(n % 9) + 1}-1{n % 9}", f"{n} Demo Street, Chennai",
                 course_ids[ci], staff_ids[si])).lastrowid
            for d in days:
                r = rng.random()
                if r < p_present:
                    status = "late" if rng.random() < 0.08 else "present"
                elif rng.random() < 0.15:
                    status = "excused"
                else:
                    status = "absent"
                db.execute("INSERT INTO attendance (student_id, attendance_date, status, recorded_by) "
                           "VALUES (?, ?, ?, ?)", (sid, d.isoformat(), status, staff_users[si]))
            for assessment, mx in (("Quiz 1", 20), ("Mid-term exam", 50), ("Assignment 1", 30)):
                db.execute("INSERT INTO marks (student_id, course_id, assessment, score, max_score, recorded_by) "
                           "VALUES (?, ?, ?, ?, ?, ?)",
                           (sid, course_ids[ci], assessment, round(mx * rng.uniform(0.5, 0.97), 1), mx, staff_users[si]))

            # sample submissions for the first few students
            if n <= 5:
                f = _write_demo_file(f"{name} certificate")
                status = ("pending", "approved", "rejected", "pending", "approved")[n - 1]
                note = {"approved": "Verified against the issuer.", "rejected": "Scan is unreadable - please re-upload."}.get(status)
                db.execute(
                    "INSERT INTO certificate_submissions (student_id, title, issuer, issued_on, stored_filename, "
                    "original_filename, status, review_note, reviewed_by, reviewed_at) VALUES (?,?,?,?,?,?,?,?,?,?)",
                    (sid, ["Python Basics", "Data Analysis", "First Aid", "Public Speaking", "Excel Essentials"][n - 1],
                     "Open Learning Academy", (today - timedelta(days=20 + n)).isoformat(), f, "certificate.pdf",
                     status, note, staff_users[si] if note else None, today.isoformat() if note else None))
            if n in (1, 4):
                f = _write_demo_file(f"{name} course completion")
                status = "approved" if n == 1 else "pending"
                db.execute(
                    "INSERT INTO course_completions (student_id, course_id, completed_on, details, stored_filename, "
                    "original_filename, status, review_note, reviewed_by, reviewed_at) VALUES (?,?,?,?,?,?,?,?,?,?)",
                    (sid, course_ids[ci], (today - timedelta(days=10)).isoformat(),
                     "Completed all modules and the final project with distinction.", f, "completion.pdf", status,
                     "Great work." if n == 1 else None, staff_users[si] if n == 1 else None,
                     today.isoformat() if n == 1 else None))
            if n in (2, 3, 5):
                status = {2: "pending", 3: "approved", 5: "rejected"}[n]
                db.execute(
                    "INSERT INTO leave_requests (student_id, start_date, end_date, reason, status, review_note, "
                    "reviewed_by, reviewed_at) VALUES (?,?,?,?,?,?,?,?)",
                    (sid, (today + timedelta(days=3)).isoformat(), (today + timedelta(days=5)).isoformat(),
                     "Family function out of town.", status,
                     {"approved": "Approved. Please catch up on notes.", "rejected": "Exam week - leave not possible."}.get(status),
                     staff_users[si] if status != "pending" else None, today.isoformat() if status != "pending" else None))
    return True

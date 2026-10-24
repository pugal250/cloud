"""Smoke + security tests.  Run:  python -m unittest discover -s tests -v"""
import io
import os
import re
import shutil
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sms import create_app  # noqa: E402
from sms.db import get_db, init_db  # noqa: E402
from sms.seed import seed_demo  # noqa: E402

PDF = b"%PDF-1.4\n%test\n"


class Base(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp()
        cls.app = create_app({
            "TESTING": True, "SECRET_KEY": "test",
            "DATABASE": os.path.join(cls.tmp, "t.sqlite3"), "UPLOAD_FOLDER": os.path.join(cls.tmp, "up"),
        })
        with cls.app.app_context():
            init_db()
            seed_demo(get_db())

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def setUp(self):
        self.client = self.app.test_client()

    def token(self, path="/login"):
        html = self.client.get(path).get_data(as_text=True)
        return re.search(r'name="csrf_token" value="([^"]+)"', html).group(1)

    def login(self, user, pw):
        return self.client.post("/login", data={"username": user, "password": pw, "csrf_token": self.token()})

    def post(self, path, data, page=None, **kw):
        data = dict(data, csrf_token=self.token(page or path.rsplit("/", 1)[0] or "/"))
        return self.client.post(path, data=data, **kw)


class AuthTests(Base):
    def test_login_required_and_redirect(self):
        r = self.client.get("/student/")
        self.assertEqual(r.status_code, 302)
        self.assertIn("/login", r.headers["Location"])

    def test_csrf_enforced(self):
        self.client.get("/login")
        r = self.client.post("/login", data={"username": "admin", "password": "Admin@123"})
        self.assertEqual(r.status_code, 400)

    def test_bad_password(self):
        self.assertEqual(self.login("admin", "wrong").status_code, 401)

    def test_repeated_failures_do_not_block_login(self):
        for _ in range(6):
            self.assertEqual(self.login("admin", "wrong").status_code, 401)
        response = self.login("admin", "Admin@123")
        self.assertIn("/admin/", response.headers["Location"])

    def test_roles_redirect_and_isolation(self):
        self.assertIn("/admin/", self.login("admin", "Admin@123").headers["Location"])
        self.assertEqual(self.client.get("/admin/").status_code, 200)
        self.assertEqual(self.client.get("/student/").status_code, 403)
        self.assertEqual(self.client.get("/staff/").status_code, 403)

    def test_passwords_hashed(self):
        with self.app.app_context():
            for (h,) in get_db().execute("SELECT password_hash FROM users"):
                self.assertTrue(h.startswith("pbkdf2:"))
                self.assertNotIn("Admin@123", h)
                self.assertNotIn("Staff@123", h)
                self.assertNotIn("Student@123", h)


class StudentTests(Base):
    def setUp(self):
        super().setUp()
        self.login("student1", "Student@123")

    def test_dashboard(self):
        html = self.client.get("/student/").get_data(as_text=True)
        self.assertIn("Aarav Sharma", html)
        self.assertIn("Attendance", html)

    def test_upload_validation(self):
        tok = self.token("/student/certificates")
        bad = self.client.post("/student/certificates", data={
            "csrf_token": tok, "title": "Bad", "file": (io.BytesIO(b"MZ not a pdf"), "x.pdf")},
            content_type="multipart/form-data")
        self.assertEqual(bad.status_code, 400)
        self.assertIn("does not match", bad.get_data(as_text=True))
        exe = self.client.post("/student/certificates", data={
            "csrf_token": tok, "title": "Bad", "file": (io.BytesIO(PDF), "x.exe")},
            content_type="multipart/form-data")
        self.assertIn("Only PDF, PNG or JPG", exe.get_data(as_text=True))
        big = self.client.post("/student/certificates", data={
            "csrf_token": tok, "title": "Big", "file": (io.BytesIO(PDF + b"0" * (5 * 1024 * 1024)), "x.pdf")},
            content_type="multipart/form-data")
        self.assertIn("too large", big.get_data(as_text=True))

    def test_upload_ok_and_file_access(self):
        tok = self.token("/student/certificates")
        r = self.client.post("/student/certificates", data={
            "csrf_token": tok, "title": "My cert", "file": (io.BytesIO(PDF), "../../evil name.pdf")},
            content_type="multipart/form-data")
        self.assertEqual(r.status_code, 302)
        with self.app.app_context():
            row = get_db().execute("SELECT id, stored_filename, original_filename FROM certificate_submissions "
                                   "WHERE title = 'My cert'").fetchone()
        self.assertNotIn("..", row["stored_filename"])
        self.assertNotIn("/", row["original_filename"])
        self.assertEqual(self.client.get(f"/files/certificates/{row['id']}").status_code, 200)
        # another student cannot read it
        other = self.app.test_client()
        t = re.search(r'value="([^"]+)"', other.get("/login").get_data(as_text=True).split("csrf_token")[1]).group(1)
        other.post("/login", data={"username": "student2", "password": "Student@123", "csrf_token": t})
        self.assertEqual(other.get(f"/files/certificates/{row['id']}").status_code, 404)

    def test_leave_validation(self):
        r = self.post("/student/leaves", {"start_date": "2030-01-05", "end_date": "2030-01-01", "reason": "Trip home"},
                      page="/student/leaves")
        self.assertEqual(r.status_code, 400)
        r = self.post("/student/leaves", {"start_date": "2026-01-01", "end_date": "2026-01-02", "reason": "x"},
                      page="/student/leaves")
        self.assertEqual(r.status_code, 400)


class StaffTests(Base):
    def setUp(self):
        super().setUp()
        self.login("staff1", "Staff@123")

    def test_dashboard_only_assigned(self):
        html = self.client.get("/staff/").get_data(as_text=True)
        self.assertIn("Aarav Sharma", html)
        self.assertNotIn("Meera Iyer", html)  # assigned to staff2

    def test_cannot_open_unassigned_student(self):
        with self.app.app_context():
            sid = get_db().execute("SELECT id FROM students WHERE student_code = 'STU004'").fetchone()["id"]
        self.assertEqual(self.client.get(f"/staff/students/{sid}").status_code, 404)

    def test_review_flow(self):
        with self.app.app_context():
            row = get_db().execute(
                "SELECT l.id FROM leave_requests l JOIN students s ON s.id = l.student_id "
                "WHERE l.status = 'pending' AND s.student_code = 'STU002'").fetchone()
        no_note = self.post(f"/staff/reviews/leaves/{row['id']}", {"decision": "approved", "note": ""},
                            page="/staff/reviews/leaves")
        self.assertEqual(no_note.status_code, 302)
        with self.app.app_context():
            self.assertEqual(get_db().execute("SELECT status FROM leave_requests WHERE id = ?", (row["id"],)).fetchone()[0], "pending")
        self.post(f"/staff/reviews/leaves/{row['id']}", {"decision": "approved", "note": "Fine, enjoy."},
                  page="/staff/reviews/leaves")
        with self.app.app_context():
            self.assertEqual(get_db().execute("SELECT status FROM leave_requests WHERE id = ?", (row["id"],)).fetchone()[0], "approved")

    def test_cannot_review_other_staffs_student(self):
        with self.app.app_context():
            row = get_db().execute(
                "SELECT c.id FROM course_completions c JOIN students s ON s.id = c.student_id "
                "WHERE s.student_code = 'STU004'").fetchone()
        r = self.post(f"/staff/reviews/completions/{row['id']}", {"decision": "approved", "note": "ok ok"},
                      page="/staff/reviews/completions")
        self.assertEqual(r.status_code, 404)


class AdminTests(Base):
    def setUp(self):
        super().setUp()
        self.login("admin", "Admin@123")

    def test_dashboard_low_alerts(self):
        html = self.client.get("/admin/").get_data(as_text=True)
        self.assertIn("Low attendance alerts", html)
        self.assertIn("Vikram Das", html)       # 55% seeded
        self.assertNotIn("Aarav Sharma</td>", html)

    def test_threshold_changes_alerts(self):
        self.post("/admin/settings/threshold", {"attendance_threshold": "10"}, page="/admin/courses")
        html = self.client.get("/admin/").get_data(as_text=True)
        self.assertIn("No low attendance alerts", html)
        self.post("/admin/settings/threshold", {"attendance_threshold": "75"}, page="/admin/courses")
        self.assertEqual(self.post("/admin/settings/threshold", {"attendance_threshold": "150"}, page="/admin/courses").status_code, 302)
        with self.app.app_context():
            from sms.services import get_threshold
            self.assertEqual(get_threshold(get_db()), 75.0)

    def test_student_crud_and_delete_confirmation(self):
        form = {"full_name": "Test Pupil", "username": "pupil1", "email": "pupil1@example.edu", "password": "Passw0rd!",
                "student_code": "STU900", "is_active": "1"}
        bad = self.post("/admin/students/new", dict(form, password="short"), page="/admin/students/new")
        self.assertEqual(bad.status_code, 400)
        ok = self.post("/admin/students/new", form, page="/admin/students/new")
        self.assertEqual(ok.status_code, 302)
        dup = self.post("/admin/students/new", form, page="/admin/students/new")
        self.assertEqual(dup.status_code, 400)
        with self.app.app_context():
            sid = get_db().execute("SELECT id FROM students WHERE student_code = 'STU900'").fetchone()["id"]
        self.assertEqual(self.client.get(f"/admin/students/{sid}").status_code, 200)
        self.assertEqual(self.client.get(f"/admin/students/{sid}/edit").status_code, 200)
        page = self.client.get(f"/admin/students/{sid}/delete")           # GET only asks for confirmation
        self.assertIn("Delete student?", page.get_data(as_text=True))
        with self.app.app_context():
            self.assertIsNotNone(get_db().execute("SELECT 1 FROM students WHERE id = ?", (sid,)).fetchone())
        self.post(f"/admin/students/{sid}/delete", {}, page=f"/admin/students/{sid}/delete")
        with self.app.app_context():
            self.assertIsNone(get_db().execute("SELECT 1 FROM students WHERE id = ?", (sid,)).fetchone())
            self.assertIsNone(get_db().execute("SELECT 1 FROM users WHERE username = 'pupil1'").fetchone())

    def test_staff_and_course_pages(self):
        for path in ("/admin/staff", "/admin/staff/new", "/admin/courses", "/admin/courses/new",
                     "/admin/attendance", "/admin/students?q=Aarav&low=1"):
            self.assertEqual(self.client.get(path).status_code, 200, path)
        r = self.post("/admin/staff/new", {"full_name": "New Teacher", "username": "teach9", "email": "t9@example.edu",
                      "password": "Teach1234", "employee_code": "EMP900", "is_active": "1"}, page="/admin/staff/new")
        self.assertEqual(r.status_code, 302)

    def test_search_injection_safe(self):
        r = self.client.get("/admin/students?q=%27%20OR%201%3D1%20--")
        self.assertEqual(r.status_code, 200)
        self.assertIn("No students found", r.get_data(as_text=True))

    def test_course_in_use_cannot_be_deleted(self):
        with self.app.app_context():
            cid = get_db().execute("SELECT id FROM courses WHERE code = 'CS101'").fetchone()["id"]
        self.post(f"/admin/courses/{cid}/delete", {}, page="/admin/courses")
        with self.app.app_context():
            self.assertIsNotNone(get_db().execute("SELECT 1 FROM courses WHERE id = ?", (cid,)).fetchone())

    def test_security_headers(self):
        r = self.client.get("/admin/")
        self.assertIn("default-src 'self'", r.headers["Content-Security-Policy"])
        self.assertEqual(r.headers["X-Content-Type-Options"], "nosniff")


if __name__ == "__main__":
    unittest.main()

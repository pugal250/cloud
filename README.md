# Student Management System

A small role-based web app for **students, staff and administrators**.
Flask + SQLite backend, vanilla HTML/CSS/JavaScript frontend (no build step). The visual style borrows the
forest-green / lime palette and the icon font of the *Spark Admin* template.

## Features

| Role | What they can do |
|------|------------------|
| **Student** | Log in/out · dashboard with profile, attendance %, attendance records, marks and course-completion status · upload certificates · submit course completion + certificate · request leave · see review status and staff notes |
| **Staff** | Log in/out · dashboard of *assigned* students with attendance and marks · pending-review summaries · approve/reject certificates, course completions and leave requests (review note required) · view student attendance and marks · record attendance and marks |
| **Admin** | Log in/out · dashboard with counts and **low-attendance alerts** (name, ID, %) · add / edit / view / delete students · create and manage staff accounts · view attendance and marks · manage courses and the **attendance threshold** |

Attendance % = (present + late) ÷ (all records except *excused*) × 100.

## Requirements

* Python 3.9 or newer
* Nothing else except the packages in `requirements.txt` (Flask). SQLite ships with Python.

## Setup

```bash
cd student_management

# 1. (recommended) virtual environment
python -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate

# 2. install dependencies
pip install -r requirements.txt

# 3. load demo accounts and sample data (also creates instance/sms.sqlite3;
#    tables are created automatically, `flask --app sms init-db` is optional)
flask --app sms seed-demo

# 4. run
python run.py                      # or: flask --app sms run
```

Open <http://127.0.0.1:5000> and sign in with a demo account.

### Demo accounts (local testing only)

| Role | Username | Password |
|------|----------|----------|
| Admin | `admin` | `Admin@123` |
| Staff | `staff1` (Priya Nair), `staff2` (Rahul Mehta) | `Staff@123` |
| Student | `student1` … `student8` | `Student@123` |

`student3`, `student5`, `student6`, `student7` have lower attendance, so the admin alerts show data
(default threshold 75 %). **Delete or change these accounts before any real use.**

### Your own admin account (instead of / in addition to the demo)

```bash
flask --app sms create-admin
```

### Reset everything

```bash
flask --app sms init-db --reset     # deletes the database and uploaded files
flask --app sms seed-demo
```

## Project layout

```
student_management/
├── run.py                  # python run.py
├── requirements.txt
├── sms/
│   ├── __init__.py         # app factory, config, error pages, template helpers
│   ├── schema.sql          # all SQLite tables
│   ├── db.py               # connection handling
│   ├── security.py         # CSRF, password hashing, role guard, upload validation, login throttle
│   ├── validators.py       # server-side form validation
│   ├── services.py         # shared queries (attendance %, submissions, ...)
│   ├── auth.py             # login / logout
│   ├── student.py  staff.py  admin.py   # role blueprints (/student, /staff, /admin)
│   ├── files.py            # authorised access to uploaded files
│   ├── cli.py  seed.py     # init-db, seed-demo, create-admin
│   ├── templates/          # Jinja2 pages (base, macros, auth, student, staff, admin)
│   └── static/             # css, js, icon font
├── tests/test_app.py       # python -m unittest discover -s tests
└── instance/               # created at runtime: sms.sqlite3, uploads/, secret_key (not for version control)
```

## Database

SQLite tables: `users`, `students`, `staff`, `courses`, `attendance`, `marks`, `settings`,
`certificate_submissions`, `course_completions`, `leave_requests`.
All have `created_at` timestamps; submissions/requests carry a `status`
(`pending` / `approved` / `rejected`), `review_note`, `reviewed_by` and `reviewed_at`.
Foreign keys are enforced (`PRAGMA foreign_keys = ON`); deleting a student removes their user and all related rows,
deleting a staff member un-assigns their students, and a course that is in use cannot be deleted.

## Security notes

* **Passwords** are hashed (PBKDF2-SHA256 via Werkzeug); never stored in plain text. Failed logins are throttled (5 per 10 min per IP + username).
* **Sessions**: Flask signed cookies (HttpOnly, SameSite=Lax), regenerated on login. The secret key comes from `SMS_SECRET_KEY` or is generated once into `instance/secret_key`.
* **Roles**: every route of the `/student`, `/staff`, `/admin` blueprints is guarded centrally. Students only ever query their own `student_id`; staff only see students assigned to them (others return 404); admins see everything.
* **CSRF**: every POST requires a per-session token (hidden field in all forms, including logout).
* **SQL**: all queries use `?` parameters; the only interpolated names are table names from a fixed internal map.
* **Uploads**: PDF/PNG/JPG only, ≤ 5 MB, extension *and* leading file bytes checked, stored under a random name outside `static/`, and downloaded only through `/files/...` after an ownership check. Original names are sanitised with `secure_filename`.
* **Destructive actions** (delete student / staff / course) go through a confirmation page; the delete itself is a CSRF-protected POST.
* **Headers**: strict Content-Security-Policy (no inline scripts/styles), `X-Frame-Options: DENY`, `nosniff`, `no-store`.

### Before deploying for real

* Serve with a production WSGI server (e.g. `gunicorn "sms:create_app()"`) behind HTTPS and set `SMS_COOKIE_SECURE=1`.
* Set a fixed `SMS_SECRET_KEY`, remove the demo accounts, back up `instance/`.
* The login throttle is in-memory (per process); use a shared store if you run several workers.

## Configuration (environment variables)

| Variable | Purpose | Default |
|----------|---------|---------|
| `SMS_SECRET_KEY` | session signing key | generated in `instance/secret_key` |
| `SMS_COOKIE_SECURE` | `1` to send cookies over HTTPS only | off |
| `SMS_HOST`, `SMS_PORT` | for `python run.py` | `127.0.0.1`, `5000` |
| `SMS_DEBUG` | `1` enables Flask debug/reload | off |

## Tests

```bash
python -m unittest discover -s tests -v
```
Covers login/CSRF, role isolation, upload validation, file access control, review workflow,
low-attendance alerts, CRUD and delete confirmation.

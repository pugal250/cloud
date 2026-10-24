-- Student Management System schema (SQLite)
-- Timestamps are stored as UTC text (YYYY-MM-DD HH:MM:SS); dates as YYYY-MM-DD.

CREATE TABLE IF NOT EXISTS users (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    username      TEXT NOT NULL UNIQUE COLLATE NOCASE,
    email         TEXT NOT NULL UNIQUE COLLATE NOCASE,
    full_name     TEXT NOT NULL,
    password_hash TEXT NOT NULL,
    role          TEXT NOT NULL CHECK (role IN ('student', 'staff', 'admin')),
    is_active     INTEGER NOT NULL DEFAULT 1 CHECK (is_active IN (0, 1)),
    last_login_at TEXT,
    created_at    TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at    TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS courses (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    code        TEXT NOT NULL UNIQUE COLLATE NOCASE,
    name        TEXT NOT NULL,
    description TEXT NOT NULL DEFAULT '',
    created_at  TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at  TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS staff (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id       INTEGER NOT NULL UNIQUE REFERENCES users (id) ON DELETE CASCADE,
    employee_code TEXT NOT NULL UNIQUE COLLATE NOCASE,
    department    TEXT NOT NULL DEFAULT '',
    phone         TEXT NOT NULL DEFAULT '',
    created_at    TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at    TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS students (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id       INTEGER NOT NULL UNIQUE REFERENCES users (id) ON DELETE CASCADE,
    student_code  TEXT NOT NULL UNIQUE COLLATE NOCASE,
    phone         TEXT NOT NULL DEFAULT '',
    date_of_birth TEXT,
    address       TEXT NOT NULL DEFAULT '',
    course_id     INTEGER REFERENCES courses (id) ON DELETE RESTRICT,
    staff_id      INTEGER REFERENCES staff (id) ON DELETE SET NULL,   -- assigned staff member
    enrolled_on   TEXT NOT NULL DEFAULT (date('now')),
    created_at    TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at    TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS attendance (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    student_id      INTEGER NOT NULL REFERENCES students (id) ON DELETE CASCADE,
    attendance_date TEXT NOT NULL,
    status          TEXT NOT NULL CHECK (status IN ('present', 'absent', 'late', 'excused')),
    recorded_by     INTEGER REFERENCES users (id) ON DELETE SET NULL,
    created_at      TEXT NOT NULL DEFAULT (datetime('now')),
    UNIQUE (student_id, attendance_date)
);

CREATE TABLE IF NOT EXISTS marks (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    student_id  INTEGER NOT NULL REFERENCES students (id) ON DELETE CASCADE,
    course_id   INTEGER REFERENCES courses (id) ON DELETE RESTRICT,
    assessment  TEXT NOT NULL,
    score       REAL NOT NULL CHECK (score >= 0),
    max_score   REAL NOT NULL CHECK (max_score > 0),
    recorded_by INTEGER REFERENCES users (id) ON DELETE SET NULL,
    created_at  TEXT NOT NULL DEFAULT (datetime('now')),
    CHECK (score <= max_score)
);

CREATE TABLE IF NOT EXISTS settings (
    key        TEXT PRIMARY KEY,
    value      TEXT NOT NULL,
    updated_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS certificate_submissions (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    student_id        INTEGER NOT NULL REFERENCES students (id) ON DELETE CASCADE,
    title             TEXT NOT NULL,
    issuer            TEXT NOT NULL DEFAULT '',
    issued_on         TEXT,
    stored_filename   TEXT NOT NULL,
    original_filename TEXT NOT NULL,
    status            TEXT NOT NULL DEFAULT 'pending' CHECK (status IN ('pending', 'approved', 'rejected')),
    review_note       TEXT,
    reviewed_by       INTEGER REFERENCES users (id) ON DELETE SET NULL,
    reviewed_at       TEXT,
    created_at        TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at        TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS course_completions (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    student_id        INTEGER NOT NULL REFERENCES students (id) ON DELETE CASCADE,
    course_id         INTEGER NOT NULL REFERENCES courses (id) ON DELETE RESTRICT,
    completed_on      TEXT NOT NULL,
    details           TEXT NOT NULL,
    stored_filename   TEXT NOT NULL,
    original_filename TEXT NOT NULL,
    status            TEXT NOT NULL DEFAULT 'pending' CHECK (status IN ('pending', 'approved', 'rejected')),
    review_note       TEXT,
    reviewed_by       INTEGER REFERENCES users (id) ON DELETE SET NULL,
    reviewed_at       TEXT,
    created_at        TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at        TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS leave_requests (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    student_id  INTEGER NOT NULL REFERENCES students (id) ON DELETE CASCADE,
    start_date  TEXT NOT NULL,
    end_date    TEXT NOT NULL,
    reason      TEXT NOT NULL,
    status      TEXT NOT NULL DEFAULT 'pending' CHECK (status IN ('pending', 'approved', 'rejected')),
    review_note TEXT,
    reviewed_by INTEGER REFERENCES users (id) ON DELETE SET NULL,
    reviewed_at TEXT,
    created_at  TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at  TEXT NOT NULL DEFAULT (datetime('now')),
    CHECK (end_date >= start_date)
);

CREATE INDEX IF NOT EXISTS idx_students_staff    ON students (staff_id);
CREATE INDEX IF NOT EXISTS idx_students_course   ON students (course_id);
CREATE INDEX IF NOT EXISTS idx_attendance_student ON attendance (student_id, attendance_date);
CREATE INDEX IF NOT EXISTS idx_marks_student     ON marks (student_id);
CREATE INDEX IF NOT EXISTS idx_cert_student      ON certificate_submissions (student_id, status);
CREATE INDEX IF NOT EXISTS idx_completion_student ON course_completions (student_id, status);
CREATE INDEX IF NOT EXISTS idx_leave_student     ON leave_requests (student_id, status);

INSERT OR IGNORE INTO settings (key, value) VALUES ('attendance_threshold', '75');

"""Shared read queries. Table names come from the fixed KINDS map, never from user input."""

KINDS = {
    "certificates": {"table": "certificate_submissions", "label": "Certificates", "icon": "patch-check"},
    "completions": {"table": "course_completions", "label": "Course completions", "icon": "mortarboard"},
    "leaves": {"table": "leave_requests", "label": "Leave requests", "icon": "calendar2-x"},
}
STATUSES = ("pending", "approved", "rejected")


def scalar(db, sql, params=()):
    return db.execute(sql, params).fetchone()[0]


# -- settings --------------------------------------------------------------
def get_threshold(db):
    row = db.execute("SELECT value FROM settings WHERE key = 'attendance_threshold'").fetchone()
    try:
        return float(row["value"]) if row else 75.0
    except ValueError:
        return 75.0


def set_threshold(db, value):
    with db:
        db.execute(
            "INSERT INTO settings (key, value, updated_at) VALUES ('attendance_threshold', ?, datetime('now')) "
            "ON CONFLICT(key) DO UPDATE SET value = excluded.value, updated_at = excluded.updated_at",
            (f"{value:g}",),
        )


# -- people ----------------------------------------------------------------
_STUDENT_SELECT = """
SELECT s.id, s.user_id, s.student_code, s.phone, s.date_of_birth, s.address, s.course_id,
       s.staff_id, s.enrolled_on, s.created_at,
       u.full_name, u.email, u.username, u.is_active,
       c.name AS course_name, c.code AS course_code,
       su.full_name AS staff_name,
       COALESCE(att.attended, 0) AS attended, COALESCE(att.total, 0) AS total_classes,
       mk.score_sum, mk.max_sum
FROM students s
JOIN users u ON u.id = s.user_id
LEFT JOIN courses c ON c.id = s.course_id
LEFT JOIN staff st ON st.id = s.staff_id
LEFT JOIN users su ON su.id = st.user_id
LEFT JOIN (
    SELECT student_id,
           SUM(CASE WHEN status IN ('present', 'late') THEN 1 ELSE 0 END) AS attended,
           SUM(CASE WHEN status <> 'excused' THEN 1 ELSE 0 END) AS total
    FROM attendance GROUP BY student_id
) att ON att.student_id = s.id
LEFT JOIN (
    SELECT student_id, SUM(score) AS score_sum, SUM(max_score) AS max_sum
    FROM marks GROUP BY student_id
) mk ON mk.student_id = s.id
"""


def _decorate(row):
    d = dict(row)
    total = d["total_classes"]
    d["attendance_pct"] = round(d["attended"] * 100.0 / total, 1) if total else None
    d["marks_pct"] = round(d["score_sum"] * 100.0 / d["max_sum"], 1) if d["max_sum"] else None
    return d


def list_students(db, *, q="", course_id=None, staff_id=None, student_id=None):
    where, params = [], []
    if q:
        like = "%" + q.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"
        where.append(
            "(u.full_name LIKE ? ESCAPE '\\' OR s.student_code LIKE ? ESCAPE '\\' OR u.email LIKE ? ESCAPE '\\')"
        )
        params += [like, like, like]
    if course_id:
        where.append("s.course_id = ?")
        params.append(course_id)
    if staff_id:
        where.append("s.staff_id = ?")
        params.append(staff_id)
    if student_id:
        where.append("s.id = ?")
        params.append(student_id)
    sql = _STUDENT_SELECT
    if where:
        sql += " WHERE " + " AND ".join(where)
    sql += " ORDER BY u.full_name COLLATE NOCASE"
    return [_decorate(r) for r in db.execute(sql, params).fetchall()]


def get_student(db, student_id):
    rows = list_students(db, student_id=student_id)
    return rows[0] if rows else None


def get_student_by_user(db, user_id):
    row = db.execute("SELECT id FROM students WHERE user_id = ?", (user_id,)).fetchone()
    return get_student(db, row["id"]) if row else None


def get_staff_by_user(db, user_id):
    return db.execute(
        "SELECT st.id, st.employee_code, st.department, st.phone, u.full_name "
        "FROM staff st JOIN users u ON u.id = st.user_id WHERE st.user_id = ?",
        (user_id,),
    ).fetchone()


def is_low(student, threshold):
    pct = student["attendance_pct"]
    return pct is not None and pct < threshold


# -- attendance / marks ----------------------------------------------------
def attendance_records(db, student_id, limit=None):
    sql = "SELECT attendance_date, status FROM attendance WHERE student_id = ? ORDER BY attendance_date DESC"
    params = [student_id]
    if limit:
        sql += " LIMIT ?"
        params.append(limit)
    return db.execute(sql, params).fetchall()


def attendance_breakdown(db, student_id):
    out = {"present": 0, "late": 0, "absent": 0, "excused": 0}
    for r in db.execute(
        "SELECT status, COUNT(*) AS n FROM attendance WHERE student_id = ? GROUP BY status", (student_id,)
    ):
        out[r["status"]] = r["n"]
    return out


def marks_for(db, student_id):
    rows = db.execute(
        "SELECT m.id, m.assessment, m.score, m.max_score, m.created_at, c.name AS course_name "
        "FROM marks m LEFT JOIN courses c ON c.id = m.course_id "
        "WHERE m.student_id = ? ORDER BY m.created_at DESC, m.id DESC",
        (student_id,),
    ).fetchall()
    return [dict(r, pct=round(r["score"] * 100.0 / r["max_score"], 1)) for r in rows]


# -- submissions -----------------------------------------------------------
def list_submissions(db, kind, *, student_id=None, staff_id=None, status=None, q="", limit=None):
    table = KINDS[kind]["table"]
    extra_sel = ", c.name AS course_name" if kind == "completions" else ""
    extra_join = "LEFT JOIN courses c ON c.id = x.course_id" if kind == "completions" else ""
    where, params = [], []
    if student_id:
        where.append("x.student_id = ?")
        params.append(student_id)
    if staff_id:
        where.append("s.staff_id = ?")
        params.append(staff_id)
    if status in STATUSES:
        where.append("x.status = ?")
        params.append(status)
    if q:
        like = "%" + q.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"
        where.append("(u.full_name LIKE ? ESCAPE '\\' OR s.student_code LIKE ? ESCAPE '\\')")
        params += [like, like]
    sql = (
        f"SELECT x.*, u.full_name AS student_name, s.student_code, r.full_name AS reviewer_name{extra_sel} "
        f"FROM {table} x "
        "JOIN students s ON s.id = x.student_id JOIN users u ON u.id = s.user_id "
        f"LEFT JOIN users r ON r.id = x.reviewed_by {extra_join}"
    )
    if where:
        sql += " WHERE " + " AND ".join(where)
    sql += " ORDER BY CASE x.status WHEN 'pending' THEN 0 ELSE 1 END, x.created_at DESC, x.id DESC"
    if limit:
        sql += " LIMIT ?"
        params.append(limit)
    return db.execute(sql, params).fetchall()


def pending_counts(db, staff_id=None):
    counts = {}
    for kind, meta in KINDS.items():
        sql = f"SELECT COUNT(*) FROM {meta['table']} x JOIN students s ON s.id = x.student_id WHERE x.status = 'pending'"
        params = ()
        if staff_id:
            sql += " AND s.staff_id = ?"
            params = (staff_id,)
        counts[kind] = scalar(db, sql, params)
    counts["total"] = sum(counts.values())
    return counts

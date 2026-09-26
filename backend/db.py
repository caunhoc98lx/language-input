"""MySQL access via PyMySQL. Thin sqlite3-style wrapper (conn.execute with
'?' placeholders, dict-like rows) so callers didn't need to change.

ponytail: previously Postgres/psycopg2. MySQL lacks several things that
schema/queries leaned on - RETURNING, FILTER (WHERE ...), ON CONFLICT,
CREATE INDEX IF NOT EXISTS, and DEFAULT CURRENT_TIMESTAMP on a non-temporal
column - so this file (and the ~25 call sites across main.py that used
those) were rewritten, not just the connection string. See MIGRATION_NOTES
below for exactly what changed and why.
"""
import os
from contextlib import contextmanager
from urllib.parse import urlparse

import pymysql
import pymysql.cursors
import pymysql.err

DATABASE_URL = os.environ.get("DATABASE_URL", "")

# Tables. id SERIAL -> id INT AUTO_INCREMENT (MySQL has no SERIAL shorthand
# combinable with PRIMARY KEY the way Postgres does). Columns that used to
# be `TEXT DEFAULT CURRENT_TIMESTAMP` are now plain TEXT/VARCHAR with no
# default - MySQL only allows CURRENT_TIMESTAMP as a default on TIMESTAMP/
# DATETIME columns, and this app's ISO-8601-with-offset strings
# (`datetime.now(timezone.utc).isoformat()`) don't match MySQL's own
# CURRENT_TIMESTAMP string format anyway, so every caller now supplies the
# timestamp explicitly instead of relying on either database's default -
# one consistent format regardless of engine. Columns that appear in a
# UNIQUE constraint or an index are VARCHAR, not TEXT: MySQL refuses to
# index a TEXT/BLOB column without an explicit prefix length.
SCHEMA_TABLES = """
CREATE TABLE IF NOT EXISTS users (
    id INT AUTO_INCREMENT PRIMARY KEY,
    email VARCHAR(255) UNIQUE NOT NULL,
    password_hash TEXT NOT NULL,
    name TEXT,
    native_language TEXT,
    ielts_target REAL,
    ielts_current REAL,
    daily_goal_minutes INTEGER DEFAULT 30,
    streak INTEGER DEFAULT 0,
    last_active_date TEXT,
    created_at TEXT
);

CREATE TABLE IF NOT EXISTS vocabulary (
    id INT AUTO_INCREMENT PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES users(id),
    word TEXT NOT NULL,
    normalized_word VARCHAR(255) NOT NULL,
    translation TEXT,
    definition TEXT,
    part_of_speech TEXT,
    pronunciation TEXT,
    phonetic TEXT,
    examples_json TEXT,
    synonyms_json TEXT,
    antonyms_json TEXT,
    collocations_json TEXT,
    ielts_level TEXT,
    topic TEXT,
    memory_tip TEXT,
    notes TEXT,
    srs_state VARCHAR(20),
    ease REAL DEFAULT 2.5,
    interval_days REAL DEFAULT 0,
    repetitions INTEGER DEFAULT 0,
    lapses INTEGER DEFAULT 0,
    next_review_at VARCHAR(40),
    last_reviewed_at TEXT,
    starred INTEGER DEFAULT 0,
    created_at TEXT,
    updated_at TEXT,
    UNIQUE(user_id, normalized_word)
);

CREATE TABLE IF NOT EXISTS vocabulary_sets (
    id INT AUTO_INCREMENT PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES users(id),
    title TEXT NOT NULL,
    description TEXT,
    created_at TEXT
);

CREATE TABLE IF NOT EXISTS set_words (
    set_id INTEGER NOT NULL REFERENCES vocabulary_sets(id),
    vocabulary_id INTEGER NOT NULL REFERENCES vocabulary(id),
    PRIMARY KEY (set_id, vocabulary_id)
);

CREATE TABLE IF NOT EXISTS reviews (
    id INT AUTO_INCREMENT PRIMARY KEY,
    vocabulary_id INTEGER NOT NULL REFERENCES vocabulary(id),
    user_id INTEGER NOT NULL REFERENCES users(id),
    rating TEXT NOT NULL,
    interval_before REAL,
    interval_after REAL,
    reviewed_at VARCHAR(40)
);

CREATE TABLE IF NOT EXISTS daily_tasks (
    id INT AUTO_INCREMENT PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES users(id),
    task_date VARCHAR(20) NOT NULL,
    kind VARCHAR(20) NOT NULL,
    content_json TEXT NOT NULL,
    created_at TEXT,
    UNIQUE(user_id, task_date, kind)
);

CREATE TABLE IF NOT EXISTS daily_attempts (
    id INT AUTO_INCREMENT PRIMARY KEY,
    task_id INTEGER NOT NULL REFERENCES daily_tasks(id),
    user_id INTEGER NOT NULL REFERENCES users(id),
    answers_json TEXT,
    score INTEGER,
    total INTEGER,
    band REAL,
    feedback_json TEXT,
    submitted_at VARCHAR(40)
);

-- One row per finished game session (the gamified /study/anki screen). The
-- unique request_id makes crediting XP/coins idempotent, same idea as reviews.
CREATE TABLE IF NOT EXISTS game_sessions (
    id INT AUTO_INCREMENT PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES users(id),
    request_id VARCHAR(64) NOT NULL UNIQUE,
    xp INTEGER NOT NULL,
    coins INTEGER NOT NULL,
    best_combo INTEGER NOT NULL,
    correct INTEGER NOT NULL,
    total INTEGER NOT NULL,
    boss_won BOOLEAN NOT NULL,
    completed_at VARCHAR(40)
);
"""

# Indexes, kept separate from SCHEMA_TABLES: MySQL has no
# `CREATE INDEX IF NOT EXISTS`, so these are created one at a time in
# init_db(), each tolerating "already exists" instead of relying on the
# database to no-op like the table DDL above does.
SCHEMA_INDEXES = [
    ("idx_vocab_user_next", "CREATE INDEX idx_vocab_user_next ON vocabulary(user_id, next_review_at)"),
    ("idx_vocab_user_norm", "CREATE INDEX idx_vocab_user_norm ON vocabulary(user_id, normalized_word)"),
    ("idx_reviews_user_time", "CREATE INDEX idx_reviews_user_time ON reviews(user_id, reviewed_at)"),
    ("idx_daily_tasks_user_date", "CREATE INDEX idx_daily_tasks_user_date ON daily_tasks(user_id, task_date)"),
    ("idx_daily_attempts_task", "CREATE INDEX idx_daily_attempts_task ON daily_attempts(task_id)"),
    ("idx_daily_attempts_user_time", "CREATE INDEX idx_daily_attempts_user_time ON daily_attempts(user_id, submitted_at)"),
    # Unique, not just an index: this is what makes a review's request_id an
    # idempotency key. MySQL unique indexes already treat every NULL as
    # distinct (same as Postgres's plain UNIQUE), so no partial-index
    # WHERE clause is needed here the way Postgres required one.
    ("idx_reviews_request_id", "CREATE UNIQUE INDEX idx_reviews_request_id ON reviews(request_id)"),
]

ERR_DUP_KEYNAME = 1061  # MySQL: "Duplicate key name" - the index already exists


def _convert_placeholders(sql: str) -> str:
    """Turn '?' placeholders into PyMySQL's '%s', leaving string literals alone.

    A plain .replace() also rewrites the '?' inside 'Do you agree?', which
    PyMySQL then treats as a missing parameter - a confusing IndexError far from
    the actual mistake. This walks the statement instead, which is cheap and
    removes the trap entirely.
    """
    out = []
    quote = None
    for ch in sql:
        if ch == "%":
            out.append("%%")  # a literal % must survive PyMySQL's own formatting,
            continue          # inside quotes (LIKE patterns) as much as outside
        if quote:
            out.append(ch)
            if ch == quote:
                quote = None
            continue
        if ch in ("'", '"'):
            quote = ch
            out.append(ch)
        elif ch == "?":
            out.append("%s")
        else:
            out.append(ch)
    return "".join(out)


class _ReturningIdCursor:
    """Wraps a PyMySQL cursor so `INSERT ... RETURNING id` keeps working.

    MySQL has no RETURNING; `_convert_placeholders`'s caller strips the
    clause before sending the query and this wraps the result so
    `.fetchone()["id"]` - the pattern every call site already uses - still
    works, backed by `cursor.lastrowid` instead.
    """
    def __init__(self, cursor):
        self._cursor = cursor

    def fetchone(self):
        return {"id": self._cursor.lastrowid}

    def __getattr__(self, name):
        return getattr(self._cursor, name)


class Conn:
    def __init__(self, mysql_conn):
        self._conn = mysql_conn

    def execute(self, sql, params=None):
        cur = self._conn.cursor(pymysql.cursors.DictCursor)
        returning_id = sql.rstrip().rstrip(";").upper().endswith("RETURNING ID")
        if returning_id:
            sql = sql.rstrip().rstrip(";")[: -len("RETURNING id")]
        sql = _convert_placeholders(sql) if params else sql
        if params:
            cur.execute(sql, params)
        else:
            cur.execute(sql)
        return _ReturningIdCursor(cur) if returning_id else cur

    def commit(self):
        self._conn.commit()

    def close(self):
        self._conn.close()


def get_conn():
    if not DATABASE_URL:
        raise RuntimeError("DATABASE_URL is not set - copy .env.example to .env.")
    url = urlparse(DATABASE_URL)
    return Conn(pymysql.connect(
        host=url.hostname or "localhost",
        port=url.port or 3306,
        user=url.username or "",
        password=url.password or "",
        database=(url.path or "/").lstrip("/"),
        charset="utf8mb4",
        autocommit=False,
    ))


@contextmanager
def db():
    conn = get_conn()
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


ERR_DUP_COLUMN = 1060  # MySQL: "Duplicate column name" - the column already exists


def _run_script(conn, script: str):
    """Execute a `;`-separated batch of DDL statements one at a time - MySQL
    (via PyMySQL, without the MULTI_STATEMENTS client flag) doesn't run a
    whole multi-statement script in one call the way psycopg2 did."""
    for statement in script.split(";"):
        statement = statement.strip()
        if statement:
            conn.execute(statement)


def _run_migrations(conn, script: str):
    """Like _run_script, but tolerates "column already exists" - unlike
    Postgres, MySQL has no `ADD COLUMN IF NOT EXISTS` at all (that's a
    MariaDB-only extension), so idempotency here is "try it, ignore a
    duplicate-column error" instead of a flag in the DDL itself."""
    for statement in script.split(";"):
        statement = statement.strip()
        if not statement:
            continue
        try:
            conn.execute(statement)
        except pymysql.err.OperationalError as e:
            if e.args and e.args[0] == ERR_DUP_COLUMN:
                continue
            raise


# Columns added after the first release - no migration tool until a change
# needs backfilling or a rollback. Indexes are the one other thing this
# can't cover the same way; see SCHEMA_INDEXES.
MIGRATIONS = """
ALTER TABLE users ADD COLUMN cefr_level TEXT;
ALTER TABLE users ADD COLUMN target_date TEXT;
ALTER TABLE users ADD COLUMN onboarded BOOLEAN DEFAULT FALSE;
-- How long the learner spent on a daily task, for the "today's practice time
-- by skill" dashboard chart.
ALTER TABLE daily_attempts ADD COLUMN duration_sec INTEGER;

-- FSRS scheduler state. srs_state/next_review_at/last_reviewed_at/interval_days
-- stay as the display/back-compat fields (existing UI reads them unchanged);
-- these are the engine fields the fsrs library actually operates on.
ALTER TABLE vocabulary ADD COLUMN fsrs_state SMALLINT NOT NULL DEFAULT 1;
ALTER TABLE vocabulary ADD COLUMN fsrs_step SMALLINT;
ALTER TABLE vocabulary ADD COLUMN stability REAL;
ALTER TABLE vocabulary ADD COLUMN difficulty REAL;

-- Full before/after snapshot per review, for scheduler debugging, plus a
-- client-supplied request id (see SCHEMA_INDEXES) so a double-submitted
-- rating (double-click, retry) is a no-op instead of a second review.
ALTER TABLE reviews ADD COLUMN request_id VARCHAR(64);
ALTER TABLE reviews ADD COLUMN state_before TEXT;
ALTER TABLE reviews ADD COLUMN state_after TEXT;
ALTER TABLE reviews ADD COLUMN stability_before REAL;
ALTER TABLE reviews ADD COLUMN stability_after REAL;
ALTER TABLE reviews ADD COLUMN difficulty_before REAL;
ALTER TABLE reviews ADD COLUMN difficulty_after REAL;
ALTER TABLE reviews ADD COLUMN scheduled_days REAL;
ALTER TABLE reviews ADD COLUMN elapsed_days REAL;

-- Per-user scheduler settings: day-boundary timezone and daily caps.
-- timezone is VARCHAR, not TEXT, purely so it's allowed to carry a literal
-- DEFAULT - MySQL refuses a literal default on any TEXT/BLOB column.
ALTER TABLE users ADD COLUMN timezone VARCHAR(64) NOT NULL DEFAULT 'Asia/Ho_Chi_Minh';
ALTER TABLE users ADD COLUMN new_cards_per_day INTEGER NOT NULL DEFAULT 20;
ALTER TABLE users ADD COLUMN max_reviews_per_day INTEGER NOT NULL DEFAULT 200;

-- Game layer on top of the scheduler: running totals only. Level is derived
-- from xp (main.level_info), achievements from these + vocabulary counts.
ALTER TABLE users ADD COLUMN xp INTEGER NOT NULL DEFAULT 0;
ALTER TABLE users ADD COLUMN coins INTEGER NOT NULL DEFAULT 0;
ALTER TABLE users ADD COLUMN best_combo INTEGER NOT NULL DEFAULT 0;
ALTER TABLE users ADD COLUMN boss_wins INTEGER NOT NULL DEFAULT 0;
ALTER TABLE users ADD COLUMN sessions_completed INTEGER NOT NULL DEFAULT 0;
ALTER TABLE vocabulary ADD COLUMN word_family_json TEXT;
"""


def seed_default_user():
    """Insert a default login so the app is usable out of the box - there is no
    /api/auth/register route, so without this a fresh database has no way to log in."""
    import auth
    from datetime import datetime, timezone

    email = os.environ.get("DEFAULT_USER_EMAIL", "demo@example.com").strip().lower()
    password = os.environ.get("DEFAULT_USER_PASSWORD", "changeme123")
    name = os.environ.get("DEFAULT_USER_NAME", "Demo User")
    with db() as conn:
        conn.execute(
            """INSERT IGNORE INTO users (email, password_hash, name, native_language, created_at)
               VALUES (?,?,?,?,?)""",
            (email, auth.hash_password(password), name, "Vietnamese", datetime.now(timezone.utc).isoformat()),
        )


def init_db():
    with db() as conn:
        _run_script(conn, SCHEMA_TABLES)
        # Migrations first: some indexed columns (e.g. reviews.request_id)
        # only exist after a migration adds them.
        _run_migrations(conn, MIGRATIONS)
        for name, stmt in SCHEMA_INDEXES:
            try:
                conn.execute(stmt)
            except pymysql.err.OperationalError as e:
                if e.args and e.args[0] == ERR_DUP_KEYNAME:
                    continue
                raise
    seed_default_user()


def _demo():
    # Placeholders become PyMySQL's, but only outside string literals.
    assert _convert_placeholders("SELECT * FROM t WHERE id=?") == "SELECT * FROM t WHERE id=%s"
    assert _convert_placeholders("INSERT INTO q (a,b) VALUES (?,?)") == "INSERT INTO q (a,b) VALUES (%s,%s)"
    # The trap this exists for: a question mark inside quoted text is data.
    assert _convert_placeholders("INSERT INTO q (t, id) VALUES ('Do you agree?', ?)") == \
        "INSERT INTO q (t, id) VALUES ('Do you agree?', %s)"
    assert _convert_placeholders("""SELECT ? WHERE name='what?' AND x="huh?" """) == \
        """SELECT %s WHERE name='what?' AND x="huh?" """
    # A literal % (e.g. a LIKE pattern) must not be read as a format spec.
    assert _convert_placeholders("SELECT * FROM t WHERE email LIKE 'x-%' AND id=?") == \
        "SELECT * FROM t WHERE email LIKE 'x-%%' AND id=%s"
    assert _convert_placeholders("SELECT 1") == "SELECT 1"
    print("db self-check OK")


if __name__ == "__main__":
    _demo()

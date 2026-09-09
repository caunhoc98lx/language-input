"""Postgres access via psycopg2. Thin sqlite3-style wrapper (conn.execute with
'?' placeholders, dict-like rows) so callers didn't need to change."""
import os
from contextlib import contextmanager

import psycopg2
import psycopg2.extras

DATABASE_URL = os.environ.get("DATABASE_URL", "")

SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    id SERIAL PRIMARY KEY,
    email TEXT UNIQUE NOT NULL,
    password_hash TEXT NOT NULL,
    name TEXT DEFAULT '',
    native_language TEXT DEFAULT 'Vietnamese',
    ielts_target REAL,
    ielts_current REAL,
    daily_goal_minutes INTEGER DEFAULT 30,
    streak INTEGER DEFAULT 0,
    last_active_date TEXT,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS vocabulary (
    id SERIAL PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES users(id),
    word TEXT NOT NULL,
    normalized_word TEXT NOT NULL,
    translation TEXT DEFAULT '',
    definition TEXT DEFAULT '',
    part_of_speech TEXT DEFAULT '',
    pronunciation TEXT DEFAULT '',
    phonetic TEXT DEFAULT '',
    examples_json TEXT DEFAULT '[]',
    synonyms_json TEXT DEFAULT '[]',
    antonyms_json TEXT DEFAULT '[]',
    collocations_json TEXT DEFAULT '[]',
    ielts_level TEXT DEFAULT '',
    topic TEXT DEFAULT '',
    memory_tip TEXT DEFAULT '',
    notes TEXT DEFAULT '',
    srs_state TEXT DEFAULT 'NEW',
    ease REAL DEFAULT 2.5,
    interval_days REAL DEFAULT 0,
    repetitions INTEGER DEFAULT 0,
    lapses INTEGER DEFAULT 0,
    next_review_at TEXT DEFAULT CURRENT_TIMESTAMP,
    last_reviewed_at TEXT,
    starred INTEGER DEFAULT 0,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(user_id, normalized_word)
);
CREATE INDEX IF NOT EXISTS idx_vocab_user_next ON vocabulary(user_id, next_review_at);
CREATE INDEX IF NOT EXISTS idx_vocab_user_norm ON vocabulary(user_id, normalized_word);

CREATE TABLE IF NOT EXISTS vocabulary_sets (
    id SERIAL PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES users(id),
    title TEXT NOT NULL,
    description TEXT DEFAULT '',
    created_at TEXT DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS set_words (
    set_id INTEGER NOT NULL REFERENCES vocabulary_sets(id),
    vocabulary_id INTEGER NOT NULL REFERENCES vocabulary(id),
    PRIMARY KEY (set_id, vocabulary_id)
);

CREATE TABLE IF NOT EXISTS reviews (
    id SERIAL PRIMARY KEY,
    vocabulary_id INTEGER NOT NULL REFERENCES vocabulary(id),
    user_id INTEGER NOT NULL REFERENCES users(id),
    rating TEXT NOT NULL,
    interval_before REAL,
    interval_after REAL,
    reviewed_at TEXT DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_reviews_user_time ON reviews(user_id, reviewed_at);

CREATE TABLE IF NOT EXISTS daily_tasks (
    id SERIAL PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES users(id),
    task_date TEXT NOT NULL,
    kind TEXT NOT NULL,
    content_json TEXT NOT NULL,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(user_id, task_date, kind)
);
CREATE INDEX IF NOT EXISTS idx_daily_tasks_user_date ON daily_tasks(user_id, task_date);

CREATE TABLE IF NOT EXISTS daily_attempts (
    id SERIAL PRIMARY KEY,
    task_id INTEGER NOT NULL REFERENCES daily_tasks(id),
    user_id INTEGER NOT NULL REFERENCES users(id),
    answers_json TEXT DEFAULT '[]',
    score INTEGER,
    total INTEGER,
    band REAL,
    feedback_json TEXT DEFAULT '{}',
    submitted_at TEXT DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_daily_attempts_task ON daily_attempts(task_id);
CREATE INDEX IF NOT EXISTS idx_daily_attempts_user_time ON daily_attempts(user_id, submitted_at);
"""


def to_pg(sql: str) -> str:
    """Turn '?' placeholders into psycopg2's '%s', leaving string literals alone.

    A plain .replace() also rewrites the '?' inside 'Do you agree?', which
    psycopg2 then treats as a missing parameter - a confusing IndexError far from
    the actual mistake. This walks the statement instead, which is cheap and
    removes the trap entirely.
    """
    out = []
    quote = None
    for ch in sql:
        if ch == "%":
            out.append("%%")  # a literal % must survive psycopg2's own formatting,
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


class Conn:
    def __init__(self, pg_conn):
        self._conn = pg_conn

    def execute(self, sql, params=None):
        cur = self._conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        sql = to_pg(sql) if params else sql
        if params:
            cur.execute(sql, params)
        else:
            cur.execute(sql)  # no-params path: lets init_db() run a multi-statement script
        return cur

    def commit(self):
        self._conn.commit()

    def close(self):
        self._conn.close()


def get_conn():
    if not DATABASE_URL:
        raise RuntimeError("DATABASE_URL is not set - copy .env.example to .env.")
    return Conn(psycopg2.connect(DATABASE_URL))


@contextmanager
def db():
    conn = get_conn()
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


# Columns added after the first release. ponytail: ADD COLUMN IF NOT EXISTS is
# idempotent, so this is the whole migration story - no migration tool until a
# change needs backfilling or a rollback.
MIGRATIONS = """
ALTER TABLE users ADD COLUMN IF NOT EXISTS cefr_level TEXT DEFAULT '';
ALTER TABLE users ADD COLUMN IF NOT EXISTS target_date TEXT;
ALTER TABLE users ADD COLUMN IF NOT EXISTS onboarded BOOLEAN DEFAULT FALSE;
-- How long the learner spent on a daily task, for the "today's practice time
-- by skill" dashboard chart.
ALTER TABLE daily_attempts ADD COLUMN IF NOT EXISTS duration_sec INTEGER;

-- FSRS scheduler state. srs_state/next_review_at/last_reviewed_at/interval_days
-- stay as the display/back-compat fields (existing UI reads them unchanged);
-- these are the engine fields the fsrs library actually operates on.
ALTER TABLE vocabulary ADD COLUMN IF NOT EXISTS fsrs_state SMALLINT NOT NULL DEFAULT 1;
ALTER TABLE vocabulary ADD COLUMN IF NOT EXISTS fsrs_step SMALLINT;
ALTER TABLE vocabulary ADD COLUMN IF NOT EXISTS stability REAL;
ALTER TABLE vocabulary ADD COLUMN IF NOT EXISTS difficulty REAL;

-- Full before/after snapshot per review, for scheduler debugging, plus a
-- client-supplied request id so a double-submitted rating (double-click,
-- retry) is a no-op instead of a second review.
ALTER TABLE reviews ADD COLUMN IF NOT EXISTS request_id TEXT;
ALTER TABLE reviews ADD COLUMN IF NOT EXISTS state_before TEXT;
ALTER TABLE reviews ADD COLUMN IF NOT EXISTS state_after TEXT;
ALTER TABLE reviews ADD COLUMN IF NOT EXISTS stability_before REAL;
ALTER TABLE reviews ADD COLUMN IF NOT EXISTS stability_after REAL;
ALTER TABLE reviews ADD COLUMN IF NOT EXISTS difficulty_before REAL;
ALTER TABLE reviews ADD COLUMN IF NOT EXISTS difficulty_after REAL;
ALTER TABLE reviews ADD COLUMN IF NOT EXISTS scheduled_days REAL;
ALTER TABLE reviews ADD COLUMN IF NOT EXISTS elapsed_days REAL;
CREATE UNIQUE INDEX IF NOT EXISTS idx_reviews_request_id ON reviews(request_id) WHERE request_id IS NOT NULL;

-- Per-user scheduler settings: day-boundary timezone and daily caps.
ALTER TABLE users ADD COLUMN IF NOT EXISTS timezone TEXT NOT NULL DEFAULT 'Asia/Ho_Chi_Minh';
ALTER TABLE users ADD COLUMN IF NOT EXISTS new_cards_per_day INTEGER NOT NULL DEFAULT 20;
ALTER TABLE users ADD COLUMN IF NOT EXISTS max_reviews_per_day INTEGER NOT NULL DEFAULT 200;
"""


def seed_default_user():
    """Insert a default login so the app is usable out of the box - there is no
    /api/auth/register route, so without this a fresh database has no way to log in."""
    import auth

    email = os.environ.get("DEFAULT_USER_EMAIL", "demo@example.com").strip().lower()
    password = os.environ.get("DEFAULT_USER_PASSWORD", "changeme123")
    name = os.environ.get("DEFAULT_USER_NAME", "Demo User")
    with db() as conn:
        conn.execute(
            "INSERT INTO users (email, password_hash, name) VALUES (?,?,?) ON CONFLICT (email) DO NOTHING",
            (email, auth.hash_password(password), name),
        )


def init_db():
    with db() as conn:
        conn.execute(SCHEMA)
        conn.execute(MIGRATIONS)
    seed_default_user()


def _demo():
    # Placeholders become psycopg2's, but only outside string literals.
    assert to_pg("SELECT * FROM t WHERE id=?") == "SELECT * FROM t WHERE id=%s"
    assert to_pg("INSERT INTO q (a,b) VALUES (?,?)") == "INSERT INTO q (a,b) VALUES (%s,%s)"
    # The trap this exists for: a question mark inside quoted text is data.
    assert to_pg("INSERT INTO q (t, id) VALUES ('Do you agree?', ?)") == \
        "INSERT INTO q (t, id) VALUES ('Do you agree?', %s)"
    assert to_pg("""SELECT ? WHERE name='what?' AND x="huh?" """) == \
        """SELECT %s WHERE name='what?' AND x="huh?" """
    # A literal % (e.g. a LIKE pattern) must not be read as a format spec.
    assert to_pg("SELECT * FROM t WHERE email LIKE 'x-%' AND id=?") == \
        "SELECT * FROM t WHERE email LIKE 'x-%%' AND id=%s"
    assert to_pg("SELECT 1") == "SELECT 1"
    print("db self-check OK")


if __name__ == "__main__":
    _demo()

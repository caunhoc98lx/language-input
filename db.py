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

# Imported IELTS materials. Hierarchy:
#   material -> test -> section -> question_group -> question
#
# ponytail: one `ielts_sections` table covers all four skills - a Listening
# Section, a Reading Passage, a Writing Task and a Speaking Part are the same
# shape (title, instructions, a body of text, optional audio, some questions).
# Separate tables per skill would be four near-identical schemas and four code
# paths in the practice engine. Split them only if a skill grows fields the
# others can never use.
#
# Also deliberately absent: an answer-options table (options are a JSON array on
# the group/question, never queried across rows), a separate answers table
# (one answer per question, so it lives on the question), and a
# user_skill_progress table (derivable by aggregating practice_answers; add a
# materialised one when that aggregate is measurably slow).
SCHEMA_IELTS = """
CREATE TABLE IF NOT EXISTS ielts_materials (
    id SERIAL PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES users(id),
    title TEXT NOT NULL,
    source TEXT DEFAULT '',
    description TEXT DEFAULT '',
    doc_type TEXT DEFAULT 'CUSTOM_PDF',   -- CAMBRIDGE_IELTS | IELTS_MOCK_TEST | IELTS_BOOK | IELTS_WORKBOOK | CUSTOM_PDF | USER_CREATED
    status TEXT DEFAULT 'IMPORTING',      -- IMPORTING | NEEDS_REVIEW | READY | FAILED
    origin TEXT DEFAULT 'IMPORTED',       -- IMPORTED | USER_CREATED | AI_GENERATED
    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_materials_user ON ielts_materials(user_id, created_at);

CREATE TABLE IF NOT EXISTS ielts_tests (
    id SERIAL PRIMARY KEY,
    material_id INTEGER NOT NULL REFERENCES ielts_materials(id) ON DELETE CASCADE,
    test_number INTEGER NOT NULL,
    title TEXT DEFAULT '',
    description TEXT DEFAULT '',
    order_index INTEGER DEFAULT 0,
    UNIQUE(material_id, test_number)
);

CREATE TABLE IF NOT EXISTS import_jobs (
    id SERIAL PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES users(id),
    material_id INTEGER REFERENCES ielts_materials(id) ON DELETE CASCADE,
    status TEXT DEFAULT 'UPLOADED',       -- UPLOADED|QUEUED|PROCESSING|OCR|PARSING|STRUCTURING|MATCHING_AUDIO|READY|FAILED|CANCELLED
    current_step TEXT DEFAULT '',
    steps_json TEXT DEFAULT '[]',         -- [{step, status, detail, at}] for the progress UI
    total_pages INTEGER DEFAULT 0,
    processed_pages INTEGER DEFAULT 0,
    warnings_json TEXT DEFAULT '[]',
    error TEXT DEFAULT '',
    cancel_requested BOOLEAN DEFAULT FALSE,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
    started_at TEXT,
    completed_at TEXT
);
CREATE INDEX IF NOT EXISTS idx_jobs_user ON import_jobs(user_id, created_at);

CREATE TABLE IF NOT EXISTS import_files (
    id SERIAL PRIMARY KEY,
    job_id INTEGER REFERENCES import_jobs(id) ON DELETE SET NULL,
    user_id INTEGER NOT NULL REFERENCES users(id),
    material_id INTEGER REFERENCES ielts_materials(id) ON DELETE CASCADE,
    kind TEXT NOT NULL,                   -- PDF | AUDIO
    filename TEXT NOT NULL,               -- original name, shown to the user only
    storage_key TEXT NOT NULL,            -- opaque key in private storage
    mime_type TEXT DEFAULT '',
    size_bytes BIGINT DEFAULT 0,
    sha256 TEXT NOT NULL,
    page_count INTEGER,
    duration_sec REAL,
    meta_json TEXT DEFAULT '{}',
    created_at TEXT DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_files_user_hash ON import_files(user_id, sha256);
CREATE INDEX IF NOT EXISTS idx_files_material ON import_files(material_id);

CREATE TABLE IF NOT EXISTS document_pages (
    id SERIAL PRIMARY KEY,
    file_id INTEGER NOT NULL REFERENCES import_files(id) ON DELETE CASCADE,
    page_number INTEGER NOT NULL,
    text TEXT DEFAULT '',
    method TEXT DEFAULT 'NONE',           -- TEXT | OCR | NONE
    confidence REAL,
    char_count INTEGER DEFAULT 0,
    needs_review BOOLEAN DEFAULT FALSE,
    error TEXT DEFAULT '',
    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(file_id, page_number)          -- makes the pipeline resumable: skip pages already stored
);
CREATE INDEX IF NOT EXISTS idx_pages_file ON document_pages(file_id, page_number);
CREATE TABLE IF NOT EXISTS ielts_sections (
    id SERIAL PRIMARY KEY,
    test_id INTEGER NOT NULL REFERENCES ielts_tests(id) ON DELETE CASCADE,
    skill TEXT NOT NULL,                  -- LISTENING | READING | WRITING | SPEAKING
    section_number INTEGER NOT NULL,      -- Section 1-4 / Passage 1-3 / Task 1-2 / Part 1-3
    title TEXT DEFAULT '',
    instructions TEXT DEFAULT '',
    body TEXT DEFAULT '',                 -- reading passage, writing prompt, speaking cue card
    transcript TEXT DEFAULT '',           -- listening transcript, when the document has one
    audio_file_id INTEGER REFERENCES import_files(id) ON DELETE SET NULL,
    audio_start_sec REAL,                 -- segment inside a longer audio file
    audio_end_sec REAL,
    audio_confidence REAL,                -- how sure the matcher was (phase 3)
    first_question INTEGER,
    last_question INTEGER,
    source_pages TEXT DEFAULT '',         -- e.g. "23-26", for provenance
    confidence REAL,
    status TEXT DEFAULT 'READY',          -- READY | NEEDS_REVIEW
    order_index INTEGER DEFAULT 0,
    UNIQUE(test_id, skill, section_number)
);
CREATE INDEX IF NOT EXISTS idx_sections_test ON ielts_sections(test_id, skill, section_number);

CREATE TABLE IF NOT EXISTS ielts_question_groups (
    id SERIAL PRIMARY KEY,
    section_id INTEGER NOT NULL REFERENCES ielts_sections(id) ON DELETE CASCADE,
    question_type TEXT NOT NULL,
    instruction TEXT DEFAULT '',
    body TEXT DEFAULT '',                 -- summary/note/table skeleton the blanks sit in
    options_json TEXT DEFAULT '[]',       -- shared option bank (matching headings/features)
    word_limit TEXT DEFAULT '',           -- e.g. "NO MORE THAN TWO WORDS"
    first_question INTEGER,
    last_question INTEGER,
    order_index INTEGER DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_groups_section ON ielts_question_groups(section_id, order_index);

CREATE TABLE IF NOT EXISTS ielts_questions (
    id SERIAL PRIMARY KEY,
    section_id INTEGER NOT NULL REFERENCES ielts_sections(id) ON DELETE CASCADE,
    group_id INTEGER REFERENCES ielts_question_groups(id) ON DELETE SET NULL,
    question_number INTEGER NOT NULL,
    question_type TEXT NOT NULL,          -- MULTIPLE_CHOICE | TRUE_FALSE_NOT_GIVEN | ... | SPEAKING
    question_text TEXT DEFAULT '',
    instruction TEXT DEFAULT '',
    options_json TEXT DEFAULT '[]',       -- per-question options; empty means "use the group's"
    answer TEXT DEFAULT '',
    acceptable_answers_json TEXT DEFAULT '[]',  -- explicit variants only; never auto-generated
    word_limit TEXT DEFAULT '',
    explanation TEXT DEFAULT '',
    points REAL DEFAULT 1,
    difficulty TEXT DEFAULT '',
    answer_source TEXT DEFAULT 'DOCUMENT',      -- DOCUMENT | USER | AI
    origin TEXT DEFAULT 'IMPORTED',             -- IMPORTED | USER_CREATED | AI_GENERATED
    source_page INTEGER,
    bbox_json TEXT DEFAULT '',
    ocr_confidence REAL,
    parser_confidence REAL,
    status TEXT DEFAULT 'READY',                -- READY | NEEDS_REVIEW
    order_index INTEGER DEFAULT 0,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(section_id, question_number)
);
CREATE INDEX IF NOT EXISTS idx_questions_section ON ielts_questions(section_id, question_number);

CREATE TABLE IF NOT EXISTS practice_sessions (
    id SERIAL PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES users(id),
    material_id INTEGER REFERENCES ielts_materials(id) ON DELETE CASCADE,
    test_id INTEGER REFERENCES ielts_tests(id) ON DELETE CASCADE,
    section_id INTEGER REFERENCES ielts_sections(id) ON DELETE CASCADE,  -- null = whole skill
    skill TEXT NOT NULL,
    mode TEXT DEFAULT 'EXAM',             -- EXAM | LEARNING
    status TEXT DEFAULT 'IN_PROGRESS',    -- IN_PROGRESS | SUBMITTED | ABANDONED
    score INTEGER,
    total INTEGER,
    band REAL,
    duration_sec INTEGER,
    started_at TEXT DEFAULT CURRENT_TIMESTAMP,
    completed_at TEXT
);
CREATE INDEX IF NOT EXISTS idx_sessions_user ON practice_sessions(user_id, started_at);

CREATE TABLE IF NOT EXISTS practice_answers (
    id SERIAL PRIMARY KEY,
    session_id INTEGER NOT NULL REFERENCES practice_sessions(id) ON DELETE CASCADE,
    question_id INTEGER NOT NULL REFERENCES ielts_questions(id) ON DELETE CASCADE,
    user_answer TEXT DEFAULT '',
    correct_answer TEXT DEFAULT '',
    is_correct BOOLEAN,
    time_spent_sec INTEGER,
    answered_at TEXT DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(session_id, question_id)       -- autosave upserts into this row
);
CREATE INDEX IF NOT EXISTS idx_answers_session ON practice_answers(session_id);
CREATE INDEX IF NOT EXISTS idx_answers_question ON practice_answers(question_id);

-- Writing and speaking answers. ponytail: one table, not WritingSubmission +
-- SpeakingSubmission - they differ only in whether the answer arrived as typed
-- text or as a recording that was then transcribed. Same criteria, same feedback
-- shape, same history screen.
CREATE TABLE IF NOT EXISTS productive_submissions (
    id SERIAL PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES users(id),
    kind TEXT NOT NULL,                   -- WRITING | SPEAKING
    section_id INTEGER REFERENCES ielts_sections(id) ON DELETE SET NULL,
    task_label TEXT DEFAULT '',           -- "Task 2", "Part 3", ...
    prompt TEXT NOT NULL,
    response TEXT DEFAULT '',             -- the essay, or the transcript of the recording
    audio_key TEXT DEFAULT '',            -- speaking only: private storage key
    band REAL,
    criteria_json TEXT DEFAULT '{}',      -- per-criterion bands
    feedback_json TEXT DEFAULT '{}',
    word_count INTEGER DEFAULT 0,
    duration_sec INTEGER,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_submissions_user ON productive_submissions(user_id, kind, created_at);

-- Grammar errors the examiner found, kept as rows so "my weak grammar topics" is
-- a GROUP BY rather than a JSON scan of every past submission.
CREATE TABLE IF NOT EXISTS grammar_mistakes (
    id SERIAL PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES users(id),
    submission_id INTEGER REFERENCES productive_submissions(id) ON DELETE CASCADE,
    original TEXT NOT NULL,
    correction TEXT DEFAULT '',
    error_type TEXT DEFAULT '',
    topic TEXT DEFAULT '',
    explanation TEXT DEFAULT '',
    created_at TEXT DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_mistakes_user ON grammar_mistakes(user_id, topic);
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
-- Targeted practice ("10 more Matching Headings", "redo my mistakes") builds a
-- session from a hand-picked set of questions rather than a whole section.
ALTER TABLE practice_sessions ADD COLUMN IF NOT EXISTS question_ids_json TEXT DEFAULT '';
ALTER TABLE practice_sessions ADD COLUMN IF NOT EXISTS label TEXT DEFAULT '';
"""


def init_db():
    with db() as conn:
        conn.execute(SCHEMA)
        conn.execute(SCHEMA_IELTS)
        conn.execute(MIGRATIONS)


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

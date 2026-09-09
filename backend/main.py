import json
import os
import random
import re
import secrets
from datetime import datetime, date, timedelta, timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from dotenv import load_dotenv

load_dotenv()

from fastapi import FastAPI, Request, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from starlette.middleware.sessions import SessionMiddleware
import psycopg2.errors

import auth
import ai
import coach
import ielts
import srs
from db import db, init_db

app = FastAPI(title="Language Input API")
app.add_middleware(SessionMiddleware, secret_key=os.environ.get("SESSION_SECRET", secrets.token_hex(32)))
app.add_middleware(
    CORSMiddleware,
    allow_origins=[os.environ.get("FRONTEND_ORIGIN", "http://localhost:3000")],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

init_db()

REVIEW_QUEUE_SIZE = 20


# ---------- helpers ----------

def current_user(request: Request):
    uid = request.session.get("user_id")
    if not uid:
        return None
    with db() as conn:
        row = conn.execute("SELECT * FROM users WHERE id=?", (uid,)).fetchone()
    return row


def require_user(request: Request):
    user = current_user(request)
    if not user:
        raise HTTPException(status_code=401, detail="Not authenticated")
    return user


def row_to_user(row) -> dict:
    d = dict(row)
    d.pop("password_hash", None)
    return d


def touch_streak(user_id: int):
    """Bump streak once per calendar day the user studies. ponytail: simple
    date-diff, no timezone-per-user handling."""
    today = date.today().isoformat()
    with db() as conn:
        row = conn.execute("SELECT streak, last_active_date FROM users WHERE id=?", (user_id,)).fetchone()
        if row["last_active_date"] == today:
            return
        yesterday = (date.today().toordinal() - 1)
        was_yesterday = row["last_active_date"] == date.fromordinal(yesterday).isoformat()
        new_streak = (row["streak"] or 0) + 1 if was_yesterday or not row["last_active_date"] else 1
        conn.execute("UPDATE users SET streak=?, last_active_date=? WHERE id=?", (new_streak, today, user_id))


def row_to_vocab(row) -> dict:
    d = dict(row)
    for field in ("examples", "synonyms", "antonyms", "collocations"):
        d[field] = json.loads(d.pop(f"{field}_json") or "[]")
    return d


def _daily_budget(conn, user) -> tuple[int, int]:
    """Remaining new-card and review budget for "today" in the learner's own
    timezone (resets at their midnight, not UTC's) - section 10/11 of the
    spec: configurable daily caps, timezone-correct day boundary."""
    start, end = srs.day_bounds_utc(user["timezone"] or "UTC")
    counts = conn.execute(
        """SELECT COUNT(*) FILTER (WHERE state_before='NEW') new_done, COUNT(*) total_done
           FROM reviews WHERE user_id=? AND reviewed_at>=? AND reviewed_at<?""",
        (user["id"], start, end),
    ).fetchone()
    new_left = max(0, (user["new_cards_per_day"] or 0) - (counts["new_done"] or 0))
    reviews_left = max(0, (user["max_reviews_per_day"] or 0) - (counts["total_done"] or 0))
    return new_left, reviews_left


def _scope_clause(set_id: str) -> tuple[str, list]:
    """WHERE-fragment restricting to a specific set, the unsorted ("none")
    bucket, or (set_id="") no restriction at all."""
    if set_id == "none":
        return "AND id NOT IN (SELECT vocabulary_id FROM set_words)", []
    if set_id:
        return "AND id IN (SELECT vocabulary_id FROM set_words WHERE set_id=?)", [set_id]
    return "", []


def fetch_study_rows(conn, user, set_id: str, limit: int):
    """Priority queue: due Relearning/Learning cards, then due Review cards,
    then New cards - capped by the user's daily new-card and review limits.
    `user` is a full user row (fetch_study_rows needs timezone + limits, not
    just an id)."""
    now = datetime.now(timezone.utc).isoformat()
    new_left, reviews_left = _daily_budget(conn, user)
    scope_sql, scope_params = _scope_clause(set_id)

    due = []
    if reviews_left > 0:
        due = conn.execute(
            f"""SELECT * FROM vocabulary WHERE user_id=? {scope_sql}
                AND srs_state != 'NEW' AND next_review_at<=?
                ORDER BY (fsrs_state=3) DESC, (fsrs_state=1) DESC, next_review_at
                LIMIT ?""",
            (user["id"], *scope_params, now, min(limit, reviews_left)),
        ).fetchall()

    remaining = max(0, limit - len(due))
    new_rows = []
    if new_left > 0 and remaining > 0:
        new_rows = conn.execute(
            f"""SELECT * FROM vocabulary WHERE user_id=? {scope_sql}
                AND srs_state='NEW' ORDER BY created_at LIMIT ?""",
            (user["id"], *scope_params, min(remaining, new_left)),
        ).fetchall()

    return list(due) + list(new_rows)


def build_learn_queue(conn, user, set_id: str, limit: int) -> list[dict]:
    """Fetch a study queue and assign each card an active-recall question type,
    harder types for words the learner already knows well. ponytail: type is
    chosen once per queue build, not re-adapted mid-session on a per-answer basis."""
    cards = [row_to_vocab(r) for r in fetch_study_rows(conn, user, set_id, limit)]
    if not cards:
        return []

    all_translations = [r["translation"] for r in conn.execute(
        "SELECT translation FROM vocabulary WHERE user_id=? AND translation!=''", (user["id"],)
    ).fetchall()]
    all_definitions = [r["definition"] for r in conn.execute(
        "SELECT definition FROM vocabulary WHERE user_id=? AND definition!=''", (user["id"],)
    ).fetchall()]

    for card in cards:
        if card["srs_state"] in ("NEW", "LEARNING"):
            pool = ["multiple_choice", "true_false"]
        elif card["srs_state"] == "MASTERED":
            pool = ["type_answer"]
        else:
            pool = ["fill_blank", "type_answer"]
        qtype = random.choice(pool)

        if qtype == "multiple_choice":
            distractors = [t for t in all_translations if t != card["translation"]]
            if len(distractors) < 3:
                qtype = "type_answer"
            else:
                options = random.sample(distractors, 3) + [card["translation"]]
                random.shuffle(options)
                card["options"] = options

        if qtype == "true_false":
            other_defs = [d for d in all_definitions if d != card["definition"]]
            if not card["definition"] or not other_defs:
                qtype = "type_answer"
            else:
                is_true = random.random() < 0.5
                card["tf_statement"] = card["definition"] if is_true else random.choice(other_defs)
                card["tf_answer"] = is_true

        if qtype == "fill_blank":
            sentence = next((e for e in card["examples"] if card["word"].lower() in e.lower()), None)
            if not sentence:
                qtype = "type_answer"
            else:
                pattern = re.compile(re.escape(card["word"]), re.IGNORECASE)
                card["blank_sentence"] = pattern.sub("_____", sentence, count=1)

        card["question_type"] = qtype

    return cards


# ---------- auth ----------

class LoginBody(BaseModel):
    email: str
    password: str


@app.post("/api/auth/login")
def login(request: Request, body: LoginBody):
    email = body.email.strip().lower()
    with db() as conn:
        user = conn.execute("SELECT * FROM users WHERE email=?", (email,)).fetchone()
    if not user or not auth.verify_password(body.password, user["password_hash"]):
        raise HTTPException(401, "Invalid email or password.")
    request.session["user_id"] = user["id"]
    return row_to_user(user)


@app.post("/api/auth/logout")
def logout(request: Request):
    request.session.clear()
    return {"ok": True}


@app.get("/api/auth/me")
def me(request: Request):
    user = require_user(request)
    return row_to_user(user)


# ---------- dashboard ----------

@app.get("/api/dashboard")
def dashboard(request: Request):
    user = require_user(request)
    now = datetime.utcnow().isoformat()
    with db() as conn:
        due = conn.execute(
            "SELECT COUNT(*) c FROM vocabulary WHERE user_id=? AND srs_state!='NEW' AND next_review_at<=?",
            (user["id"], now),
        ).fetchone()["c"]
        new_count = conn.execute(
            "SELECT COUNT(*) c FROM vocabulary WHERE user_id=? AND srs_state='NEW'", (user["id"],)
        ).fetchone()["c"]
        mastered = conn.execute(
            "SELECT COUNT(*) c FROM vocabulary WHERE user_id=? AND srs_state='MASTERED'", (user["id"],)
        ).fetchone()["c"]
        learning = conn.execute(
            "SELECT COUNT(*) c FROM vocabulary WHERE user_id=? AND srs_state IN ('LEARNING','REVIEW','RELEARNING')",
            (user["id"],),
        ).fetchone()["c"]
        total = conn.execute("SELECT COUNT(*) c FROM vocabulary WHERE user_id=?", (user["id"],)).fetchone()["c"]
        sets = conn.execute(
            """SELECT s.id, s.title,
                      COUNT(sw.vocabulary_id) total_words,
                      SUM(CASE WHEN v.srs_state='MASTERED' THEN 1 ELSE 0 END) mastered_words
               FROM vocabulary_sets s
               LEFT JOIN set_words sw ON sw.set_id = s.id
               LEFT JOIN vocabulary v ON v.id = sw.vocabulary_id
               WHERE s.user_id=?
               GROUP BY s.id ORDER BY s.created_at DESC LIMIT 5""",
            (user["id"],),
        ).fetchall()
        coaching = build_coaching(conn, user)
    sets_progress = []
    for s in sets:
        pct = round(100 * (s["mastered_words"] or 0) / s["total_words"]) if s["total_words"] else 0
        sets_progress.append({"id": s["id"], "title": s["title"], "total_words": s["total_words"], "pct": pct})
    return {
        "user": row_to_user(user),
        "due": due,
        "new_count": new_count,
        "mastered": mastered,
        "learning": learning,
        "total": total,
        "sets_progress": sets_progress,
        **coaching,
    }


def build_coaching(conn, user) -> dict:
    """Band estimates, weak question types, this week's activity and today's plan.

    Evidence comes from graded practice: today's and past `daily_attempts` -
    the AI-generated reading/listening/writing tasks. That is the only source
    of practice data now that imported-material practice has been removed.
    """
    uid = user["id"]
    today = date.today().isoformat()
    week_start, week_end = coach.week_window()

    attempts = conn.execute(
        """SELECT t.kind AS skill, a.band, a.score, a.total, a.submitted_at,
                  t.content_json, a.feedback_json, a.duration_sec
           FROM daily_attempts a JOIN daily_tasks t ON t.id = a.task_id
           WHERE a.user_id=? ORDER BY a.submitted_at DESC LIMIT 40""",
        (uid,),
    ).fetchall()

    graded = [{"skill": (r["skill"] or "").lower(), "band": r["band"]} for r in attempts]
    bands = coach.skill_bands(graded)

    # Per-question-type accuracy: pair each stored question with its marked result.
    per_question = []
    for row in attempts:
        try:
            questions = json.loads(row["content_json"]).get("questions", [])
            results = json.loads(row["feedback_json"] or "{}").get("results", [])
        except (TypeError, ValueError):
            continue
        for res in results:
            i = res.get("index")
            if isinstance(i, int) and i < len(questions):
                per_question.append({"type": questions[i].get("type", "unknown"),
                                     "correct": bool(res.get("correct"))})
    accuracy = coach.question_type_accuracy(per_question)
    weak = coach.weak_areas(accuracy)

    done_today = {(r["skill"] or "").lower() for r in attempts if (r["submitted_at"] or "")[:10] == today}
    if conn.execute(
        "SELECT 1 FROM reviews WHERE user_id=? AND reviewed_at>=? LIMIT 1", (uid, today)
    ).fetchone():
        done_today.add("vocabulary")

    # Today's practice time per skill, for the dashboard chart.
    skill_seconds: dict[str, int] = {}
    for r in attempts:
        if (r["submitted_at"] or "")[:10] == today and r["duration_sec"]:
            skill = (r["skill"] or "").lower()
            skill_seconds[skill] = skill_seconds.get(skill, 0) + r["duration_sec"]
    today_by_skill = [
        {"skill": s, "minutes": round(skill_seconds.get(s, 0) / 60, 1)}
        for s in ("listening", "reading", "writing", "speaking")
    ]

    week_reviews = conn.execute(
        "SELECT COUNT(*) c FROM reviews WHERE user_id=? AND reviewed_at>=? AND reviewed_at<?",
        (uid, week_start, week_end),
    ).fetchone()["c"]
    week_practice_sec = conn.execute(
        """SELECT COALESCE(SUM(duration_sec),0) s FROM daily_attempts a JOIN daily_tasks t ON t.id = a.task_id
           WHERE a.user_id=? AND a.submitted_at>=? AND a.submitted_at<?""",
        (uid, week_start, week_end),
    ).fetchone()["s"]
    answered = sum((r["total"] or 0) for r in attempts)
    correct = sum((r["score"] or 0) for r in attempts)

    due_cards = conn.execute(
        "SELECT COUNT(*) c FROM vocabulary WHERE user_id=? AND srs_state!='NEW' AND next_review_at<=?",
        (uid, datetime.utcnow().isoformat()),
    ).fetchone()["c"]
    new_cards = conn.execute(
        "SELECT COUNT(*) c FROM vocabulary WHERE user_id=? AND srs_state='NEW'", (uid,)
    ).fetchone()["c"]

    return {
        "bands": {
            "skills": bands,
            "overall": coach.overall_band(bands, fallback=user["ielts_current"]),
            "estimated_from": "practice" if bands else "self-reported",
            "target": user["ielts_target"],
            "target_date": user["target_date"],
        },
        "plan": coach.todays_plan(
            due_cards=due_cards, new_cards=new_cards, weak=weak, done_today=done_today,
            minutes=user["daily_goal_minutes"] or 30,
        ),
        "weak_areas": weak,
        "question_type_accuracy": accuracy,
        "activity": {
            "reviews_this_week": week_reviews,
            "practice_minutes_this_week": round((week_practice_sec or 0) / 60),
            "questions_answered": answered,
            "accuracy": round(correct / answered, 3) if answered else None,
            "today_by_skill": today_by_skill,
        },
    }


class TargetBody(BaseModel):
    name: str = ""
    cefr_level: str = ""
    ielts_current: float | None = None
    ielts_target: float | None = None
    target_date: str = ""
    daily_goal_minutes: int | None = None
    timezone: str = ""
    new_cards_per_day: int | None = None
    max_reviews_per_day: int | None = None


CEFR_LEVELS = ("A1", "A2", "B1", "B2", "C1", "C2")


@app.patch("/api/profile")
def profile_update(request: Request, body: TargetBody):
    """Onboarding + settings: IELTS target, current level, daily study time,
    and the scheduler's daily new-card/review caps (section 10 of the spec)."""
    user = require_user(request)
    for band in (body.ielts_current, body.ielts_target):
        if band is not None and not (0 <= band <= 9):
            raise HTTPException(400, "IELTS scores must be between 0 and 9.")
    if body.cefr_level and body.cefr_level not in CEFR_LEVELS:
        raise HTTPException(400, "Unknown CEFR level.")
    if body.target_date:
        try:
            date.fromisoformat(body.target_date)
        except ValueError:
            raise HTTPException(400, "Target date must be YYYY-MM-DD.")
    if body.timezone:
        try:
            ZoneInfo(body.timezone)
        except ZoneInfoNotFoundError:
            raise HTTPException(400, f"Unknown timezone: {body.timezone}")
    for field, value in (("new_cards_per_day", body.new_cards_per_day), ("max_reviews_per_day", body.max_reviews_per_day)):
        if value is not None and value < 0:
            raise HTTPException(400, f"{field} cannot be negative.")
    with db() as conn:
        conn.execute(
            """UPDATE users SET
                 name = COALESCE(NULLIF(?, ''), name),
                 cefr_level = COALESCE(NULLIF(?, ''), cefr_level),
                 ielts_current = COALESCE(?, ielts_current),
                 ielts_target = COALESCE(?, ielts_target),
                 target_date = COALESCE(NULLIF(?, ''), target_date),
                 daily_goal_minutes = COALESCE(?, daily_goal_minutes),
                 timezone = COALESCE(NULLIF(?, ''), timezone),
                 new_cards_per_day = COALESCE(?, new_cards_per_day),
                 max_reviews_per_day = COALESCE(?, max_reviews_per_day),
                 onboarded = TRUE
               WHERE id=?""",
            (body.name, body.cefr_level, body.ielts_current, body.ielts_target,
             body.target_date, body.daily_goal_minutes, body.timezone,
             body.new_cards_per_day, body.max_reviews_per_day, user["id"]),
        )
        row = conn.execute("SELECT * FROM users WHERE id=?", (user["id"],)).fetchone()
    return row_to_user(row)


# ---------- vocabulary ----------

@app.get("/api/vocabulary")
def vocabulary_list(request: Request, state: str = "", q: str = "", set_id: str = ""):
    user = require_user(request)
    sql = "SELECT * FROM vocabulary WHERE user_id=?"
    params = [user["id"]]
    if state == "due":
        sql += " AND srs_state!='NEW' AND next_review_at<=?"
        params.append(datetime.utcnow().isoformat())
    elif state:
        sql += " AND srs_state=?"
        params.append(state)
    if q:
        sql += " AND (word LIKE ? OR translation LIKE ?)"
        params += [f"%{q}%", f"%{q}%"]
    if set_id == "none":
        sql += " AND id NOT IN (SELECT vocabulary_id FROM set_words)"
    elif set_id:
        sql += " AND id IN (SELECT vocabulary_id FROM set_words WHERE set_id=?)"
        params.append(set_id)
    sql += " ORDER BY created_at DESC LIMIT 200"
    with db() as conn:
        rows = conn.execute(sql, params).fetchall()
    return {"items": [row_to_vocab(r) for r in rows]}


class ExtractBody(BaseModel):
    text: str


@app.post("/api/vocabulary/extract")
def vocabulary_extract(request: Request, body: ExtractBody):
    require_user(request)
    try:
        items = ai.extract_vocabulary(body.text)
    except ai.AIError as e:
        raise HTTPException(502, str(e))
    return {"items": [i.model_dump() for i in items]}


class SaveBody(BaseModel):
    items: list[dict]
    set_id: int | None = None
    group_by_topic: bool = False


def _set_id_for_topic(conn, user_id: int, topic: str, cache: dict[str, int]) -> int:
    """Find-or-create a vocabulary set named after `topic` (case-insensitive),
    so repeated saves land in the same set instead of spawning duplicates."""
    key = topic.lower()
    if key in cache:
        return cache[key]
    row = conn.execute(
        "SELECT id FROM vocabulary_sets WHERE user_id=? AND LOWER(title)=?", (user_id, key)
    ).fetchone()
    if row:
        set_id = row["id"]
    else:
        set_id = conn.execute(
            "INSERT INTO vocabulary_sets (user_id, title) VALUES (?,?) RETURNING id", (user_id, topic)
        ).fetchone()["id"]
    cache[key] = set_id
    return set_id


@app.post("/api/vocabulary/save")
def vocabulary_save(request: Request, body: SaveBody):
    user = require_user(request)
    saved_ids = []
    topic_by_id: dict[int, str] = {}
    with db() as conn:
        for item in body.items:
            normalized = item["word"].strip().lower()
            existing = conn.execute(
                "SELECT id FROM vocabulary WHERE user_id=? AND normalized_word=?", (user["id"], normalized)
            ).fetchone()
            if existing:
                vid = existing["id"]
            else:
                vid = conn.execute(
                    """INSERT INTO vocabulary
                       (user_id, word, normalized_word, translation, definition, part_of_speech,
                        pronunciation, phonetic, examples_json, synonyms_json, antonyms_json,
                        collocations_json, ielts_level, topic, memory_tip)
                       VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?) RETURNING id""",
                    (
                        user["id"], item["word"], normalized, item.get("translation", ""), item.get("definition", ""),
                        item.get("part_of_speech", ""), item.get("pronunciation", ""), item.get("phonetic", ""),
                        json.dumps(item.get("examples", [])), json.dumps(item.get("synonyms", [])),
                        json.dumps(item.get("antonyms", [])), json.dumps(item.get("collocations", [])),
                        item.get("ielts_level", ""), item.get("topic", ""), item.get("memory_tip", ""),
                    ),
                ).fetchone()["id"]
            saved_ids.append(vid)
            topic_by_id[vid] = (item.get("topic") or "").strip()

        if body.set_id:
            for vid in saved_ids:
                conn.execute(
                    "INSERT INTO set_words (set_id, vocabulary_id) VALUES (?, ?) ON CONFLICT DO NOTHING",
                    (body.set_id, vid),
                )
        elif body.group_by_topic:
            set_cache: dict[str, int] = {}
            for vid in saved_ids:
                topic = topic_by_id[vid]
                if not topic:
                    continue
                set_id = _set_id_for_topic(conn, user["id"], topic, set_cache)
                conn.execute(
                    "INSERT INTO set_words (set_id, vocabulary_id) VALUES (?, ?) ON CONFLICT DO NOTHING",
                    (set_id, vid),
                )
    return {"ok": True, "saved_ids": saved_ids}


@app.get("/api/vocabulary/{vocab_id}")
def vocabulary_detail(request: Request, vocab_id: int):
    user = require_user(request)
    with db() as conn:
        row = conn.execute("SELECT * FROM vocabulary WHERE id=? AND user_id=?", (vocab_id, user["id"])).fetchone()
        if not row:
            raise HTTPException(404)
        history = conn.execute(
            "SELECT * FROM reviews WHERE vocabulary_id=? ORDER BY reviewed_at DESC LIMIT 20", (vocab_id,)
        ).fetchall()
    return {"item": row_to_vocab(row), "history": [dict(h) for h in history]}


class EditVocabBody(BaseModel):
    translation: str = ""
    definition: str = ""
    notes: str = ""
    memory_tip: str = ""


@app.patch("/api/vocabulary/{vocab_id}")
def vocabulary_edit(request: Request, vocab_id: int, body: EditVocabBody):
    user = require_user(request)
    with db() as conn:
        conn.execute(
            """UPDATE vocabulary SET translation=?, definition=?, notes=?, memory_tip=?, updated_at=CURRENT_TIMESTAMP
               WHERE id=? AND user_id=?""",
            (body.translation, body.definition, body.notes, body.memory_tip, vocab_id, user["id"]),
        )
        row = conn.execute("SELECT * FROM vocabulary WHERE id=? AND user_id=?", (vocab_id, user["id"])).fetchone()
        if not row:
            raise HTTPException(404)
    return {"item": row_to_vocab(row)}


@app.post("/api/vocabulary/{vocab_id}/star")
def vocabulary_star(request: Request, vocab_id: int):
    user = require_user(request)
    with db() as conn:
        conn.execute(
            "UPDATE vocabulary SET starred = 1 - starred WHERE id=? AND user_id=?", (vocab_id, user["id"])
        )
        row = conn.execute("SELECT * FROM vocabulary WHERE id=? AND user_id=?", (vocab_id, user["id"])).fetchone()
        if not row:
            raise HTTPException(404)
    return {"item": row_to_vocab(row)}


@app.delete("/api/vocabulary/{vocab_id}")
def vocabulary_delete(request: Request, vocab_id: int):
    user = require_user(request)
    with db() as conn:
        conn.execute("DELETE FROM set_words WHERE vocabulary_id=?", (vocab_id,))
        conn.execute("DELETE FROM reviews WHERE vocabulary_id=?", (vocab_id,))
        conn.execute("DELETE FROM vocabulary WHERE id=? AND user_id=?", (vocab_id, user["id"]))
    return {"ok": True}


# ---------- sets ----------

@app.get("/api/sets")
def sets_list(request: Request):
    user = require_user(request)
    with db() as conn:
        rows = conn.execute(
            """SELECT s.*, COUNT(sw.vocabulary_id) word_count,
                      COALESCE(SUM(CASE WHEN v.srs_state='MASTERED' THEN 1 ELSE 0 END), 0) mastered_count
               FROM vocabulary_sets s
               LEFT JOIN set_words sw ON sw.set_id = s.id
               LEFT JOIN vocabulary v ON v.id = sw.vocabulary_id
               WHERE s.user_id=? GROUP BY s.id ORDER BY s.created_at DESC""",
            (user["id"],),
        ).fetchall()
        unsorted = conn.execute(
            """SELECT COUNT(*) c, COALESCE(SUM(CASE WHEN srs_state='MASTERED' THEN 1 ELSE 0 END), 0) mastered
               FROM vocabulary
               WHERE user_id=? AND id NOT IN (SELECT vocabulary_id FROM set_words)""",
            (user["id"],),
        ).fetchone()
    return {
        "sets": [dict(r) for r in rows],
        "unsorted_count": unsorted["c"],
        "unsorted_mastered": unsorted["mastered"],
    }


class NewSetBody(BaseModel):
    title: str
    description: str = ""


@app.post("/api/sets")
def sets_new(request: Request, body: NewSetBody):
    user = require_user(request)
    with db() as conn:
        cur = conn.execute(
            "INSERT INTO vocabulary_sets (user_id, title, description) VALUES (?, ?, ?) RETURNING id",
            (user["id"], body.title.strip(), body.description.strip()),
        )
        set_id = cur.fetchone()["id"]
        row = conn.execute("SELECT * FROM vocabulary_sets WHERE id=?", (set_id,)).fetchone()
    return {"set": dict(row)}


@app.get("/api/sets/{set_id}")
def set_detail(request: Request, set_id: int):
    user = require_user(request)
    with db() as conn:
        s = conn.execute("SELECT * FROM vocabulary_sets WHERE id=? AND user_id=?", (set_id, user["id"])).fetchone()
        if not s:
            raise HTTPException(404)
        words = conn.execute(
            """SELECT v.* FROM vocabulary v JOIN set_words sw ON sw.vocabulary_id = v.id
               WHERE sw.set_id=? ORDER BY v.created_at DESC""",
            (set_id,),
        ).fetchall()
        other_words = conn.execute(
            """SELECT v.id, v.word FROM vocabulary v
               WHERE v.user_id=? AND v.id NOT IN (SELECT vocabulary_id FROM set_words WHERE set_id=?)
               ORDER BY v.word LIMIT 200""",
            (user["id"], set_id),
        ).fetchall()
    return {
        "set": dict(s),
        "words": [row_to_vocab(r) for r in words],
        "other_words": [dict(r) for r in other_words],
    }


class AddWordsBody(BaseModel):
    word_ids: list[int]


@app.post("/api/sets/{set_id}/words")
def set_add_words(request: Request, set_id: int, body: AddWordsBody):
    user = require_user(request)
    with db() as conn:
        owned = conn.execute("SELECT id FROM vocabulary_sets WHERE id=? AND user_id=?", (set_id, user["id"])).fetchone()
        if not owned:
            raise HTTPException(404)
        for wid in body.word_ids:
            conn.execute(
                "INSERT INTO set_words (set_id, vocabulary_id) VALUES (?, ?) ON CONFLICT DO NOTHING", (set_id, wid)
            )
    return {"ok": True}


@app.delete("/api/sets/{set_id}/words/{vocab_id}")
def set_remove_word(request: Request, set_id: int, vocab_id: int):
    user = require_user(request)
    with db() as conn:
        owned = conn.execute("SELECT id FROM vocabulary_sets WHERE id=? AND user_id=?", (set_id, user["id"])).fetchone()
        if not owned:
            raise HTTPException(404)
        conn.execute("DELETE FROM set_words WHERE set_id=? AND vocabulary_id=?", (set_id, vocab_id))
    return {"ok": True}


@app.delete("/api/sets/{set_id}")
def set_delete(request: Request, set_id: int):
    user = require_user(request)
    with db() as conn:
        conn.execute("DELETE FROM set_words WHERE set_id=?", (set_id,))
        conn.execute("DELETE FROM vocabulary_sets WHERE id=? AND user_id=?", (set_id, user["id"]))
    return {"ok": True}


# ---------- study / flashcards / review ----------

@app.get("/api/study/due")
def study_due(request: Request):
    """Due/new/learning breakdown for the reminder banner and daily-queue
    summary. `due` is kept as the overall count for back-compat with the
    banner; the breakdown is additive."""
    user = require_user(request)
    now = datetime.now(timezone.utc).isoformat()
    with db() as conn:
        row = conn.execute(
            """SELECT
                 COUNT(*) FILTER (WHERE srs_state NOT IN ('NEW') AND next_review_at<=?
                                   AND fsrs_state IN (1,3)) learning,
                 COUNT(*) FILTER (WHERE srs_state NOT IN ('NEW') AND next_review_at<=?
                                   AND fsrs_state=2) review,
                 COUNT(*) FILTER (WHERE srs_state='NEW') new
               FROM vocabulary WHERE user_id=?""",
            (now, now, user["id"]),
        ).fetchone()
        new_left, reviews_left = _daily_budget(conn, user)
    return {
        "due": row["learning"] + row["review"],
        "learning": row["learning"],
        "review": row["review"],
        "new_available": row["new"],
        "new_today": min(row["new"], new_left),
        "reviews_remaining_today": reviews_left,
    }


@app.get("/api/study/flashcards")
def study_flashcards(request: Request, set_id: str = ""):
    user = require_user(request)
    with db() as conn:
        rows = fetch_study_rows(conn, user, set_id, REVIEW_QUEUE_SIZE)
    return {"queue": [row_to_vocab(r) for r in rows]}


@app.get("/api/study/learn")
def study_learn(request: Request, set_id: str = ""):
    user = require_user(request)
    with db() as conn:
        queue = build_learn_queue(conn, user, set_id, REVIEW_QUEUE_SIZE)
    return {"queue": queue}


def _apply_review(conn, user, vocabulary_id: int, rating: str, request_id: str | None):
    """Core of POST /api/review: run the FSRS scheduler, persist the new card
    state and a full review-log row in one transaction. Raises psycopg2's
    UniqueViolation if `request_id` was already used (caller decides how to
    respond - see api_review)."""
    row = conn.execute("SELECT * FROM vocabulary WHERE id=? AND user_id=?", (vocabulary_id, user["id"])).fetchone()
    if not row:
        raise HTTPException(404)
    result = srs.review(row, rating)
    f, log = result["fields"], result["log"]
    conn.execute(
        """UPDATE vocabulary SET fsrs_state=?, fsrs_step=?, stability=?, difficulty=?,
           repetitions=?, lapses=?, srs_state=?, interval_days=?,
           next_review_at=?, last_reviewed_at=CURRENT_TIMESTAMP, updated_at=CURRENT_TIMESTAMP
           WHERE id=?""",
        (f["fsrs_state"], f["fsrs_step"], f["stability"], f["difficulty"],
         f["repetitions"], f["lapses"], f["srs_state"], f["interval_days"],
         f["next_review_at"], vocabulary_id),
    )
    conn.execute(
        """INSERT INTO reviews
           (vocabulary_id, user_id, rating, interval_before, interval_after, request_id,
            state_before, state_after, stability_before, stability_after,
            difficulty_before, difficulty_after, scheduled_days, elapsed_days)
           VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        (vocabulary_id, user["id"], rating, row["interval_days"], f["interval_days"], request_id,
         log["state_before"], log["state_after"], log["stability_before"], log["stability_after"],
         log["difficulty_before"], log["difficulty_after"], log["scheduled_days"], log["elapsed_days"]),
    )
    return f


class ReviewBody(BaseModel):
    vocabulary_id: int
    rating: str
    request_id: str | None = None


@app.post("/api/review")
def api_review(request: Request, body: ReviewBody):
    """Rate one card. Idempotent when `request_id` is supplied: a resubmit of
    the same id (double-click, retried request) is a no-op that returns the
    review that already landed, instead of scheduling the card twice."""
    user = require_user(request)
    if body.rating not in srs.RATINGS:
        raise HTTPException(400, f"Unknown rating: {body.rating}")
    try:
        with db() as conn:
            f = _apply_review(conn, user, body.vocabulary_id, body.rating, body.request_id)
    except psycopg2.errors.UniqueViolation:
        with db() as conn:
            existing = conn.execute(
                "SELECT * FROM reviews WHERE request_id=? AND user_id=?", (body.request_id, user["id"])
            ).fetchone()
        if not existing:
            raise HTTPException(409, "Duplicate review conflict.")
        return {
            "ok": True, "state": existing["state_after"], "next_review_at": None,
            "interval_days": existing["scheduled_days"], "duplicate": True,
        }
    touch_streak(user["id"])
    return {"ok": True, "state": f["srs_state"], "next_review_at": f["next_review_at"], "interval_days": f["interval_days"]}


@app.get("/api/review/preview/{vocabulary_id}")
def review_preview(request: Request, vocabulary_id: int):
    """What each of the 4 ratings would do to this card, without applying
    any of them - the intervals shown on the rating buttons."""
    user = require_user(request)
    with db() as conn:
        row = conn.execute(
            "SELECT * FROM vocabulary WHERE id=? AND user_id=?", (vocabulary_id, user["id"])
        ).fetchone()
        if not row:
            raise HTTPException(404)
    return srs.preview(row)


@app.get("/api/review/stats")
def review_stats(request: Request, days: int = 30):
    """Retention and rating-mix stats for the progress screen: section 13 of
    the spec. Retention = (Hard+Good+Easy) / all reviews in the window."""
    user = require_user(request)
    days = min(max(days, 1), 365)
    since = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
    today_start, today_end = srs.day_bounds_utc(user["timezone"] or "UTC")
    with db() as conn:
        counts = conn.execute(
            """SELECT rating, COUNT(*) c FROM reviews
               WHERE user_id=? AND reviewed_at>=? GROUP BY rating""",
            (user["id"], since),
        ).fetchall()
        reviewed_today = conn.execute(
            "SELECT COUNT(*) c FROM reviews WHERE user_id=? AND reviewed_at>=? AND reviewed_at<?",
            (user["id"], today_start, today_end),
        ).fetchone()["c"]
        totals = conn.execute(
            """SELECT COUNT(*) total,
                      COUNT(*) FILTER (WHERE srs_state='NEW') new,
                      COUNT(*) FILTER (WHERE srs_state NOT IN ('NEW')) learned,
                      COUNT(*) FILTER (WHERE srs_state != 'NEW' AND next_review_at<=?) due_now
               FROM vocabulary WHERE user_id=?""",
            (datetime.now(timezone.utc).isoformat(), user["id"]),
        ).fetchone()
    by_rating = {r["rating"]: r["c"] for r in counts}
    total_reviews = sum(by_rating.values())
    successful = sum(by_rating.get(r, 0) for r in ("hard", "good", "easy"))
    return {
        "days": days,
        "total_reviews": total_reviews,
        "reviewed_today": reviewed_today,
        "retention": round(successful / total_reviews, 3) if total_reviews else None,
        "rating_rates": {
            r: round(by_rating.get(r, 0) / total_reviews, 3) if total_reviews else 0
            for r in srs.RATINGS
        },
        "total_cards": totals["total"],
        "new_cards": totals["new"],
        "cards_learned": totals["learned"],
        "due_now": totals["due_now"],
        "streak": user["streak"],
    }


# ---------- AI tutor ----------

class TutorBody(BaseModel):
    history: list[dict]


def coach_context_text(conn, user) -> str:
    """A compact, factual summary of the learner for the AI coach.

    ponytail: plain text, not a JSON dump - it is read by a model, and the
    numbers are the point. Kept short so it costs little per message.
    """
    coaching = build_coaching(conn, user)
    bands = coaching["bands"]
    lines = [
        f"Target band: {bands['target'] or 'not set'}"
        + (f", test date {bands['target_date']}" if bands["target_date"] else ""),
        "Estimated bands: " + (
            ", ".join(f"{s} {b}" for s, b in bands["skills"].items()) or "none yet")
        + f" (overall {bands['overall'] or 'unknown'}, from {bands['estimated_from']})",
    ]
    if coaching["weak_areas"]:
        lines.append("Weakest question types: " + ", ".join(
            f"{w['label']} {round(w['accuracy'] * 100)}% over {w['attempts']}q"
            for w in coaching["weak_areas"]))
    activity = coaching["activity"]
    lines.append(
        f"Activity: {activity['questions_answered']} questions answered, "
        f"accuracy {round((activity['accuracy'] or 0) * 100)}%, "
        f"{activity['reviews_this_week']} vocabulary reviews this week, "
        f"{user['streak']}-day streak, daily goal {user['daily_goal_minutes']} minutes.")

    plan = ", ".join(f"{t['title']} ({t['minutes']}m)" for t in coaching["plan"])
    lines.append(f"Today's suggested plan: {plan}")
    return "\n".join(lines)


@app.post("/api/tutor")
def api_tutor(request: Request, body: TutorBody):
    user = require_user(request)
    with db() as conn:
        weak = conn.execute(
            """SELECT word FROM vocabulary WHERE user_id=? AND lapses>0
               ORDER BY lapses DESC, ease ASC LIMIT 5""",
            (user["id"],),
        ).fetchall()
        context = coach_context_text(conn, user)
    weak_words = [r["word"] for r in weak]
    try:
        reply = ai.tutor_reply(body.history, weak_words, context)
    except ai.AIError as e:
        raise HTTPException(502, str(e))
    return {"reply": reply}


# ---------- daily IELTS practice ----------

KINDS = ("reading", "listening", "writing")
GENERATORS = {
    "reading": ai.generate_reading,
    "listening": ai.generate_listening,
    "writing": ai.generate_writing,
}


def strip_answers(content: dict) -> dict:
    """Hide answers, explanations and the vocabulary list until the learner submits.

    The vocabulary entries quote definitions straight out of the text, so leaving
    them in would give away several answers.

    ponytail: the listening transcript stays in the payload - the browser needs it
    to speak the audio. The UI hides it until submission; someone reading devtools
    is only cheating themselves. Move to server-side TTS if that ever matters.
    """
    safe = {k: v for k, v in content.items() if k != "vocabulary"}
    safe["questions"] = [
        {k: v for k, v in q.items() if k not in ("answer", "explanation", "vocab_words")}
        for q in content.get("questions", [])
    ]
    return safe


def load_task(conn, user_id: int, kind: str, task_date: str):
    return conn.execute(
        "SELECT * FROM daily_tasks WHERE user_id=? AND task_date=? AND kind=?",
        (user_id, task_date, kind),
    ).fetchone()


def load_attempt(conn, task_id: int):
    return conn.execute(
        "SELECT * FROM daily_attempts WHERE task_id=? ORDER BY submitted_at DESC LIMIT 1",
        (task_id,),
    ).fetchone()


def attempt_to_dict(row) -> dict:
    return {
        "id": row["id"],
        "answers": json.loads(row["answers_json"] or "[]"),
        "score": row["score"],
        "total": row["total"],
        "band": row["band"],
        "feedback": json.loads(row["feedback_json"] or "{}"),
        "submitted_at": row["submitted_at"],
    }


@app.get("/api/daily")
def daily_overview(request: Request):
    user = require_user(request)
    today = date.today().isoformat()
    out = {}
    with db() as conn:
        for kind in KINDS:
            task = load_task(conn, user["id"], kind, today)
            if not task:
                out[kind] = {"generated": False, "attempted": False}
                continue
            content = json.loads(task["content_json"])
            attempt = load_attempt(conn, task["id"])
            out[kind] = {
                "generated": True,
                "attempted": attempt is not None,
                "title": content.get("title", ""),
                "topic": content.get("topic", ""),
                "score": attempt["score"] if attempt else None,
                "total": attempt["total"] if attempt else None,
                "band": attempt["band"] if attempt else None,
            }
        history = conn.execute(
            """SELECT t.kind, t.task_date, t.content_json, a.score, a.total, a.band
               FROM daily_attempts a JOIN daily_tasks t ON t.id = a.task_id
               WHERE a.user_id=? ORDER BY a.submitted_at DESC LIMIT 10""",
            (user["id"],),
        ).fetchall()
    return {
        "date": today,
        "tasks": out,
        "history": [
            {
                "kind": h["kind"],
                "task_date": h["task_date"],
                "title": json.loads(h["content_json"]).get("title", ""),
                "score": h["score"],
                "total": h["total"],
                "band": h["band"],
            }
            for h in history
        ],
    }


@app.get("/api/daily/{kind}")
def daily_get(request: Request, kind: str):
    user = require_user(request)
    if kind not in KINDS:
        raise HTTPException(404)
    today = date.today().isoformat()
    with db() as conn:
        task = load_task(conn, user["id"], kind, today)
        if not task:
            return {"task": None, "attempt": None}
        content = json.loads(task["content_json"])
        attempt = load_attempt(conn, task["id"])
    # Answers stay server-side until the learner submits.
    payload = content if attempt else strip_answers(content)
    return {
        "task": {"id": task["id"], "kind": kind, "date": today, "content": payload},
        "attempt": attempt_to_dict(attempt) if attempt else None,
    }


@app.post("/api/daily/{kind}/generate")
def daily_generate(request: Request, kind: str):
    user = require_user(request)
    if kind not in KINDS:
        raise HTTPException(404)
    today = date.today().isoformat()
    with db() as conn:
        existing = load_task(conn, user["id"], kind, today)
        if existing:  # one generation per day per kind keeps AI cost predictable
            content = json.loads(existing["content_json"])
            attempt = load_attempt(conn, existing["id"])
            return {
                "task": {"id": existing["id"], "kind": kind, "date": today,
                         "content": content if attempt else strip_answers(content)},
                "attempt": attempt_to_dict(attempt) if attempt else None,
            }
    try:
        generated = GENERATORS[kind]().model_dump()
    except ai.AIError as e:
        raise HTTPException(502, str(e))
    with db() as conn:
        cur = conn.execute(
            """INSERT INTO daily_tasks (user_id, task_date, kind, content_json)
               VALUES (?,?,?,?)
               ON CONFLICT (user_id, task_date, kind) DO UPDATE SET kind = EXCLUDED.kind
               RETURNING id""",
            (user["id"], today, kind, json.dumps(generated)),
        )
        task_id = cur.fetchone()["id"]
    return {"task": {"id": task_id, "kind": kind, "date": today, "content": strip_answers(generated)},
            "attempt": None}


class DailyAnswersBody(BaseModel):
    answers: list[str] = []
    essay: str = ""
    duration_sec: int | None = None


@app.post("/api/daily/{kind}/submit")
def daily_submit(request: Request, kind: str, body: DailyAnswersBody):
    user = require_user(request)
    if kind not in KINDS:
        raise HTTPException(404)
    today = date.today().isoformat()
    with db() as conn:
        task = load_task(conn, user["id"], kind, today)
        if not task:
            raise HTTPException(404, "No task generated for today yet.")
        content = json.loads(task["content_json"])

    if kind == "writing":
        essay = body.essay.strip()
        if len(essay.split()) < 20:
            raise HTTPException(400, "Please write a longer answer before submitting.")
        try:
            feedback = ai.grade_writing(content["prompt"], essay).model_dump()
        except ai.AIError as e:
            raise HTTPException(502, str(e))
        answers, score, total, band = [essay], None, None, feedback["band_overall"]
    else:
        marked = ielts.grade(content["questions"], body.answers)
        feedback = {"results": marked["results"]}
        answers, score, total, band = body.answers, marked["score"], marked["total"], marked["band"]

    with db() as conn:
        cur = conn.execute(
            """INSERT INTO daily_attempts (task_id, user_id, answers_json, score, total, band, feedback_json, duration_sec)
               VALUES (?,?,?,?,?,?,?,?) RETURNING id""",
            (task["id"], user["id"], json.dumps(answers), score, total, band, json.dumps(feedback),
             body.duration_sec),
        )
        attempt_id = cur.fetchone()["id"]
    touch_streak(user["id"])
    return {
        "attempt": {"id": attempt_id, "answers": answers, "score": score, "total": total,
                    "band": band, "feedback": feedback},
        "content": content,  # now safe to reveal answers + explanations + vocabulary
    }


# ---------- progress & analytics ----------

@app.get("/api/progress")
def progress(request: Request, days: int = 90):
    """Everything the progress page charts: band history, accuracy over time,
    question-type performance, vocabulary retention and study activity."""
    user = require_user(request)
    days = min(max(days, 7), 365)
    since = (date.today() - timedelta(days=days)).isoformat()

    with db() as conn:
        coaching = build_coaching(conn, user)

        # Band history from graded daily practice, oldest first.
        history = conn.execute(
            """SELECT t.kind AS skill, a.band, a.score, a.total, a.submitted_at AS at
               FROM daily_attempts a JOIN daily_tasks t ON t.id = a.task_id
               WHERE a.user_id=? AND a.band IS NOT NULL AND a.submitted_at>=?
               ORDER BY at""",
            (user["id"], since),
        ).fetchall()

        vocab = conn.execute(
            """SELECT COUNT(*) total,
                      COUNT(*) FILTER (WHERE srs_state='MASTERED') mastered,
                      COUNT(*) FILTER (WHERE srs_state IN ('LEARNING','REVIEW','RELEARNING')) learning,
                      COUNT(*) FILTER (WHERE srs_state='NEW') new_words,
                      COUNT(*) FILTER (WHERE lapses > 0) lapsed,
                      COALESCE(AVG(interval_days) FILTER (WHERE repetitions > 0), 0) avg_interval
               FROM vocabulary WHERE user_id=?""",
            (user["id"],),
        ).fetchone()
        reviews = conn.execute(
            """SELECT COUNT(*) total, COUNT(*) FILTER (WHERE rating='again') lapses
               FROM reviews WHERE user_id=? AND reviewed_at>=?""",
            (user["id"], since),
        ).fetchone()

        # Study activity per day, for the streak/consistency chart.
        activity = conn.execute(
            """SELECT day, SUM(items) items FROM (
                 SELECT LEFT(reviewed_at, 10) AS day, COUNT(*) items FROM reviews
                  WHERE user_id=? AND reviewed_at>=? GROUP BY LEFT(reviewed_at, 10)
                 UNION ALL
                 SELECT LEFT(submitted_at, 10) AS day, COALESCE(SUM(total), 1) items
                  FROM daily_attempts WHERE user_id=? AND submitted_at>=?
                  GROUP BY LEFT(submitted_at, 10)
               ) d GROUP BY day ORDER BY day""",
            (user["id"], since, user["id"], since),
        ).fetchall()

        daily_tasks_done = conn.execute(
            "SELECT COUNT(*) c FROM daily_attempts WHERE user_id=?",
            (user["id"],)).fetchone()["c"]

    retention = None
    if reviews["total"]:
        retention = round(1 - (reviews["lapses"] / reviews["total"]), 3)

    return {
        "bands": coaching["bands"],
        "question_type_accuracy": coaching["question_type_accuracy"],
        "weak_areas": coaching["weak_areas"],
        "history": [{"skill": (h["skill"] or "").lower(), "band": h["band"], "score": h["score"],
                     "total": h["total"], "at": h["at"]} for h in history],
        "vocabulary": {**dict(vocab), "avg_interval": round(vocab["avg_interval"] or 0, 1),
                       "retention": retention, "reviews_in_window": reviews["total"]},
        "activity": [{"day": a["day"], "items": a["items"]} for a in activity],
        "daily_tasks_completed": daily_tasks_done,
        "streak": user["streak"],
        "days": days,
    }

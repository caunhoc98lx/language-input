import json
import os
import random
import re
import secrets
from datetime import datetime, date, timedelta

from dotenv import load_dotenv

load_dotenv()

from fastapi import FastAPI, Request, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from starlette.middleware.sessions import SessionMiddleware

import auth
import ai
import audio_match
import dictation
import coach
import ielts
import ielts_parser
import imports
import storage
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


def fetch_study_rows(conn, user_id: int, set_id: str, limit: int):
    """Due-first queue: overdue/new cards for the user, or a specific set."""
    now = datetime.utcnow().isoformat()
    if set_id:
        return conn.execute(
            """SELECT v.* FROM vocabulary v JOIN set_words sw ON sw.vocabulary_id=v.id
               WHERE sw.set_id=? AND v.user_id=?
               ORDER BY (v.srs_state='NEW'), v.next_review_at LIMIT ?""",
            (set_id, user_id, limit),
        ).fetchall()
    return conn.execute(
        """SELECT * FROM vocabulary WHERE user_id=?
           AND (srs_state='NEW' OR next_review_at<=?)
           ORDER BY (srs_state='NEW'), next_review_at LIMIT ?""",
        (user_id, now, limit),
    ).fetchall()


def build_learn_queue(conn, user_id: int, set_id: str, limit: int) -> list[dict]:
    """Fetch a study queue and assign each card an active-recall question type,
    harder types for words the learner already knows well. ponytail: type is
    chosen once per queue build, not re-adapted mid-session on a per-answer basis."""
    cards = [row_to_vocab(r) for r in fetch_study_rows(conn, user_id, set_id, limit)]
    if not cards:
        return []

    all_translations = [r["translation"] for r in conn.execute(
        "SELECT translation FROM vocabulary WHERE user_id=? AND translation!=''", (user_id,)
    ).fetchall()]
    all_definitions = [r["definition"] for r in conn.execute(
        "SELECT definition FROM vocabulary WHERE user_id=? AND definition!=''", (user_id,)
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

class SignupBody(BaseModel):
    email: str
    password: str
    name: str = ""


class LoginBody(BaseModel):
    email: str
    password: str


@app.post("/api/auth/signup")
def signup(request: Request, body: SignupBody):
    email = body.email.strip().lower()
    if len(body.password) < 8:
        raise HTTPException(400, "Password must be at least 8 characters.")
    with db() as conn:
        existing = conn.execute("SELECT id FROM users WHERE email=?", (email,)).fetchone()
        if existing:
            raise HTTPException(400, "An account with that email already exists.")
        cur = conn.execute(
            "INSERT INTO users (email, password_hash, name) VALUES (?, ?, ?) RETURNING id",
            (email, auth.hash_password(body.password), body.name.strip()),
        )
        user_id = cur.fetchone()["id"]
        user = conn.execute("SELECT * FROM users WHERE id=?", (user_id,)).fetchone()
    request.session["user_id"] = user_id
    return row_to_user(user)


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

    Evidence comes from graded practice: `daily_attempts` today, and
    `practice_sessions` once imported tests are being practised (phase 3). Both
    feed the same coach functions, so the dashboard doesn't care which produced
    a score.
    """
    uid = user["id"]
    today = date.today().isoformat()
    week_start, week_end = coach.week_window()

    attempts = conn.execute(
        """SELECT t.kind AS skill, a.band, a.score, a.total, a.submitted_at,
                  t.content_json, a.feedback_json
           FROM daily_attempts a JOIN daily_tasks t ON t.id = a.task_id
           WHERE a.user_id=? ORDER BY a.submitted_at DESC LIMIT 40""",
        (uid,),
    ).fetchall()
    sessions = conn.execute(
        """SELECT skill, band, score, total, completed_at, duration_sec
           FROM practice_sessions
           WHERE user_id=? AND status='SUBMITTED' ORDER BY completed_at DESC LIMIT 40""",
        (uid,),
    ).fetchall()

    graded = [{"skill": (r["skill"] or "").lower(), "band": r["band"]} for r in attempts]
    graded += [{"skill": (r["skill"] or "").lower(), "band": r["band"]} for r in sessions]
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
    per_question += [
        {"type": r["question_type"], "correct": bool(r["is_correct"])}
        for r in conn.execute(
            """SELECT q.question_type, a.is_correct
               FROM practice_answers a
               JOIN practice_sessions s ON s.id = a.session_id
               JOIN ielts_questions q ON q.id = a.question_id
               WHERE s.user_id=? AND s.status='SUBMITTED'
               ORDER BY a.answered_at DESC LIMIT 500""",
            (uid,),
        ).fetchall()
    ]
    accuracy = coach.question_type_accuracy(per_question)
    weak = coach.weak_areas(accuracy)

    done_today = {(r["skill"] or "").lower() for r in attempts if (r["submitted_at"] or "")[:10] == today}
    if conn.execute(
        "SELECT 1 FROM reviews WHERE user_id=? AND reviewed_at>=? LIMIT 1", (uid, today)
    ).fetchone():
        done_today.add("vocabulary")

    week_reviews = conn.execute(
        "SELECT COUNT(*) c FROM reviews WHERE user_id=? AND reviewed_at>=? AND reviewed_at<?",
        (uid, week_start, week_end),
    ).fetchone()["c"]
    week_practice_sec = conn.execute(
        """SELECT COALESCE(SUM(duration_sec),0) s FROM practice_sessions
           WHERE user_id=? AND completed_at>=? AND completed_at<?""",
        (uid, week_start, week_end),
    ).fetchone()["s"]
    answered = sum((r["total"] or 0) for r in attempts) + sum((r["total"] or 0) for r in sessions)
    correct = sum((r["score"] or 0) for r in attempts) + sum((r["score"] or 0) for r in sessions)

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
            mistakes=unresolved_mistakes(conn, uid),
            grammar_topic=(conn.execute(
                """SELECT topic FROM grammar_mistakes WHERE user_id=? AND topic <> ''
                   GROUP BY topic ORDER BY COUNT(*) DESC LIMIT 1""",
                (uid,)).fetchone() or {"topic": ""})["topic"],
        ),
        "weak_areas": weak,
        "question_type_accuracy": accuracy,
        "activity": {
            "reviews_this_week": week_reviews,
            "practice_minutes_this_week": round((week_practice_sec or 0) / 60),
            "questions_answered": answered,
            "accuracy": round(correct / answered, 3) if answered else None,
        },
    }


class TargetBody(BaseModel):
    name: str = ""
    cefr_level: str = ""
    ielts_current: float | None = None
    ielts_target: float | None = None
    target_date: str = ""
    daily_goal_minutes: int | None = None


CEFR_LEVELS = ("A1", "A2", "B1", "B2", "C1", "C2")


@app.patch("/api/profile")
def profile_update(request: Request, body: TargetBody):
    """Onboarding + settings: IELTS target, current level, daily study time."""
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
    with db() as conn:
        conn.execute(
            """UPDATE users SET
                 name = COALESCE(NULLIF(?, ''), name),
                 cefr_level = COALESCE(NULLIF(?, ''), cefr_level),
                 ielts_current = COALESCE(?, ielts_current),
                 ielts_target = COALESCE(?, ielts_target),
                 target_date = COALESCE(NULLIF(?, ''), target_date),
                 daily_goal_minutes = COALESCE(?, daily_goal_minutes),
                 onboarded = TRUE
               WHERE id=?""",
            (body.name, body.cefr_level, body.ielts_current, body.ielts_target,
             body.target_date, body.daily_goal_minutes, user["id"]),
        )
        row = conn.execute("SELECT * FROM users WHERE id=?", (user["id"],)).fetchone()
    return row_to_user(row)


# ---------- vocabulary ----------

@app.get("/api/vocabulary")
def vocabulary_list(request: Request, state: str = "", q: str = ""):
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


@app.post("/api/vocabulary/save")
def vocabulary_save(request: Request, body: SaveBody):
    user = require_user(request)
    saved_ids = []
    with db() as conn:
        for item in body.items:
            normalized = item["word"].strip().lower()
            existing = conn.execute(
                "SELECT id FROM vocabulary WHERE user_id=? AND normalized_word=?", (user["id"], normalized)
            ).fetchone()
            if existing:
                saved_ids.append(existing["id"])
                continue
            cur = conn.execute(
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
            )
            saved_ids.append(cur.fetchone()["id"])
        if body.set_id:
            for vid in saved_ids:
                conn.execute(
                    "INSERT INTO set_words (set_id, vocabulary_id) VALUES (?, ?) ON CONFLICT DO NOTHING",
                    (body.set_id, vid),
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
            """SELECT s.*, COUNT(sw.vocabulary_id) word_count
               FROM vocabulary_sets s
               LEFT JOIN set_words sw ON sw.set_id = s.id
               WHERE s.user_id=? GROUP BY s.id ORDER BY s.created_at DESC""",
            (user["id"],),
        ).fetchall()
    return {"sets": [dict(r) for r in rows]}


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

@app.get("/api/study/flashcards")
def study_flashcards(request: Request, set_id: str = ""):
    user = require_user(request)
    with db() as conn:
        rows = fetch_study_rows(conn, user["id"], set_id, REVIEW_QUEUE_SIZE)
    return {"queue": [row_to_vocab(r) for r in rows]}


@app.get("/api/study/learn")
def study_learn(request: Request, set_id: str = ""):
    user = require_user(request)
    with db() as conn:
        queue = build_learn_queue(conn, user["id"], set_id, REVIEW_QUEUE_SIZE)
    return {"queue": queue}


class ReviewBody(BaseModel):
    vocabulary_id: int
    rating: str


@app.post("/api/review")
def api_review(request: Request, body: ReviewBody):
    user = require_user(request)
    with db() as conn:
        row = conn.execute("SELECT * FROM vocabulary WHERE id=? AND user_id=?", (body.vocabulary_id, user["id"])).fetchone()
        if not row:
            raise HTTPException(404)
        result = srs.review(row["ease"], row["interval_days"], row["repetitions"], row["lapses"], body.rating)
        conn.execute(
            """UPDATE vocabulary SET ease=?, interval_days=?, repetitions=?, lapses=?, srs_state=?,
               next_review_at=?, last_reviewed_at=CURRENT_TIMESTAMP, updated_at=CURRENT_TIMESTAMP
               WHERE id=?""",
            (result["ease"], result["interval_days"], result["repetitions"], result["lapses"],
             result["state"], result["next_review_at"], body.vocabulary_id),
        )
        conn.execute(
            "INSERT INTO reviews (vocabulary_id, user_id, rating, interval_before, interval_after) VALUES (?,?,?,?,?)",
            (body.vocabulary_id, user["id"], body.rating, row["interval_days"], result["interval_days"]),
        )
    touch_streak(user["id"])
    return {"ok": True, "state": result["state"], "next_review_at": result["next_review_at"]}


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

    grammar = conn.execute(
        """SELECT COALESCE(NULLIF(topic,''),'Other') topic, COUNT(*) c FROM grammar_mistakes
           WHERE user_id=? GROUP BY COALESCE(NULLIF(topic,''),'Other') ORDER BY c DESC LIMIT 4""",
        (user["id"],)).fetchall()
    if grammar:
        lines.append("Repeated grammar mistakes: " + ", ".join(f"{g['topic']} x{g['c']}" for g in grammar))
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
            """INSERT INTO daily_attempts (task_id, user_id, answers_json, score, total, band, feedback_json)
               VALUES (?,?,?,?,?,?,?) RETURNING id""",
            (task["id"], user["id"], json.dumps(answers), score, total, band, json.dumps(feedback)),
        )
        attempt_id = cur.fetchone()["id"]
    touch_streak(user["id"])
    return {
        "attempt": {"id": attempt_id, "answers": answers, "score": score, "total": total,
                    "band": band, "feedback": feedback},
        "content": content,  # now safe to reveal answers + explanations + vocabulary
    }


# ---------- IELTS library / document import ----------

def require_material(conn, material_id: int, user_id: int):
    """Every material read/write goes through this - a material belongs to
    exactly one user and is never visible to anyone else."""
    row = conn.execute(
        "SELECT * FROM ielts_materials WHERE id=? AND user_id=?", (material_id, user_id)
    ).fetchone()
    if not row:
        raise HTTPException(404, "Material not found.")
    return row


def material_counts(conn, material_id: int) -> dict:
    row = conn.execute(
        """SELECT COUNT(DISTINCT t.id) tests,
                  COUNT(DISTINCT s.id) sections,
                  COUNT(q.id) questions,
                  COUNT(q.id) FILTER (WHERE q.status='NEEDS_REVIEW') needs_review,
                  COUNT(q.id) FILTER (WHERE q.answer IS NULL OR q.answer='') missing_answers
           FROM ielts_tests t
           LEFT JOIN ielts_sections s ON s.test_id = t.id
           LEFT JOIN ielts_questions q ON q.section_id = s.id
           WHERE t.material_id=?""",
        (material_id,),
    ).fetchone()
    return dict(row)


@app.get("/api/library/materials")
def library_list(request: Request):
    user = require_user(request)
    with db() as conn:
        rows = conn.execute(
            "SELECT * FROM ielts_materials WHERE user_id=? ORDER BY created_at DESC", (user["id"],)
        ).fetchall()
        out = []
        for row in rows:
            job = conn.execute(
                "SELECT id, status FROM import_jobs WHERE material_id=? ORDER BY id DESC LIMIT 1",
                (row["id"],),
            ).fetchone()
            out.append({**dict(row), **material_counts(conn, row["id"]),
                        "job_id": job["id"] if job else None,
                        "job_status": job["status"] if job else None})
    return {"materials": out}


@app.post("/api/library/import")
async def library_import(request: Request):
    """Multipart upload -> stored files + a queued import job.

    Processing happens on a worker thread; the response returns immediately with
    a job id to poll. A large PDF must never block a request.
    """
    user = require_user(request)
    form = await request.form()
    uploads = []
    for value in form.getlist("files"):
        if hasattr(value, "read"):
            uploads.append((value.filename or "upload", await value.read()))
    try:
        created = imports.create_import(
            user["id"],
            str(form.get("title", "")),
            str(form.get("source", "")),
            str(form.get("description", "")),
            uploads,
        )
    except storage.UploadError as e:
        raise HTTPException(400, str(e))
    imports.enqueue(created["job_id"])
    return created


@app.get("/api/library/jobs/{job_id}")
def library_job(request: Request, job_id: int):
    user = require_user(request)
    with db() as conn:
        status = imports.job_status(conn, job_id, user["id"])
    if not status:
        raise HTTPException(404, "Import job not found.")
    return status


@app.post("/api/library/jobs/{job_id}/cancel")
def library_job_cancel(request: Request, job_id: int):
    user = require_user(request)
    with db() as conn:
        job = conn.execute(
            "SELECT * FROM import_jobs WHERE id=? AND user_id=?", (job_id, user["id"])
        ).fetchone()
        if not job:
            raise HTTPException(404, "Import job not found.")
        if job["status"] in ("READY", "FAILED", "CANCELLED"):
            raise HTTPException(400, "This import has already finished.")
        conn.execute("UPDATE import_jobs SET cancel_requested=TRUE WHERE id=?", (job_id,))
    return {"ok": True}


@app.post("/api/library/jobs/{job_id}/retry")
def library_job_retry(request: Request, job_id: int):
    """Re-run a stopped import. Pages already extracted are reused, so a retry
    resumes rather than re-reading the whole document."""
    user = require_user(request)
    with db() as conn:
        job = conn.execute(
            "SELECT * FROM import_jobs WHERE id=? AND user_id=?", (job_id, user["id"])
        ).fetchone()
        if not job:
            raise HTTPException(404, "Import job not found.")
        if job["status"] not in ("FAILED", "CANCELLED"):
            raise HTTPException(400, "This import is not stopped.")
        conn.execute("UPDATE import_jobs SET error='', cancel_requested=FALSE WHERE id=?", (job_id,))
    imports.enqueue(job_id)
    return {"ok": True}


@app.get("/api/library/materials/{material_id}")
def material_detail(request: Request, material_id: int):
    """The imported material as a tree: test -> skill -> section."""
    user = require_user(request)
    with db() as conn:
        material = require_material(conn, material_id, user["id"])
        tests = conn.execute(
            "SELECT * FROM ielts_tests WHERE material_id=? ORDER BY test_number", (material_id,)
        ).fetchall()
        sections = conn.execute(
            """SELECT s.*, COUNT(q.id) question_count,
                      COUNT(q.id) FILTER (WHERE q.status='NEEDS_REVIEW') needs_review
               FROM ielts_sections s
               LEFT JOIN ielts_questions q ON q.section_id = s.id
               WHERE s.test_id = ANY(?) GROUP BY s.id
               ORDER BY s.skill, s.section_number""",
            ([t["id"] for t in tests] or [0],),
        ).fetchall()
        job = conn.execute(
            "SELECT id, status FROM import_jobs WHERE material_id=? ORDER BY id DESC LIMIT 1",
            (material_id,),
        ).fetchone()
        counts = material_counts(conn, material_id)

    by_test = {}
    for s in sections:
        by_test.setdefault(s["test_id"], []).append(dict(s))
    return {
        "material": dict(material),
        "counts": counts,
        "job_id": job["id"] if job else None,
        "job_status": job["status"] if job else None,
        "tests": [{**dict(t), "sections": by_test.get(t["id"], [])} for t in tests],
    }


@app.get("/api/library/sections/{section_id}")
def section_detail(request: Request, section_id: int):
    """One section with its question groups and questions - the review screen."""
    user = require_user(request)
    with db() as conn:
        section = conn.execute(
            """SELECT s.*, t.test_number, t.material_id
               FROM ielts_sections s JOIN ielts_tests t ON t.id = s.test_id
               JOIN ielts_materials m ON m.id = t.material_id
               WHERE s.id=? AND m.user_id=?""",
            (section_id, user["id"]),
        ).fetchone()
        if not section:
            raise HTTPException(404, "Section not found.")
        groups = conn.execute(
            "SELECT * FROM ielts_question_groups WHERE section_id=? ORDER BY order_index", (section_id,)
        ).fetchall()
        questions = conn.execute(
            "SELECT * FROM ielts_questions WHERE section_id=? ORDER BY question_number", (section_id,)
        ).fetchall()
    return {
        "section": dict(section),
        "groups": [{**dict(g), "options": json.loads(g["options_json"] or "[]")} for g in groups],
        "questions": [{**dict(q), "options": json.loads(q["options_json"] or "[]")} for q in questions],
    }


class QuestionEditBody(BaseModel):
    question_text: str | None = None
    answer: str | None = None
    explanation: str | None = None
    options: list[str] | None = None
    question_type: str | None = None
    status: str | None = None


@app.patch("/api/library/questions/{question_id}")
def question_edit(request: Request, question_id: int, body: QuestionEditBody):
    """Corrections from the review screen become the canonical version."""
    user = require_user(request)
    with db() as conn:
        owned = conn.execute(
            """SELECT q.id FROM ielts_questions q
               JOIN ielts_sections s ON s.id = q.section_id
               JOIN ielts_tests t ON t.id = s.test_id
               JOIN ielts_materials m ON m.id = t.material_id
               WHERE q.id=? AND m.user_id=?""",
            (question_id, user["id"]),
        ).fetchone()
        if not owned:
            raise HTTPException(404, "Question not found.")
        if body.question_type and body.question_type not in ielts_parser.QUESTION_TYPES:
            raise HTTPException(400, "Unknown question type.")
        if body.status and body.status not in ("READY", "NEEDS_REVIEW"):
            raise HTTPException(400, "Unknown status.")
        conn.execute(
            """UPDATE ielts_questions SET
                 question_text = COALESCE(?, question_text),
                 answer = COALESCE(?, answer),
                 explanation = COALESCE(?, explanation),
                 options_json = COALESCE(?, options_json),
                 question_type = COALESCE(?, question_type),
                 status = COALESCE(?, status),
                 answer_source = CASE WHEN ?::text IS NULL THEN answer_source ELSE 'USER' END,
                 updated_at = CURRENT_TIMESTAMP
               WHERE id=?""",
            (body.question_text, body.answer, body.explanation,
             json.dumps(body.options) if body.options is not None else None,
             body.question_type, body.status, body.answer, question_id),
        )
        row = conn.execute("SELECT * FROM ielts_questions WHERE id=?", (question_id,)).fetchone()
    return {**dict(row), "options": json.loads(row["options_json"] or "[]")}


@app.post("/api/library/materials/{material_id}/publish")
def material_publish(request: Request, material_id: int):
    """Step 4 of the wizard: the user has reviewed the import, so the material
    joins their library and can be practised."""
    user = require_user(request)
    with db() as conn:
        require_material(conn, material_id, user["id"])
        counts = material_counts(conn, material_id)
        if not counts["questions"]:
            raise HTTPException(400, "Nothing to publish: no questions were extracted.")
        conn.execute(
            "UPDATE ielts_materials SET status='READY', updated_at=CURRENT_TIMESTAMP WHERE id=?",
            (material_id,),
        )
    return {"ok": True, **counts}


@app.delete("/api/library/materials/{material_id}")
def material_delete(request: Request, material_id: int):
    user = require_user(request)
    with db() as conn:
        require_material(conn, material_id, user["id"])
        keys = [r["storage_key"] for r in conn.execute(
            "SELECT storage_key FROM import_files WHERE material_id=?", (material_id,)).fetchall()]
        conn.execute("UPDATE import_jobs SET material_id=NULL WHERE material_id=?", (material_id,))
        conn.execute("DELETE FROM ielts_materials WHERE id=?", (material_id,))
    for key in keys:  # storage last: a failure here leaks a file, never a row
        storage.delete(key)
    return {"ok": True}


@app.get("/api/library/pages/{file_id}")
def document_page(request: Request, file_id: int, page: int = 1):
    """Extracted text for one page - the OCR review screen."""
    user = require_user(request)
    with db() as conn:
        file = conn.execute(
            "SELECT * FROM import_files WHERE id=? AND user_id=?", (file_id, user["id"])
        ).fetchone()
        if not file:
            raise HTTPException(404, "File not found.")
        row = conn.execute(
            "SELECT * FROM document_pages WHERE file_id=? AND page_number=?", (file_id, page)
        ).fetchone()
    if not row:
        raise HTTPException(404, "Page not extracted.")
    return {"file": {"id": file["id"], "filename": file["filename"], "page_count": file["page_count"]},
            "page": dict(row)}


@app.get("/api/library/files/{file_id}/raw")
def file_raw(request: Request, file_id: int):
    """Stream a private file to its owner. Storage is never served directly."""
    user = require_user(request)
    with db() as conn:
        file = conn.execute(
            "SELECT * FROM import_files WHERE id=? AND user_id=?", (file_id, user["id"])
        ).fetchone()
    if not file or not storage.exists(file["storage_key"]):
        raise HTTPException(404, "File not found.")
    safe_name = os.path.basename(file["filename"]).replace('"', "")
    return StreamingResponse(
        storage.open_file(file["storage_key"]),
        media_type=file["mime_type"] or "application/octet-stream",
        headers={"Content-Disposition": f'inline; filename="{safe_name}"'},
    )


# ---------- practice engine (imported material) ----------
#
# One engine for every skill and question type. The client is told what to render
# ("question_type") and nothing about what is correct until the session is
# submitted - in EXAM mode the answers never leave the server before then.

PRACTICE_MODES = ("EXAM", "LEARNING")


def load_practice_questions(conn, section_ids: list[int]) -> list[dict]:
    rows = conn.execute(
        """SELECT q.*, s.skill, s.section_number, s.title AS section_title
           FROM ielts_questions q JOIN ielts_sections s ON s.id = q.section_id
           WHERE q.section_id = ANY(?) ORDER BY s.section_number, q.question_number""",
        (section_ids or [0],),
    ).fetchall()
    out = []
    for r in rows:
        group_options = []
        if r["group_id"]:
            g = conn.execute(
                "SELECT options_json, instruction, body FROM ielts_question_groups WHERE id=?",
                (r["group_id"],),
            ).fetchone()
            if g:
                group_options = json.loads(g["options_json"] or "[]")
        out.append({
            **dict(r),
            "options": json.loads(r["options_json"] or "[]") or group_options,
            "acceptable_answers": json.loads(r["acceptable_answers_json"] or "[]"),
        })
    return out


def public_question(q: dict, reveal: bool) -> dict:
    """What the practice screen may see. Answers are stripped unless revealing."""
    data = {
        "id": q["id"],
        "section_id": q["section_id"],
        "group_id": q["group_id"],
        "question_number": q["question_number"],
        "question_type": q["question_type"],
        "question_text": q["question_text"],
        "instruction": q["instruction"],
        "options": q["options"],
        "word_limit": q["word_limit"],
        "skill": q["skill"],
    }
    if reveal:
        data.update({"answer": q["answer"], "acceptable_answers": q["acceptable_answers"],
                     "explanation": q["explanation"]})
    return data


def session_sections(conn, session) -> list[dict]:
    """Sections in this session, with the content the renderer needs."""
    picked = json.loads(session["question_ids_json"] or "[]") if "question_ids_json" in session else []
    if picked:
        # A targeted session pulls questions from wherever they live, so its
        # sections are whichever ones those questions came from.
        rows = conn.execute(
            """SELECT DISTINCT s.* FROM ielts_sections s
               JOIN ielts_questions q ON q.section_id = s.id
               WHERE q.id = ANY(?) ORDER BY s.id""",
            (picked,),
        ).fetchall()
        return [dict(r) for r in rows]
    if session["section_id"]:
        where, params = "s.id=?", (session["section_id"],)
    else:
        where, params = "s.test_id=? AND s.skill=?", (session["test_id"], session["skill"])
    rows = conn.execute(
        f"""SELECT s.* FROM ielts_sections s WHERE {where} ORDER BY s.section_number""", params
    ).fetchall()
    return [dict(r) for r in rows]


def session_questions(conn, session, sections) -> list[dict]:
    """The questions this session asks: a whole section, or a chosen subset."""
    questions = load_practice_questions(conn, [s["id"] for s in sections])
    picked = json.loads(session["question_ids_json"] or "[]") if "question_ids_json" in session else []
    if picked:
        order = {qid: i for i, qid in enumerate(picked)}
        questions = sorted((q for q in questions if q["id"] in order), key=lambda q: order[q["id"]])
    return questions


def session_payload(conn, session, reveal: bool) -> dict:
    sections = session_sections(conn, session)
    questions = session_questions(conn, session, sections)
    groups = conn.execute(
        """SELECT * FROM ielts_question_groups WHERE section_id = ANY(?) ORDER BY order_index""",
        ([s["id"] for s in sections] or [0],),
    ).fetchall()
    saved = conn.execute(
        "SELECT question_id, user_answer FROM practice_answers WHERE session_id=?",
        (session["id"],),
    ).fetchall()
    audio = {}
    for s in sections:
        if s["audio_file_id"]:
            audio[s["id"]] = {"file_id": s["audio_file_id"], "start": s["audio_start_sec"],
                              "end": s["audio_end_sec"]}
    learning = session["mode"] == "LEARNING"
    return {
        "session": {
            "id": session["id"], "mode": session["mode"], "skill": session["skill"],
            "status": session["status"], "started_at": session["started_at"],
            "material_id": session["material_id"], "test_id": session["test_id"],
            "section_id": session["section_id"],
        },
        "sections": [{
            "id": s["id"], "skill": s["skill"], "section_number": s["section_number"],
            "title": s["title"], "instructions": s["instructions"], "body": s["body"],
            # A transcript is a spoiler during the test; learning mode gets it
            # after submitting, exam mode never during the attempt.
            "transcript": s["transcript"] if (reveal and learning) else "",
            "first_question": s["first_question"], "last_question": s["last_question"],
            "audio": audio.get(s["id"]),
        } for s in sections],
        "groups": [{
            "id": g["id"], "section_id": g["section_id"], "question_type": g["question_type"],
            "instruction": g["instruction"], "body": g["body"], "word_limit": g["word_limit"],
            "options": json.loads(g["options_json"] or "[]"),
            "first_question": g["first_question"], "last_question": g["last_question"],
        } for g in groups],
        "questions": [public_question(q, reveal) for q in questions],
        "answers": {str(a["question_id"]): a["user_answer"] for a in saved},
    }


class StartPracticeBody(BaseModel):
    section_id: int | None = None
    test_id: int | None = None
    skill: str | None = None
    mode: str = "EXAM"


@app.post("/api/practice/sessions")
def practice_start(request: Request, body: StartPracticeBody):
    """Start (or resume) a practice session for a section or a whole skill."""
    user = require_user(request)
    if body.mode not in PRACTICE_MODES:
        raise HTTPException(400, "Unknown practice mode.")

    with db() as conn:
        if body.section_id:
            row = conn.execute(
                """SELECT s.*, t.id test_id, t.material_id FROM ielts_sections s
                   JOIN ielts_tests t ON t.id = s.test_id
                   JOIN ielts_materials m ON m.id = t.material_id
                   WHERE s.id=? AND m.user_id=?""",
                (body.section_id, user["id"]),
            ).fetchone()
            if not row:
                raise HTTPException(404, "Section not found.")
            skill, test_id, material_id = row["skill"], row["test_id"], row["material_id"]
            section_id = row["id"]
        elif body.test_id and body.skill:
            row = conn.execute(
                """SELECT t.id, t.material_id FROM ielts_tests t
                   JOIN ielts_materials m ON m.id = t.material_id
                   WHERE t.id=? AND m.user_id=?""",
                (body.test_id, user["id"]),
            ).fetchone()
            if not row:
                raise HTTPException(404, "Test not found.")
            skill, test_id, material_id, section_id = body.skill.upper(), row["id"], row["material_id"], None
        else:
            raise HTTPException(400, "Choose a section, or a test and a skill.")

        # An unfinished session for the same target is resumed, not duplicated -
        # otherwise a refresh mid-test would lose every answer so far.
        existing = conn.execute(
            """SELECT * FROM practice_sessions
               WHERE user_id=? AND status='IN_PROGRESS' AND skill=?
                 AND test_id IS NOT DISTINCT FROM ? AND section_id IS NOT DISTINCT FROM ?
               ORDER BY id DESC LIMIT 1""",
            (user["id"], skill, test_id, section_id),
        ).fetchone()
        session = existing or conn.execute(
            """INSERT INTO practice_sessions (user_id, material_id, test_id, section_id, skill, mode)
               VALUES (?,?,?,?,?,?) RETURNING *""",
            (user["id"], material_id, test_id, section_id, skill, body.mode),
        ).fetchone()
        if existing and existing["mode"] != body.mode:
            conn.execute("UPDATE practice_sessions SET mode=? WHERE id=?", (body.mode, session["id"]))
            session = conn.execute("SELECT * FROM practice_sessions WHERE id=?", (session["id"],)).fetchone()

        payload = session_payload(conn, session, reveal=False)
    if not payload["questions"]:
        raise HTTPException(400, "This section has no questions to practise yet.")
    return payload


def require_session(conn, session_id: int, user_id: int):
    row = conn.execute(
        "SELECT * FROM practice_sessions WHERE id=? AND user_id=?", (session_id, user_id)
    ).fetchone()
    if not row:
        raise HTTPException(404, "Practice session not found.")
    return row


@app.get("/api/practice/sessions/{session_id}")
def practice_get(request: Request, session_id: int):
    user = require_user(request)
    with db() as conn:
        session = require_session(conn, session_id, user["id"])
        payload = session_payload(conn, session, reveal=session["status"] == "SUBMITTED")
        if session["status"] == "SUBMITTED":
            payload["result"] = practice_result(conn, session)
    return payload


class SaveAnswersBody(BaseModel):
    answers: dict[str, str] = {}


@app.patch("/api/practice/sessions/{session_id}/answers")
def practice_save(request: Request, session_id: int, body: SaveAnswersBody):
    """Autosave. Upserts, so an interrupted test keeps everything answered so far."""
    user = require_user(request)
    with db() as conn:
        session = require_session(conn, session_id, user["id"])
        if session["status"] != "IN_PROGRESS":
            raise HTTPException(400, "This session has already been submitted.")
        sections_now = session_sections(conn, session)
        allowed = {q["id"] for q in session_questions(conn, session, sections_now)}
        for key, value in body.answers.items():
            if not key.isdigit() or int(key) not in allowed:
                continue  # ignore answers for questions outside this session
            conn.execute(
                """INSERT INTO practice_answers (session_id, question_id, user_answer)
                   VALUES (?,?,?) ON CONFLICT (session_id, question_id)
                   DO UPDATE SET user_answer=EXCLUDED.user_answer, answered_at=CURRENT_TIMESTAMP""",
                (session_id, int(key), value),
            )
    return {"ok": True, "saved": len(body.answers)}


class SubmitPracticeBody(BaseModel):
    answers: dict[str, str] = {}
    duration_sec: int | None = None


@app.post("/api/practice/sessions/{session_id}/submit")
def practice_submit(request: Request, session_id: int, body: SubmitPracticeBody):
    """Mark the session, store every answer, and reveal the results."""
    user = require_user(request)
    with db() as conn:
        session = require_session(conn, session_id, user["id"])
        if session["status"] == "SUBMITTED":
            payload = session_payload(conn, session, reveal=True)
            payload["result"] = practice_result(conn, session)
            return payload

        sections = session_sections(conn, session)
        questions = session_questions(conn, session, sections)
        saved = {str(r["question_id"]): r["user_answer"] for r in conn.execute(
            "SELECT question_id, user_answer FROM practice_answers WHERE session_id=?",
            (session_id,)).fetchall()}
        answers = {**saved, **body.answers}

        marked = ielts.mark_session(questions, answers, session["skill"])
        for result in marked["results"]:
            conn.execute(
                """INSERT INTO practice_answers
                   (session_id, question_id, user_answer, correct_answer, is_correct)
                   VALUES (?,?,?,?,?) ON CONFLICT (session_id, question_id) DO UPDATE SET
                     user_answer=EXCLUDED.user_answer, correct_answer=EXCLUDED.correct_answer,
                     is_correct=EXCLUDED.is_correct, answered_at=CURRENT_TIMESTAMP""",
                (session_id, result["question_id"], result["given"], result["answer"],
                 result["correct"]),
            )
        conn.execute(
            """UPDATE practice_sessions SET status='SUBMITTED', score=?, total=?, band=?,
                 duration_sec=?, completed_at=CURRENT_TIMESTAMP WHERE id=?""",
            (marked["score"], marked["total"], marked["band"], body.duration_sec, session_id),
        )
        session = conn.execute("SELECT * FROM practice_sessions WHERE id=?", (session_id,)).fetchone()
        payload = session_payload(conn, session, reveal=True)
        payload["result"] = {**marked, "duration_sec": body.duration_sec}
    touch_streak(user["id"])
    return payload


def practice_result(conn, session) -> dict:
    """Rebuild a submitted session's result from stored answers."""
    rows = conn.execute(
        """SELECT a.*, q.question_number, q.question_type, q.explanation
           FROM practice_answers a JOIN ielts_questions q ON q.id = a.question_id
           WHERE a.session_id=? ORDER BY q.question_number""",
        (session["id"],),
    ).fetchall()
    by_type: dict[str, list[int]] = {}
    for r in rows:
        seen, right = by_type.get(r["question_type"], [0, 0])
        by_type[r["question_type"]] = [seen + 1, right + (1 if r["is_correct"] else 0)]
    return {
        "score": session["score"], "total": session["total"], "band": session["band"],
        "band_is_estimate": (session["total"] or 0) != 40,
        "duration_sec": session["duration_sec"],
        "unanswered": sum(1 for r in rows if not (r["user_answer"] or "").strip()),
        "results": [{
            "question_id": r["question_id"], "question_number": r["question_number"],
            "given": r["user_answer"], "answer": r["correct_answer"],
            "correct": bool(r["is_correct"]), "answered": bool((r["user_answer"] or "").strip()),
            "question_type": r["question_type"], "explanation": r["explanation"],
        } for r in rows],
        "by_type": [{"type": t, "attempts": seen, "correct": right, "accuracy": right / seen}
                    for t, (seen, right) in sorted(by_type.items())],
    }


@app.get("/api/practice/sessions")
def practice_history(request: Request, limit: int = 20):
    user = require_user(request)
    with db() as conn:
        rows = conn.execute(
            """SELECT ps.*, m.title material_title, t.test_number, s.title section_title
               FROM practice_sessions ps
               LEFT JOIN ielts_materials m ON m.id = ps.material_id
               LEFT JOIN ielts_tests t ON t.id = ps.test_id
               LEFT JOIN ielts_sections s ON s.id = ps.section_id
               WHERE ps.user_id=? ORDER BY ps.started_at DESC LIMIT ?""",
            (user["id"], min(limit, 100)),
        ).fetchall()
    return {"sessions": [dict(r) for r in rows]}


@app.delete("/api/practice/sessions/{session_id}")
def practice_abandon(request: Request, session_id: int):
    user = require_user(request)
    with db() as conn:
        session = require_session(conn, session_id, user["id"])
        if session["status"] == "SUBMITTED":
            raise HTTPException(400, "A submitted session cannot be discarded.")
        conn.execute("UPDATE practice_sessions SET status='ABANDONED' WHERE id=?", (session_id,))
    return {"ok": True}


# ---------- audio: upload, matching, transcript, dictation ----------

def listening_sections(conn, material_id: int) -> list[dict]:
    rows = conn.execute(
        """SELECT s.id, s.section_number, s.title, s.audio_file_id, s.audio_confidence,
                  t.test_number
           FROM ielts_sections s JOIN ielts_tests t ON t.id = s.test_id
           WHERE t.material_id=? AND s.skill='LISTENING'
           ORDER BY t.test_number, s.section_number""",
        (material_id,),
    ).fetchall()
    return [dict(r) for r in rows]


def material_audio_files(conn, material_id: int) -> list[dict]:
    rows = conn.execute(
        """SELECT id, filename, size_bytes, duration_sec FROM import_files
           WHERE material_id=? AND kind='AUDIO' ORDER BY id""",
        (material_id,),
    ).fetchall()
    return [dict(r) for r in rows]


@app.post("/api/library/materials/{material_id}/audio")
async def material_audio_upload(request: Request, material_id: int):
    """Add audio to a material after the fact (or upload it separately)."""
    user = require_user(request)
    form = await request.form()
    uploads = []
    for value in form.getlist("files"):
        if hasattr(value, "read"):
            uploads.append((value.filename or "audio", await value.read()))
    if not uploads:
        raise HTTPException(400, "No audio files were attached.")

    with db() as conn:
        require_material(conn, material_id, user["id"])

    expanded = []
    try:
        for filename, data in uploads:
            kind, _, _ = storage.validate(data, filename)
            if kind == "ZIP":
                expanded.extend(storage.unpack_zip(data))
            elif kind == "AUDIO":
                expanded.append((filename, data))
            else:
                raise storage.UploadError(f"{filename} is not an audio file.")
        if not expanded:
            raise storage.UploadError("No MP3, M4A or WAV files were found.")
        saved = []
        with db() as conn:
            for filename, data in expanded:
                _, mime, ext = storage.validate(data, filename)
                key = storage.save(user["id"], data, ext)
                file_id = conn.execute(
                    """INSERT INTO import_files
                       (user_id, material_id, kind, filename, storage_key, mime_type, size_bytes, sha256)
                       VALUES (?,?, 'AUDIO', ?,?,?,?,?) RETURNING id""",
                    (user["id"], material_id, filename, key, mime, len(data), storage.sha256(data)),
                ).fetchone()["id"]
                saved.append({"id": file_id, "filename": filename, "size_bytes": len(data)})
    except storage.UploadError as e:
        raise HTTPException(400, str(e))
    return {"files": saved}


@app.get("/api/library/materials/{material_id}/audio")
def material_audio(request: Request, material_id: int):
    """Current audio links plus a proposal for anything unmatched."""
    user = require_user(request)
    with db() as conn:
        require_material(conn, material_id, user["id"])
        sections = listening_sections(conn, material_id)
        files = material_audio_files(conn, material_id)
    linked = {s["id"]: s["audio_file_id"] for s in sections if s["audio_file_id"]}
    unlinked_sections = [s for s in sections if not s["audio_file_id"]]
    unlinked_files = [f for f in files if f["id"] not in linked.values()]
    suggestions = audio_match.match_files(
        unlinked_files,
        [{"id": s["id"], "test_number": s["test_number"], "section_number": s["section_number"]}
         for s in unlinked_sections],
    )
    return {
        "sections": sections,
        "files": files,
        "suggestions": suggestions,
        "summary": audio_match.summarise(suggestions),
        "auto_link_threshold": audio_match.AUTO_LINK,
    }


@app.post("/api/library/materials/{material_id}/audio/match")
def material_audio_match(request: Request, material_id: int, apply_all: bool = False):
    """Link the confident matches. Anything below the threshold is left for the
    user to confirm in the matching screen, unless they ask for all of them."""
    user = require_user(request)
    with db() as conn:
        require_material(conn, material_id, user["id"])
        sections = [s for s in listening_sections(conn, material_id) if not s["audio_file_id"]]
        files = material_audio_files(conn, material_id)
        linked_ids = {s["audio_file_id"] for s in listening_sections(conn, material_id)
                      if s["audio_file_id"]}
        suggestions = audio_match.match_files(
            [f for f in files if f["id"] not in linked_ids],
            [{"id": s["id"], "test_number": s["test_number"], "section_number": s["section_number"]}
             for s in sections],
        )
        applied = 0
        for match in suggestions:
            if not match["file_id"]:
                continue
            if not apply_all and match["confidence"] < audio_match.AUTO_LINK:
                continue
            conn.execute(
                "UPDATE ielts_sections SET audio_file_id=?, audio_confidence=? WHERE id=?",
                (match["file_id"], match["confidence"], match["section_id"]),
            )
            applied += 1
    return {"applied": applied, "suggestions": suggestions}


class SectionAudioBody(BaseModel):
    file_id: int | None = None
    start_sec: float | None = None
    end_sec: float | None = None


@app.patch("/api/library/sections/{section_id}/audio")
def section_audio(request: Request, section_id: int, body: SectionAudioBody):
    """Confirm, change or clear the audio for one section (and its segment)."""
    user = require_user(request)
    with db() as conn:
        section = conn.execute(
            """SELECT s.id FROM ielts_sections s JOIN ielts_tests t ON t.id = s.test_id
               JOIN ielts_materials m ON m.id = t.material_id
               WHERE s.id=? AND m.user_id=?""",
            (section_id, user["id"]),
        ).fetchone()
        if not section:
            raise HTTPException(404, "Section not found.")
        if body.file_id is not None:
            owned = conn.execute(
                "SELECT id FROM import_files WHERE id=? AND user_id=? AND kind='AUDIO'",
                (body.file_id, user["id"]),
            ).fetchone()
            if not owned:
                raise HTTPException(404, "Audio file not found.")
        if body.start_sec is not None and body.end_sec is not None and body.end_sec <= body.start_sec:
            raise HTTPException(400, "The segment must end after it starts.")
        conn.execute(
            """UPDATE ielts_sections SET audio_file_id=?, audio_start_sec=?, audio_end_sec=?,
                 audio_confidence=? WHERE id=?""",
            (body.file_id, body.start_sec, body.end_sec,
             1.0 if body.file_id else None, section_id),
        )
        row = conn.execute("SELECT * FROM ielts_sections WHERE id=?", (section_id,)).fetchone()
    return dict(row)


class TranscriptBody(BaseModel):
    transcript: str


@app.patch("/api/library/sections/{section_id}/transcript")
def section_transcript(request: Request, section_id: int, body: TranscriptBody):
    user = require_user(request)
    with db() as conn:
        owned = conn.execute(
            """SELECT s.id FROM ielts_sections s JOIN ielts_tests t ON t.id = s.test_id
               JOIN ielts_materials m ON m.id = t.material_id
               WHERE s.id=? AND m.user_id=?""",
            (section_id, user["id"]),
        ).fetchone()
        if not owned:
            raise HTTPException(404, "Section not found.")
        conn.execute("UPDATE ielts_sections SET transcript=? WHERE id=?",
                     (body.transcript, section_id))
    return {"ok": True}


@app.post("/api/library/sections/{section_id}/transcribe")
def section_transcribe(request: Request, section_id: int):
    """Generate a transcript from the section's audio, when the book has none."""
    user = require_user(request)
    with db() as conn:
        section = conn.execute(
            """SELECT s.*, f.storage_key, f.filename FROM ielts_sections s
               JOIN ielts_tests t ON t.id = s.test_id
               JOIN ielts_materials m ON m.id = t.material_id
               LEFT JOIN import_files f ON f.id = s.audio_file_id
               WHERE s.id=? AND m.user_id=?""",
            (section_id, user["id"]),
        ).fetchone()
        if not section:
            raise HTTPException(404, "Section not found.")
        if not section["storage_key"]:
            raise HTTPException(400, "This section has no audio to transcribe.")
    try:
        text = ai.transcribe_audio(storage.local_path(section["storage_key"]), section["filename"])
    except ai.AIError as e:
        raise HTTPException(502, str(e))
    with db() as conn:
        conn.execute("UPDATE ielts_sections SET transcript=? WHERE id=?", (text, section_id))
    return {"transcript": text}


@app.get("/api/dictation/sections")
def dictation_sections(request: Request):
    """Listening sections that have both audio and a transcript - the only ones
    dictation can actually mark."""
    user = require_user(request)
    with db() as conn:
        rows = conn.execute(
            """SELECT s.id, s.title, s.transcript, t.test_number, m.id material_id, m.title material_title
               FROM ielts_sections s
               JOIN ielts_tests t ON t.id = s.test_id
               JOIN ielts_materials m ON m.id = t.material_id
               WHERE m.user_id=? AND s.skill='LISTENING'
                 AND s.audio_file_id IS NOT NULL AND s.transcript <> ''
               ORDER BY m.created_at DESC, t.test_number, s.section_number""",
            (user["id"],),
        ).fetchall()
    return {"sections": [{"id": r["id"], "title": r["title"], "test_number": r["test_number"],
                          "material_id": r["material_id"], "material_title": r["material_title"],
                          "words": len(r["transcript"].split())} for r in rows]}


@app.get("/api/dictation/sections/{section_id}")
def dictation_section(request: Request, section_id: int):
    """Audio for a dictation attempt. The transcript stays on the server."""
    user = require_user(request)
    with db() as conn:
        row = conn.execute(
            """SELECT s.id, s.title, s.audio_file_id, s.audio_start_sec, s.audio_end_sec,
                      s.transcript, t.test_number
               FROM ielts_sections s JOIN ielts_tests t ON t.id = s.test_id
               JOIN ielts_materials m ON m.id = t.material_id
               WHERE s.id=? AND m.user_id=?""",
            (section_id, user["id"]),
        ).fetchone()
    if not row or not row["audio_file_id"] or not row["transcript"]:
        raise HTTPException(404, "No dictation available for this section.")
    return {"id": row["id"], "title": row["title"], "test_number": row["test_number"],
            "audio": {"file_id": row["audio_file_id"], "start": row["audio_start_sec"],
                      "end": row["audio_end_sec"]},
            "words": len(row["transcript"].split())}


class DictationBody(BaseModel):
    typed: str


@app.post("/api/dictation/sections/{section_id}/check")
def dictation_check(request: Request, section_id: int, body: DictationBody):
    """Mark a dictation attempt against the stored transcript."""
    user = require_user(request)
    with db() as conn:
        row = conn.execute(
            """SELECT s.transcript FROM ielts_sections s JOIN ielts_tests t ON t.id = s.test_id
               JOIN ielts_materials m ON m.id = t.material_id
               WHERE s.id=? AND m.user_id=?""",
            (section_id, user["id"]),
        ).fetchone()
    if not row or not row["transcript"]:
        raise HTTPException(404, "This section has no transcript.")
    return {**dictation.compare(row["transcript"], body.typed), "transcript": row["transcript"]}


# ---------- vocabulary from imported material ----------

class LookupBody(BaseModel):
    word: str
    context: str = ""


@app.post("/api/vocabulary/lookup")
def vocabulary_lookup(request: Request, body: LookupBody):
    """Click-to-look-up from a passage or transcript. Returns an unsaved entry
    plus whether this word is already in the learner's vocabulary."""
    user = require_user(request)
    word = body.word.strip()
    if not word or len(word) > 80:
        raise HTTPException(400, "Select a word or short phrase to look up.")
    with db() as conn:
        existing = conn.execute(
            "SELECT id FROM vocabulary WHERE user_id=? AND normalized_word=?",
            (user["id"], word.lower()),
        ).fetchone()
    try:
        item = ai.lookup_word(word, body.context)
    except ai.AIError as e:
        raise HTTPException(502, str(e))
    if not item:
        raise HTTPException(404, f"No dictionary entry could be produced for “{word}”.")
    return {"item": item.model_dump(), "saved_id": existing["id"] if existing else None}


@app.post("/api/library/sections/{section_id}/vocabulary")
def section_vocabulary(request: Request, section_id: int, limit: int = 12):
    """Suggest IELTS vocabulary from a section's passage or transcript.

    Suggestions only - nothing is written to the learner's deck until they pick.
    """
    user = require_user(request)
    with db() as conn:
        section = conn.execute(
            """SELECT s.body, s.transcript, s.title FROM ielts_sections s
               JOIN ielts_tests t ON t.id = s.test_id
               JOIN ielts_materials m ON m.id = t.material_id
               WHERE s.id=? AND m.user_id=?""",
            (section_id, user["id"]),
        ).fetchone()
        if not section:
            raise HTTPException(404, "Section not found.")
        text = "\n\n".join(t for t in (section["body"], section["transcript"]) if t)
        if not text.strip():
            raise HTTPException(400, "This section has no passage or transcript to read.")
        try:
            items = ai.extract_passage_vocabulary(text, min(max(limit, 1), 25))
        except ai.AIError as e:
            raise HTTPException(502, str(e))
        known = {r["normalized_word"] for r in conn.execute(
            "SELECT normalized_word FROM vocabulary WHERE user_id=?", (user["id"],)).fetchall()}
    return {
        "items": [{**i.model_dump(), "already_saved": i.word.strip().lower() in known} for i in items],
        "section_title": section["title"],
    }


# ---------- writing & speaking (imported prompts) ----------
#
# Both skills share one flow: a prompt from imported material, an answer (typed
# or spoken), an examiner call, a stored submission, and grammar mistakes filed
# by topic so they can be practised later.

WRITING_CRITERIA = ("task_response", "coherence_cohesion", "lexical_resource", "grammatical_range")
SPEAKING_CRITERIA = ("fluency_coherence", "lexical_resource", "grammatical_range", "pronunciation")


def productive_prompts(conn, user_id: int, skill: str) -> list[dict]:
    rows = conn.execute(
        """SELECT s.id, s.title, s.instructions, s.body, s.section_number,
                  t.test_number, m.id material_id, m.title material_title,
                  (SELECT COUNT(*) FROM productive_submissions ps
                    WHERE ps.section_id = s.id AND ps.user_id = ?) attempts
           FROM ielts_sections s
           JOIN ielts_tests t ON t.id = s.test_id
           JOIN ielts_materials m ON m.id = t.material_id
           WHERE m.user_id=? AND s.skill=? AND s.body <> ''
           ORDER BY m.created_at DESC, t.test_number, s.section_number""",
        (user_id, user_id, skill),
    ).fetchall()
    return [dict(r) for r in rows]


def store_submission(conn, user_id: int, *, kind: str, section_id: int | None, task_label: str,
                     prompt: str, response: str, feedback: dict, criteria: tuple,
                     duration_sec: int | None, audio_key: str = "") -> int:
    submission_id = conn.execute(
        """INSERT INTO productive_submissions
           (user_id, kind, section_id, task_label, prompt, response, audio_key, band,
            criteria_json, feedback_json, word_count, duration_sec)
           VALUES (?,?,?,?,?,?,?,?,?,?,?,?) RETURNING id""",
        (user_id, kind, section_id, task_label, prompt, response, audio_key,
         feedback.get("band_overall"),
         json.dumps({c: feedback.get(c) for c in criteria}),
         json.dumps(feedback), len(response.split()), duration_sec),
    ).fetchone()["id"]

    for correction in feedback.get("corrections", []):
        if not correction.get("original"):
            continue
        conn.execute(
            """INSERT INTO grammar_mistakes
               (user_id, submission_id, original, correction, error_type, topic, explanation)
               VALUES (?,?,?,?,?,?,?)""",
            (user_id, submission_id, correction.get("original", ""), correction.get("improved", ""),
             correction.get("error_type", ""), correction.get("grammar_topic", ""),
             correction.get("why", "")),
        )
    return submission_id


def submission_row(row) -> dict:
    return {
        "id": row["id"], "kind": row["kind"], "section_id": row["section_id"],
        "task_label": row["task_label"], "prompt": row["prompt"], "response": row["response"],
        "band": row["band"], "criteria": json.loads(row["criteria_json"] or "{}"),
        "feedback": json.loads(row["feedback_json"] or "{}"),
        "word_count": row["word_count"], "duration_sec": row["duration_sec"],
        "has_audio": bool(row["audio_key"]), "created_at": row["created_at"],
    }


@app.get("/api/writing/prompts")
def writing_prompts(request: Request):
    user = require_user(request)
    with db() as conn:
        return {"prompts": productive_prompts(conn, user["id"], "WRITING")}


@app.get("/api/speaking/prompts")
def speaking_prompts(request: Request):
    user = require_user(request)
    with db() as conn:
        return {"prompts": productive_prompts(conn, user["id"], "SPEAKING")}


def load_prompt_section(conn, section_id: int, user_id: int, skill: str):
    row = conn.execute(
        """SELECT s.*, t.test_number FROM ielts_sections s
           JOIN ielts_tests t ON t.id = s.test_id
           JOIN ielts_materials m ON m.id = t.material_id
           WHERE s.id=? AND m.user_id=? AND s.skill=?""",
        (section_id, user_id, skill),
    ).fetchone()
    if not row:
        raise HTTPException(404, "Prompt not found.")
    return row


class WritingSubmitBody(BaseModel):
    section_id: int | None = None
    prompt: str = ""
    task_label: str = "Task 2"
    response: str
    duration_sec: int | None = None


@app.post("/api/writing/submissions")
def writing_submit(request: Request, body: WritingSubmitBody):
    """Mark an essay against the four IELTS criteria and file its grammar errors."""
    user = require_user(request)
    essay = body.response.strip()
    if len(essay.split()) < 40:
        raise HTTPException(400, "Write at least 40 words before submitting.")

    prompt, task_label, section_id = body.prompt.strip(), body.task_label, body.section_id
    if section_id:
        with db() as conn:
            section = load_prompt_section(conn, section_id, user["id"], "WRITING")
        prompt = "\n\n".join(t for t in (section["instructions"], section["body"]) if t)
        task_label = section["title"] or f"Task {section['section_number']}"
    if not prompt:
        raise HTTPException(400, "No prompt to mark this essay against.")

    try:
        feedback = ai.grade_writing(prompt, essay).model_dump()
    except ai.AIError as e:
        raise HTTPException(502, str(e))

    with db() as conn:
        submission_id = store_submission(
            conn, user["id"], kind="WRITING", section_id=section_id, task_label=task_label,
            prompt=prompt, response=essay, feedback=feedback, criteria=WRITING_CRITERIA,
            duration_sec=body.duration_sec)
        row = conn.execute("SELECT * FROM productive_submissions WHERE id=?", (submission_id,)).fetchone()
    touch_streak(user["id"])
    return submission_row(row)


@app.post("/api/speaking/submissions")
async def speaking_submit(request: Request):
    """Multipart: a recording (plus the prompt). Transcribed, then examined.

    The recording is stored privately so the learner can listen back; only the
    transcript is sent to the examiner model.
    """
    user = require_user(request)
    form = await request.form()
    section_id = form.get("section_id")
    section_id = int(section_id) if section_id else None
    prompt = str(form.get("prompt", "")).strip()
    task_label = str(form.get("task_label", "Part 1"))
    duration = form.get("duration_sec")
    duration_sec = int(float(duration)) if duration else None

    upload = form.get("audio")
    if not hasattr(upload, "read"):
        raise HTTPException(400, "No recording was attached.")
    data = await upload.read()

    if section_id:
        with db() as conn:
            section = load_prompt_section(conn, section_id, user["id"], "SPEAKING")
        prompt = "\n\n".join(t for t in (section["instructions"], section["body"]) if t)
        task_label = section["title"] or f"Part {section['section_number']}"
    if not prompt:
        raise HTTPException(400, "No prompt to mark this answer against.")

    # Browsers record WebM/Ogg, which our audio sniffer does not accept for
    # library uploads; recordings are a separate, trusted-origin path, so they
    # are size-checked and stored without the IELTS-audio type restriction.
    if len(data) > storage.MAX_AUDIO_BYTES:
        raise HTTPException(400, "That recording is too large.")
    ext = (getattr(upload, "filename", "") or "recording.webm").rsplit(".", 1)[-1].lower()
    ext = ext if ext.isalnum() and len(ext) <= 5 else "webm"
    key = storage.save(user["id"], data, ext)

    try:
        transcript = ai.transcribe_audio(storage.local_path(key), f"recording.{ext}")
        feedback = ai.grade_speaking(prompt, transcript).model_dump()
    except ai.AIError as e:
        raise HTTPException(502, str(e))

    with db() as conn:
        submission_id = store_submission(
            conn, user["id"], kind="SPEAKING", section_id=section_id, task_label=task_label,
            prompt=prompt, response=transcript, feedback=feedback, criteria=SPEAKING_CRITERIA,
            duration_sec=duration_sec, audio_key=key)
        row = conn.execute("SELECT * FROM productive_submissions WHERE id=?", (submission_id,)).fetchone()
    touch_streak(user["id"])
    return submission_row(row)


@app.get("/api/submissions")
def submissions_list(request: Request, kind: str = "", limit: int = 20):
    user = require_user(request)
    with db() as conn:
        if kind:
            rows = conn.execute(
                """SELECT * FROM productive_submissions WHERE user_id=? AND kind=?
                   ORDER BY created_at DESC LIMIT ?""",
                (user["id"], kind.upper(), min(limit, 100))).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM productive_submissions WHERE user_id=? ORDER BY created_at DESC LIMIT ?",
                (user["id"], min(limit, 100))).fetchall()
    return {"submissions": [submission_row(r) for r in rows]}


@app.get("/api/submissions/{submission_id}")
def submission_detail(request: Request, submission_id: int):
    user = require_user(request)
    with db() as conn:
        row = conn.execute(
            "SELECT * FROM productive_submissions WHERE id=? AND user_id=?",
            (submission_id, user["id"])).fetchone()
    if not row:
        raise HTTPException(404, "Submission not found.")
    return submission_row(row)


@app.get("/api/submissions/{submission_id}/audio")
def submission_audio(request: Request, submission_id: int):
    """Play back your own recording."""
    user = require_user(request)
    with db() as conn:
        row = conn.execute(
            "SELECT audio_key FROM productive_submissions WHERE id=? AND user_id=?",
            (submission_id, user["id"])).fetchone()
    if not row or not row["audio_key"] or not storage.exists(row["audio_key"]):
        raise HTTPException(404, "No recording for this submission.")
    return StreamingResponse(storage.open_file(row["audio_key"]), media_type="audio/webm")


@app.get("/api/grammar/mistakes")
def grammar_mistakes(request: Request, limit: int = 50):
    """Grammar errors grouped by topic - the input to grammar practice."""
    user = require_user(request)
    with db() as conn:
        topics = conn.execute(
            """SELECT COALESCE(NULLIF(topic,''), 'Other') topic, COUNT(*) count,
                      MAX(created_at) last_seen
               FROM grammar_mistakes WHERE user_id=?
               GROUP BY COALESCE(NULLIF(topic,''), 'Other') ORDER BY count DESC""",
            (user["id"],)).fetchall()
        recent = conn.execute(
            """SELECT * FROM grammar_mistakes WHERE user_id=?
               ORDER BY created_at DESC LIMIT ?""",
            (user["id"], min(limit, 200))).fetchall()
    return {"topics": [dict(t) for t in topics], "mistakes": [dict(m) for m in recent]}


# ---------- adaptive practice: weaknesses turned into questions ----------

def unresolved_mistakes(conn, user_id: int) -> int:
    """Questions the learner has answered and never once got right.

    A question answered wrong in March and right in April is not a mistake any
    more, so it must not be counted as one - the "redo" set uses the same rule.
    """
    return conn.execute(
        """SELECT COUNT(*) c FROM (
             SELECT a.question_id FROM practice_answers a
             JOIN practice_sessions ps ON ps.id = a.session_id
             JOIN ielts_questions q ON q.id = a.question_id
             WHERE ps.user_id=? AND ps.status='SUBMITTED' AND q.answer <> ''
             GROUP BY a.question_id HAVING BOOL_AND(a.is_correct = FALSE)
           ) unresolved""",
        (user_id,)).fetchone()["c"]


class TargetedBody(BaseModel):
    source: str = "MISTAKES"      # MISTAKES | TYPE
    question_type: str | None = None
    limit: int = 10
    mode: str = "LEARNING"


@app.post("/api/practice/targeted")
def practice_targeted(request: Request, body: TargetedBody):
    """Build a session from the learner's own weak spots.

    MISTAKES - questions they have answered incorrectly before.
    TYPE     - questions of one question type, unpractised ones first.

    Only questions that can actually be marked (an answer exists) are included,
    so a targeted set never contains a question that will mark itself wrong.
    """
    user = require_user(request)
    if body.mode not in PRACTICE_MODES:
        raise HTTPException(400, "Unknown practice mode.")
    limit = min(max(body.limit, 1), 40)

    with db() as conn:
        if body.source.upper() == "MISTAKES":
            rows = conn.execute(
                """SELECT q.id, MAX(a.answered_at) last_seen
                   FROM practice_answers a
                   JOIN practice_sessions ps ON ps.id = a.session_id
                   JOIN ielts_questions q ON q.id = a.question_id
                   WHERE ps.user_id=? AND ps.status='SUBMITTED' AND a.is_correct = FALSE
                     AND q.answer <> ''
                   GROUP BY q.id
                   HAVING BOOL_AND(a.is_correct = FALSE)  -- still unmastered
                   ORDER BY last_seen DESC LIMIT ?""",
                (user["id"], limit),
            ).fetchall()
            label = "Redo my mistakes"
        else:
            qtype = coach.canonical_type(body.question_type or "")
            if qtype not in ielts_parser.QUESTION_TYPES:
                raise HTTPException(400, "Unknown question type.")
            rows = conn.execute(
                """SELECT q.id,
                          (SELECT COUNT(*) FROM practice_answers a
                            JOIN practice_sessions ps ON ps.id = a.session_id
                            WHERE a.question_id = q.id AND ps.user_id = ?) seen
                   FROM ielts_questions q
                   JOIN ielts_sections s ON s.id = q.section_id
                   JOIN ielts_tests t ON t.id = s.test_id
                   JOIN ielts_materials m ON m.id = t.material_id
                   WHERE m.user_id=? AND q.question_type=? AND q.answer <> ''
                   ORDER BY seen, q.id LIMIT ?""",
                (user["id"], user["id"], qtype, limit),
            ).fetchall()
            label = f"Targeted practice: {coach.label_for(qtype)}"

        question_ids = [r["id"] for r in rows]
        if not question_ids:
            raise HTTPException(
                400,
                "No questions available for that yet. Import material and practise it first."
                if body.source.upper() != "MISTAKES"
                else "You have no unresolved mistakes to redo - nice.",
            )

        skill = conn.execute(
            """SELECT s.skill FROM ielts_questions q JOIN ielts_sections s ON s.id = q.section_id
               WHERE q.id=?""", (question_ids[0],)).fetchone()["skill"]
        session = conn.execute(
            """INSERT INTO practice_sessions (user_id, skill, mode, question_ids_json, label)
               VALUES (?,?,?,?,?) RETURNING *""",
            (user["id"], skill, body.mode, json.dumps(question_ids), label),
        ).fetchone()
        payload = session_payload(conn, session, reveal=False)
    payload["session"]["label"] = label
    return payload


@app.get("/api/practice/weaknesses")
def practice_weaknesses(request: Request):
    """Everything the coach knows about what to work on, in one call."""
    user = require_user(request)
    with db() as conn:
        coaching = build_coaching(conn, user)
        mistakes = unresolved_mistakes(conn, user["id"])
        grammar = conn.execute(
            """SELECT COALESCE(NULLIF(topic,''),'Other') topic, COUNT(*) count
               FROM grammar_mistakes WHERE user_id=?
               GROUP BY COALESCE(NULLIF(topic,''),'Other') ORDER BY count DESC LIMIT 6""",
            (user["id"],)).fetchall()
        weak_words = conn.execute(
            """SELECT word, translation, lapses FROM vocabulary
               WHERE user_id=? AND lapses > 0 ORDER BY lapses DESC, next_review_at LIMIT 10""",
            (user["id"],)).fetchall()
        practised_types = conn.execute(
            """SELECT DISTINCT q.question_type FROM ielts_questions q
               JOIN ielts_sections s ON s.id = q.section_id
               JOIN ielts_tests t ON t.id = s.test_id
               JOIN ielts_materials m ON m.id = t.material_id
               WHERE m.user_id=? AND q.answer <> ''""",
            (user["id"],)).fetchall()
    return {
        **coaching,
        "unresolved_mistakes": mistakes,
        "grammar_topics": [dict(g) for g in grammar],
        "weak_words": [dict(w) for w in weak_words],
        "available_types": sorted({p["question_type"] for p in practised_types}),
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

        # Band history from both sources of graded work, oldest first.
        history = conn.execute(
            """SELECT skill, band, score, total, completed_at AS at, 'practice' AS source
               FROM practice_sessions
               WHERE user_id=? AND status='SUBMITTED' AND band IS NOT NULL AND completed_at>=?
               UNION ALL
               SELECT t.kind AS skill, a.band, a.score, a.total, a.submitted_at AS at,
                      'daily' AS source
               FROM daily_attempts a JOIN daily_tasks t ON t.id = a.task_id
               WHERE a.user_id=? AND a.band IS NOT NULL AND a.submitted_at>=?
               UNION ALL
               SELECT LOWER(kind) AS skill, band, NULL, NULL, created_at AS at,
                      'submission' AS source
               FROM productive_submissions
               WHERE user_id=? AND band IS NOT NULL AND created_at>=?
               ORDER BY at""",
            (user["id"], since, user["id"], since, user["id"], since),
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
                 SELECT LEFT(completed_at, 10) AS day, COALESCE(SUM(total), 1) items
                  FROM practice_sessions
                  WHERE user_id=? AND status='SUBMITTED' AND completed_at>=?
                  GROUP BY LEFT(completed_at, 10)
                 UNION ALL
                 SELECT LEFT(submitted_at, 10) AS day, COALESCE(SUM(total), 1) items
                  FROM daily_attempts WHERE user_id=? AND submitted_at>=?
                  GROUP BY LEFT(submitted_at, 10)
               ) d GROUP BY day ORDER BY day""",
            (user["id"], since, user["id"], since, user["id"], since),
        ).fetchall()

        submissions = conn.execute(
            """SELECT kind, COUNT(*) count, AVG(band) avg_band, MAX(band) best_band
               FROM productive_submissions WHERE user_id=? AND band IS NOT NULL
               GROUP BY kind""",
            (user["id"],),
        ).fetchall()
        tests_done = conn.execute(
            "SELECT COUNT(*) c FROM practice_sessions WHERE user_id=? AND status='SUBMITTED'",
            (user["id"],)).fetchone()["c"]

    retention = None
    if reviews["total"]:
        retention = round(1 - (reviews["lapses"] / reviews["total"]), 3)

    return {
        "bands": coaching["bands"],
        "question_type_accuracy": coaching["question_type_accuracy"],
        "weak_areas": coaching["weak_areas"],
        "history": [{"skill": (h["skill"] or "").lower(), "band": h["band"], "score": h["score"],
                     "total": h["total"], "at": h["at"], "source": h["source"]} for h in history],
        "vocabulary": {**dict(vocab), "avg_interval": round(vocab["avg_interval"] or 0, 1),
                       "retention": retention, "reviews_in_window": reviews["total"]},
        "activity": [{"day": a["day"], "items": a["items"]} for a in activity],
        "submissions": [dict(s) for s in submissions],
        "tests_completed": tests_done,
        "streak": user["streak"],
        "days": days,
    }

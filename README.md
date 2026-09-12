# Language Input

An IELTS-focused English vocabulary and study app for Vietnamese learners. Paste in
a word, phrase, or a whole paragraph and it extracts vocabulary, translates it,
schedules it for spaced-repetition review, and generates daily reading/listening/
writing practice — all graded by AI.

## Stack

- **Backend**: FastAPI (Python), MySQL (`PyMySQL`), OpenAI for extraction/
  tutoring/grading, session-cookie auth.
- **Frontend**: Next.js (App Router) + React, plain CSS (no UI framework).

## Features

- **Vocabulary capture** — paste text, AI extracts words/phrases with translation,
  definition, pronunciation, examples, synonyms/antonyms, collocations, IELTS level.
- **Spaced repetition (FSRS)** — flashcards and a "learn" mode (multiple choice,
  true/false, fill-in-the-blank, type-the-answer) that adapt question difficulty to
  how well you know each word, scheduled by the same FSRS algorithm family Anki uses.
- **Vocabulary sets** — group words into custom study sets.
- **AI tutor** — chat about grammar/vocabulary/usage; it knows the words you're
  struggling with.
- **Daily IELTS practice** — AI-generated reading passage, listening script, and
  writing prompt each day, auto-graded (writing gets full band-score feedback).
- **IELTS target & study plan** — first-run setup captures current level, target band,
  test date and daily study time; the dashboard turns that into today's plan.
- **Coach dashboard** — estimated band per skill from real graded practice, gap to
  target, weakest question types, and a prioritised plan for today.
- **Progress** — band history per skill, accuracy by question type, vocabulary
  retention, and study activity, all from real graded daily practice.

## Project layout

```
backend/
  main.py       FastAPI app: routes for auth, vocabulary, sets, study, tutor, daily practice
  db.py         MySQL connection + schema
  coach.py      Band estimates, weak-area detection, today's study plan
  auth.py       Password hashing/verification
  srs.py        FSRS spaced-repetition scheduler (wraps the `fsrs` library)
  ielts.py      IELTS band-conversion tables, used to score daily reading/listening
  ai.py         OpenAI prompts/schemas: extraction, tutor, daily practice, essay grading
  requirements.txt
frontend/       Next.js app (see frontend/README.md for its own notes)
```

## Setup

### Backend

```bash
py -m venv venv
venv\Scripts\activate        # macOS/Linux: source venv/bin/activate
pip install -r requirements.txt
```

Copy `backend/.env.example` to `backend/.env` and fill in:

```
OPENAI_API_KEY=sk-...
SESSION_SECRET=some-random-string
FRONTEND_ORIGIN=http://localhost:3000
DATABASE_URL=mysql://root:@localhost:3306/language_input
```

Make sure the MySQL database in `DATABASE_URL` exists
(`mysql -u root -e "CREATE DATABASE language_input"`), then start the API —
tables are created automatically on startup:

```bash
uvicorn main:app --reload --app-dir backend
```

API runs at `http://localhost:8000`.

### Frontend

```bash
cd frontend
npm install
npm run dev
```

Set `NEXT_PUBLIC_API_URL` in `frontend/.env.local` to point at the backend (defaults
to `http://localhost:8000` if unset — check `frontend/lib/api.ts`).

App runs at `http://localhost:3000`.

## API overview

| Area | Routes |
|---|---|
| Auth | `POST /api/auth/login`, `logout`, `GET /api/auth/me` |
| Dashboard | `GET /api/dashboard` — counts, band estimates, today's plan, weak areas |
| Profile | `PATCH /api/profile` — IELTS target, CEFR level, test date, daily goal |
| Progress | `GET /api/progress` |
| Vocabulary | `GET/POST /api/vocabulary`, `extract`, `save`, `GET/PATCH/DELETE /api/vocabulary/{id}`, `star` |
| Sets | `GET/POST /api/sets`, `GET/DELETE /api/sets/{id}`, `POST/DELETE .../words` |
| Study | `GET /api/study/due`, `GET /api/study/flashcards`, `GET /api/study/learn`, `POST /api/review` |
| Tutor | `POST /api/tutor` |
| Daily practice | `GET /api/daily`, `GET /api/daily/{kind}`, `POST /api/daily/{kind}/generate`, `POST /api/daily/{kind}/submit` |

## Tests

No test framework — each module self-checks with `assert`s. Run these from `backend/`:

```bash
cd backend
python auth.py && python srs.py && python ielts.py && python coach.py && python db.py
```

There is no end-to-end suite currently — it was removed along with the imported-material
features it exercised (import pipeline, practice engine, dictation, writing/speaking
submissions).

## The learning loop

Everything is wired into one cycle, and each arrow is a real link in the app:

```
today's plan -> daily reading/listening/writing -> graded by AI -> band + weak areas
      ^                                                                    |
      |                                                                    v
 spaced repetition <---------------------- vocabulary saved <---- weak words & topics
```

A word extracted from your own input (or generated inside a daily task) enters the
same SM-2 review queue as everything else; a weak question type from recent daily
attempts becomes today's first task. Nothing on the dashboard is a placeholder — if
there is no evidence for something, it says so instead of showing a number.

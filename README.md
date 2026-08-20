# Language Input

An IELTS-focused English vocabulary and study app for Vietnamese learners. Paste in
a word, phrase, or a whole paragraph and it extracts vocabulary, translates it,
schedules it for spaced-repetition review, and generates daily reading/listening/
writing practice — all graded by AI.

## Stack

- **Backend**: FastAPI (Python), PostgreSQL (`psycopg2`), OpenAI for extraction/
  tutoring/grading, session-cookie auth.
- **Frontend**: Next.js (App Router) + React, plain CSS (no UI framework).

## Features

- **Vocabulary capture** — paste text, AI extracts words/phrases with translation,
  definition, pronunciation, examples, synonyms/antonyms, collocations, IELTS level.
- **Spaced repetition (SM-2)** — flashcards and a "learn" mode (multiple choice,
  true/false, fill-in-the-blank, type-the-answer) that adapt question difficulty to
  how well you know each word.
- **Vocabulary sets** — group words into custom study sets.
- **AI tutor** — chat about grammar/vocabulary/usage; it knows the words you're
  struggling with.
- **Daily IELTS practice** — AI-generated reading passage, listening script, and
  writing prompt each day, auto-graded (writing gets full band-score feedback).
- **IELTS target & study plan** — first-run setup captures current level, target band,
  test date and daily study time; the dashboard turns that into today's plan.
- **Coach dashboard** — estimated band per skill from real graded practice, gap to
  target, weakest question types, and a prioritised plan for today.
- **IELTS library & document import** — upload an IELTS PDF you own; a background
  job extracts every page (OCR for scanned pages), detects tests / skills /
  sections / question ranges, parses questions with AI, imports any answer key,
  and shows a review screen before you publish it to your library. Everything
  extracted keeps its source page, extraction method and confidence, and stays
  editable.
- **Practice engine** — one engine renders every question type from every source
  (imported, edited, generated later). Exam mode: countdown, audio plays once, no
  answers until you submit. Learning mode: replay, transcript, explanations and
  click-to-look-up. Autosaves, resumes, marks strictly (word limits enforced,
  plurals not accepted unless the material says so) and converts raw scores with
  the published band tables.
- **Audio** — upload MP3/M4A/WAV or a ZIP; filenames are matched to listening
  sections with a confidence score (high confidence links itself, the rest you
  confirm). Segment support, playback speed, and a dictation mode that diffs what
  you typed against the transcript word by word.
- **Writing & speaking** — answer imported Task 1/2 and Part 1–3 prompts. Essays and
  recordings (transcribed first) are marked on all four official criteria, with your
  own sentences corrected, each error tagged with its grammar topic and counted.
- **Adaptive practice** — "redo my mistakes" and "10 more Matching Headings" build
  sessions from your actual record; the dashboard plan reprioritises around them.
- **Progress** — band history per skill, accuracy by question type, vocabulary
  retention, and study activity, all from real graded work.

## Project layout

```
main.py       FastAPI app: routes for auth, vocabulary, sets, study, tutor, daily practice
db.py         Postgres connection + schema (app tables, IELTS content/import tables)
coach.py      Band estimates, weak-area detection, today's study plan
storage.py    Private file storage: type sniffing, size limits, content-addressed keys
documents.py  PDF page text extraction + OCR fallback (PyMuPDF, vision model)
ielts_parser.py  Test/section/question detection: regex outline + AI extraction
imports.py    The import pipeline and its background job runner
audio_match.py   Matching audio filenames to listening sections, with confidence
dictation.py  Word-level diff of a dictation attempt against its transcript
test_*.py     End-to-end tests against a real database (AI stubbed)
auth.py       Password hashing/verification
srs.py        SM-2 spaced-repetition scheduler
ai.py         OpenAI prompts/schemas: extraction, tutor, daily practice, essay grading
frontend/     Next.js app (see frontend/README.md for its own notes)
```

## Setup

### Backend

```bash
python -m venv venv
venv\Scripts\activate        # macOS/Linux: source venv/bin/activate
pip install -r requirements.txt
```

Copy `.env.example` to `.env` and fill in:

```
OPENAI_API_KEY=sk-...
SESSION_SECRET=some-random-string
FRONTEND_ORIGIN=http://localhost:3000
DATABASE_URL=postgresql://postgres:postgres@localhost:5432/language_input
```

Make sure the Postgres database in `DATABASE_URL` exists (`createdb language_input`),
then start the API — tables are created automatically on startup:

```bash
uvicorn main:app --reload
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
| Auth | `POST /api/auth/signup`, `login`, `logout`, `GET /api/auth/me` |
| Dashboard | `GET /api/dashboard` — counts, band estimates, today's plan, weak areas |
| Profile | `PATCH /api/profile` — IELTS target, CEFR level, test date, daily goal |
| IELTS library | `GET /api/library/materials`, `GET/DELETE .../{id}`, `POST .../{id}/publish` |
| Import | `POST /api/library/import` (multipart), `GET /api/library/jobs/{id}`, `POST .../cancel`, `POST .../retry` |
| Imported content | `GET /api/library/sections/{id}`, `PATCH /api/library/questions/{id}`, `GET /api/library/pages/{file_id}?page=N`, `GET /api/library/files/{id}/raw` |
| Audio | `GET/POST /api/library/materials/{id}/audio`, `POST .../audio/match`, `PATCH /api/library/sections/{id}/audio`, `PATCH/POST .../transcript`, `.../transcribe` |
| Practice | `POST /api/practice/sessions`, `GET/DELETE .../{id}`, `PATCH .../answers`, `POST .../submit`, `POST /api/practice/targeted`, `GET /api/practice/weaknesses` |
| Dictation | `GET /api/dictation/sections`, `GET .../{id}`, `POST .../{id}/check` |
| Writing / speaking | `GET /api/writing/prompts`, `GET /api/speaking/prompts`, `POST /api/writing/submissions`, `POST /api/speaking/submissions`, `GET /api/submissions[/{id}[/audio]]`, `GET /api/grammar/mistakes` |
| Progress | `GET /api/progress` |
| Vocabulary | `GET/POST /api/vocabulary`, `extract`, `save`, `GET/PATCH/DELETE /api/vocabulary/{id}`, `star` |
| Sets | `GET/POST /api/sets`, `GET/DELETE /api/sets/{id}`, `POST/DELETE .../words` |
| Study | `GET /api/study/flashcards`, `GET /api/study/learn`, `POST /api/review` |
| Tutor | `POST /api/tutor` |
| Daily practice | `GET /api/daily`, `GET /api/daily/{kind}`, `POST /api/daily/{kind}/generate`, `POST /api/daily/{kind}/submit` |

## Importing IELTS material

Only upload material you have the right to use. Imports are private to your
account: files live outside any web-served directory, are streamed back only to
their owner, and nothing is shared or published anywhere. No IELTS content ships
with this repository.

The pipeline (`imports.py`) runs on a background thread and writes its progress
to the `import_jobs` row, so the UI can show it live:

```
upload -> extract page text (OCR fallback) -> detect tests/skills/sections
       -> AI-parse questions per section -> merge answer key -> review -> publish
```

Extracted pages are stored per page, so an interrupted import resumes where it
stopped instead of re-reading the document. Every question keeps its source page,
extraction confidence and answer source (`DOCUMENT` from a printed answer key,
`AI` when the parser produced it, `USER` once you confirm it), and can be edited
in the review screen — corrections become the canonical version.

Relevant environment variables (see `.env.example`): `STORAGE_DIR`, `MAX_PDF_MB`,
`MAX_AUDIO_MB`, `OCR_PROVIDER` (`openai` or `none`), `OCR_MODEL`, `OCR_DPI`,
`PDF_MIN_TEXT_CHARS`.

## Tests

No test framework — each module self-checks with `assert`s:

```bash
# module self-checks (no database, no API calls)
python auth.py && python srs.py && python ielts.py && python coach.py && python db.py
python storage.py && python documents.py && python ielts_parser.py && python imports.py
python audio_match.py && python dictation.py

# end-to-end, against the real database (AI and OCR stubbed, so free)
python test_import.py       # PDF -> pages -> structure -> questions -> answer key
python test_practice.py     # sessions, autosave, resume, marking, band, privacy
python test_audio.py        # audio upload, matching, transcript, dictation
python test_productive.py   # writing + speaking submissions, grammar mistakes
python test_adaptive.py     # redo-my-mistakes, targeted practice, progress
```

## The learning loop

Everything is wired into one cycle, and each arrow is a real link in the app:

```
import a book -> practise a section -> get marked -> mistakes recorded
      ^                                                     |
      |                                                     v
 targeted practice <- weak question types <- dashboard <- vocabulary saved
      |                                                     |
      +------------------ spaced repetition <---------------+
```

A question answered wrong becomes a "redo my mistakes" item; a question type below
75% over enough attempts becomes today's first task; a word looked up in a passage
enters the same review queue as everything else; grammar errors the examiner finds
are counted by topic. Nothing on the dashboard is a placeholder — if there is no
evidence for something, it says so instead of showing a number.

## Design notes

- **One practice engine.** Imported, hand-edited and (later) generated questions all
  render through the same `QuestionRenderer`, so a new question type is a branch, not
  a new screen.
- **Nothing automatic is trusted.** OCR text, parsed questions and AI-suggested
  answers are stored with their source page, method and confidence, marked
  `NEEDS_REVIEW` below threshold, and are editable — your correction becomes canonical.
- **Answer sources are labelled**: `DOCUMENT` (printed answer key), `AI` (the parser's
  reading — models infer answers even when told not to), `USER` (you confirmed it).
- **Strict marking.** Word limits are enforced; "apples" is not "apple" unless the
  material lists it as acceptable.
- **Copyright.** No IELTS content ships with this repository, imports are private to
  the uploading account, and files are served only through authenticated endpoints.

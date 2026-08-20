"""The import pipeline: uploaded PDF -> pages -> outline -> sections & questions.

Runs off the request thread, one step at a time, writing progress to the
`import_jobs` row as it goes so the UI can show what is happening.

Resumable by construction: extracted pages are stored as they are produced with
a UNIQUE(file_id, page_number), so a job that dies on page 120 restarts at page
120, not page 1. Re-running a finished step is a no-op rather than a duplicate.

ponytail: the "queue" is a daemon thread, because this app runs as one process
for one learner. `enqueue()` is the seam - swap in Celery/RQ/arq there and
nothing else moves. The DB row, not the thread, is the source of truth, so a
process restart leaves a job visibly stuck rather than silently lost.
"""
import json
import threading
import traceback
from datetime import datetime, timezone

from dotenv import load_dotenv

load_dotenv()  # so `python imports.py` and the worker thread both see DATABASE_URL

import documents
import ielts_parser
import storage
from ai import AIError
from db import db

# Steps shown in the progress UI, in order.
STEPS = ["Upload", "Extract text", "Detect structure", "Read questions", "Validate"]


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


# --- job bookkeeping ---------------------------------------------------------

def _set(conn, job_id: int, **fields):
    if not fields:
        return
    assigns = ", ".join(f"{k}=?" for k in fields)
    conn.execute(f"UPDATE import_jobs SET {assigns} WHERE id=?", (*fields.values(), job_id))


def _step(conn, job_id: int, name: str, status: str, detail: str = ""):
    """Record one pipeline step. Steps are a list, so the UI can render a log."""
    row = conn.execute("SELECT steps_json FROM import_jobs WHERE id=?", (job_id,)).fetchone()
    steps = json.loads(row["steps_json"] or "[]")
    for s in steps:
        if s["step"] == name:
            s.update({"status": status, "detail": detail, "at": _now()})
            break
    else:
        steps.append({"step": name, "status": status, "detail": detail, "at": _now()})
    _set(conn, job_id, steps_json=json.dumps(steps), current_step=name)


def _warn(conn, job_id: int, message: str):
    row = conn.execute("SELECT warnings_json FROM import_jobs WHERE id=?", (job_id,)).fetchone()
    warnings = json.loads(row["warnings_json"] or "[]")
    if message not in warnings:
        warnings.append(message)
        _set(conn, job_id, warnings_json=json.dumps(warnings))


def _cancelled(conn, job_id: int) -> bool:
    row = conn.execute("SELECT cancel_requested FROM import_jobs WHERE id=?", (job_id,)).fetchone()
    return bool(row and row["cancel_requested"])


class Cancelled(Exception):
    pass


# --- creating an import ------------------------------------------------------

def create_import(user_id: int, title: str, source: str, description: str,
                  uploads: list[tuple[str, bytes]]) -> dict:
    """Validate + store uploads, create the material, job and file rows.

    Returns {"job_id", "material_id", "files", "duplicates"}.
    Raises storage.UploadError if a file is rejected - nothing is written then.
    """
    if not title.strip():
        raise storage.UploadError("Give the material a name.")
    if not uploads:
        raise storage.UploadError("Attach at least one PDF.")

    # Expand zips first, then validate everything before writing anything.
    expanded: list[tuple[str, bytes]] = []
    for filename, data in uploads:
        kind, _, _ = storage.validate(data, filename)
        if kind == "ZIP":
            members = storage.unpack_zip(data)
            if not members:
                raise storage.UploadError(f"{filename} contains no MP3/M4A/WAV files.")
            expanded.extend(members)
        else:
            expanded.append((filename, data))

    prepared = []
    for filename, data in expanded:
        kind, mime, ext = storage.validate(data, filename)
        prepared.append({"filename": filename, "data": data, "kind": kind,
                         "mime": mime, "ext": ext, "sha256": storage.sha256(data)})
    if not any(p["kind"] == "PDF" for p in prepared):
        raise storage.UploadError("Attach the PDF for this material.")

    with db() as conn:
        duplicates = [
            {"filename": p["filename"], "material": row["title"]}
            for p in prepared
            for row in [conn.execute(
                """SELECT m.title FROM import_files f
                   JOIN ielts_materials m ON m.id = f.material_id
                   WHERE f.user_id=? AND f.sha256=? LIMIT 1""",
                (user_id, p["sha256"]),
            ).fetchone()]
            if row
        ]

        material_id = conn.execute(
            """INSERT INTO ielts_materials (user_id, title, source, description, status)
               VALUES (?,?,?,?, 'IMPORTING') RETURNING id""",
            (user_id, title.strip(), source.strip(), description.strip()),
        ).fetchone()["id"]
        job_id = conn.execute(
            """INSERT INTO import_jobs (user_id, material_id, status, current_step)
               VALUES (?,?, 'UPLOADED', 'Upload') RETURNING id""",
            (user_id, material_id),
        ).fetchone()["id"]

        files = []
        for p in prepared:
            key = storage.save(user_id, p["data"], p["ext"])
            file_id = conn.execute(
                """INSERT INTO import_files
                   (job_id, user_id, material_id, kind, filename, storage_key, mime_type, size_bytes, sha256)
                   VALUES (?,?,?,?,?,?,?,?,?) RETURNING id""",
                (job_id, user_id, material_id, p["kind"], p["filename"], key,
                 p["mime"], len(p["data"]), p["sha256"]),
            ).fetchone()["id"]
            files.append({"id": file_id, "filename": p["filename"], "kind": p["kind"],
                          "size_bytes": len(p["data"])})
        _step(conn, job_id, "Upload", "done", f"{len(files)} file(s) stored")
    return {"job_id": job_id, "material_id": material_id, "files": files, "duplicates": duplicates}


def enqueue(job_id: int) -> None:
    """Hand the job to a worker. See module docstring for the upgrade path."""
    with db() as conn:
        _set(conn, job_id, status="QUEUED", cancel_requested=False)
    threading.Thread(target=run_job, args=(job_id,), daemon=True).start()


# --- the pipeline ------------------------------------------------------------

def run_job(job_id: int) -> None:
    try:
        _run(job_id)
    except Cancelled:
        with db() as conn:
            _set(conn, job_id, status="CANCELLED", completed_at=_now())
    except Exception as e:  # a crashed import must still be visible and explainable
        traceback.print_exc()
        with db() as conn:
            _set(conn, job_id, status="FAILED", error=str(e), completed_at=_now())
            conn.execute("UPDATE ielts_materials SET status='FAILED' WHERE id=(SELECT material_id FROM import_jobs WHERE id=?)", (job_id,))


def _run(job_id: int) -> None:
    with db() as conn:
        job = conn.execute("SELECT * FROM import_jobs WHERE id=?", (job_id,)).fetchone()
        if not job:
            return
        pdfs = conn.execute(
            "SELECT * FROM import_files WHERE job_id=? AND kind='PDF' ORDER BY id", (job_id,)
        ).fetchall()
        _set(conn, job_id, status="EXTRACTING", started_at=_now(), error="")
    material_id = job["material_id"]

    pages = _extract_pages(job_id, pdfs)
    outlined = _detect_structure(job_id, pages)
    _build_content(job_id, material_id, outlined, pages)
    _validate(job_id, material_id, outlined, pages)

    with db() as conn:
        _set(conn, job_id, status="READY", completed_at=_now())
        conn.execute("UPDATE ielts_materials SET status='NEEDS_REVIEW' WHERE id=?", (material_id,))


def _extract_pages(job_id: int, pdfs) -> list[dict]:
    """Page text for every PDF, skipping pages already done (resume)."""
    total = 0
    counts = {}
    for f in pdfs:
        try:
            counts[f["id"]] = documents.page_count(storage.local_path(f["storage_key"]))
        except documents.ExtractionError as e:
            with db() as conn:
                _step(conn, job_id, "Extract text", "error", str(e))
            raise
        total += counts[f["id"]]
    with db() as conn:
        _set(conn, job_id, total_pages=total)
        _step(conn, job_id, "Extract text", "running", f"0 / {total} pages")
        for f in pdfs:
            conn.execute("UPDATE import_files SET page_count=? WHERE id=?", (counts[f["id"]], f["id"]))

    all_pages: list[dict] = []
    processed = 0
    ocr_used = 0
    for f in pdfs:
        path = storage.local_path(f["storage_key"])
        with db() as conn:
            done = {r["page_number"]: dict(r) for r in conn.execute(
                "SELECT * FROM document_pages WHERE file_id=?", (f["id"],)).fetchall()}
        for page_number in range(1, counts[f["id"]] + 1):
            with db() as conn:
                if _cancelled(conn, job_id):
                    raise Cancelled()
            if page_number in done:
                all_pages.append({"page_number": len(all_pages) + 1,
                                  "text": done[page_number]["text"] or "",
                                  "file_id": f["id"], "file_page": page_number})
                processed += 1
                continue

            result = documents.extract_page(path, page_number)
            if result["method"] == "OCR":
                ocr_used += 1
            with db() as conn:
                conn.execute(
                    """INSERT INTO document_pages
                       (file_id, page_number, text, method, confidence, char_count, needs_review, error)
                       VALUES (?,?,?,?,?,?,?,?)
                       ON CONFLICT (file_id, page_number) DO UPDATE SET
                         text=EXCLUDED.text, method=EXCLUDED.method, confidence=EXCLUDED.confidence,
                         char_count=EXCLUDED.char_count, needs_review=EXCLUDED.needs_review,
                         error=EXCLUDED.error""",
                    (f["id"], page_number, result["text"], result["method"], result["confidence"],
                     len(result["text"]), result["method"] == "NONE" or bool(result["error"]),
                     result["error"]),
                )
                processed += 1
                _set(conn, job_id, processed_pages=processed,
                     status="OCR" if result["method"] == "OCR" else "EXTRACTING")
                _step(conn, job_id, "Extract text", "running", f"{processed} / {total} pages")
                if result["error"]:
                    _warn(conn, job_id, f"{f['filename']} page {page_number}: {result['error']}")
            all_pages.append({"page_number": len(all_pages) + 1, "text": result["text"],
                              "file_id": f["id"], "file_page": page_number})

    unreadable = sum(1 for p in all_pages if not p["text"].strip())
    with db() as conn:
        detail = f"{total} pages read"
        if ocr_used:
            detail += f", {ocr_used} via OCR"
        if unreadable:
            detail += f", {unreadable} unreadable"
            _warn(conn, job_id, f"{unreadable} page(s) could not be read and were left empty.")
        _step(conn, job_id, "Extract text", "done", detail)
    return all_pages


def _detect_structure(job_id: int, pages: list[dict]) -> dict:
    with db() as conn:
        _set(conn, job_id, status="PARSING")
        _step(conn, job_id, "Detect structure", "running")
    outlined = ielts_parser.outline(pages)
    summary = ielts_parser.summarise(outlined)
    with db() as conn:
        if not outlined["sections"]:
            _warn(conn, job_id, "No IELTS tests or sections were recognised in this document.")
            _step(conn, job_id, "Detect structure", "warning", "nothing recognised")
        else:
            by_skill = ", ".join(f"{n} {s.lower()}" for s, n in summary["sections_by_skill"].items())
            _step(conn, job_id, "Detect structure", "done",
                  f"{summary['tests']} test(s): {by_skill}")
    return outlined


def _build_content(job_id: int, material_id: int, outlined: dict, pages: list[dict]) -> None:
    """One AI call per detected section, written straight into the content tables."""
    sections = outlined["sections"]
    with db() as conn:
        _set(conn, job_id, status="STRUCTURING")
        _step(conn, job_id, "Read questions", "running", f"0 / {len(sections)} sections")

    text_by_page = {p["page_number"]: p["text"] for p in pages}
    parsed_count, question_count = 0, 0

    for i, section in enumerate(sections, start=1):
        with db() as conn:
            if _cancelled(conn, job_id):
                raise Cancelled()
        page_texts = [text_by_page.get(n, "") for n in
                      range(section["first_page"], section["last_page"] + 1)]

        parsed, error = None, ""
        if any(t.strip() for t in page_texts):
            try:
                parsed = ielts_parser.extract_section(section, page_texts)
            except AIError as e:
                error = str(e)
        else:
            error = "No readable text on these pages."

        _save_section(material_id, section, parsed, page_texts, error)
        if parsed:
            parsed_count += 1
            question_count += sum(len(g.questions) for g in parsed.groups)
        else:
            with db() as conn:
                _warn(conn, job_id,
                      f"Test {section['test_number']} {section['skill'].title()} "
                      f"{section['title']} needs review: {error}")
        with db() as conn:
            _step(conn, job_id, "Read questions", "running", f"{i} / {len(sections)} sections")

    with db() as conn:
        _step(conn, job_id, "Read questions",
              "done" if parsed_count == len(sections) else "warning",
              f"{question_count} questions from {parsed_count} / {len(sections)} sections")


def _save_section(material_id: int, section: dict, parsed, page_texts: list[str], error: str) -> None:
    """Write (or rewrite) one section and its questions. Idempotent per section."""
    pages_label = (f"{section['first_page']}-{section['last_page']}"
                   if section["last_page"] != section["first_page"] else str(section["first_page"]))
    raw_text = "\n\n".join(t for t in page_texts if t.strip())

    with db() as conn:
        test_id = conn.execute(
            """INSERT INTO ielts_tests (material_id, test_number, title, order_index)
               VALUES (?,?,?,?) ON CONFLICT (material_id, test_number) DO UPDATE
               SET title = ielts_tests.title RETURNING id""",
            (material_id, section["test_number"], f"Test {section['test_number']}",
             section["test_number"]),
        ).fetchone()["id"]

        section_id = conn.execute(
            """INSERT INTO ielts_sections
               (test_id, skill, section_number, title, instructions, body, transcript,
                first_question, last_question, source_pages, confidence, status, order_index)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)
               ON CONFLICT (test_id, skill, section_number) DO UPDATE SET
                 title=EXCLUDED.title, instructions=EXCLUDED.instructions, body=EXCLUDED.body,
                 transcript=EXCLUDED.transcript, first_question=EXCLUDED.first_question,
                 last_question=EXCLUDED.last_question, source_pages=EXCLUDED.source_pages,
                 confidence=EXCLUDED.confidence, status=EXCLUDED.status
               RETURNING id""",
            (test_id, section["skill"], section["section_number"],
             # Our own label ("Section 1", "Passage 2"), not the model's - it
             # tends to echo the prompt header back as a title.
             section["title"],
             (parsed.instructions if parsed else ""),
             # With no parse, the page text is kept verbatim so nothing is lost.
             (parsed.body if parsed else raw_text),
             (parsed.transcript if parsed else ""),
             section["first_question"], section["last_question"], pages_label,
             (parsed.confidence if parsed else 0.0),
             "READY" if parsed and parsed.confidence >= 0.6 else "NEEDS_REVIEW",
             section["section_number"]),
        ).fetchone()["id"]

        # Re-running the pipeline replaces this section's questions rather than
        # appending a second copy of them.
        conn.execute("DELETE FROM ielts_questions WHERE section_id=?", (section_id,))
        conn.execute("DELETE FROM ielts_question_groups WHERE section_id=?", (section_id,))
        if not parsed:
            return

        for order, group in enumerate(parsed.groups):
            # A question with no text, no options and no answer carries nothing:
            # it is the model filling in a stated range ("Questions 1-10") whose
            # questions are not actually printed on these pages. Storing those
            # would inflate the question count with blanks.
            group.questions = [q for q in group.questions
                               if q.question_text.strip() or q.options or q.answer.strip()]
            if not group.questions:
                continue
            numbers = [q.question_number for q in group.questions]
            group_id = conn.execute(
                """INSERT INTO ielts_question_groups
                   (section_id, question_type, instruction, body, options_json, word_limit,
                    first_question, last_question, order_index)
                   VALUES (?,?,?,?,?,?,?,?,?) RETURNING id""",
                (section_id, group.question_type, group.instruction, group.body,
                 json.dumps(group.options),
                 group.word_limit or ielts_parser.word_limit_in(group.instruction),
                 min(numbers) if numbers else None, max(numbers) if numbers else None, order),
            ).fetchone()["id"]

            for q_order, q in enumerate(group.questions):
                conn.execute(
                    """INSERT INTO ielts_questions
                       (section_id, group_id, question_number, question_type, question_text,
                        options_json, answer, word_limit, answer_source, source_page,
                        parser_confidence, status, order_index)
                       VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)
                       ON CONFLICT (section_id, question_number) DO UPDATE SET
                         group_id=EXCLUDED.group_id, question_type=EXCLUDED.question_type,
                         question_text=EXCLUDED.question_text, options_json=EXCLUDED.options_json,
                         answer=EXCLUDED.answer, status=EXCLUDED.status""",
                    (section_id, group_id, q.question_number, q.question_type, q.question_text,
                     json.dumps(q.options or group.options), q.answer,
                     q.word_limit or group.word_limit,
                     # An answer the parser produced is the model's reading of the
                     # page, and models infer answers even when asked not to. Only
                     # the answer-key merge may claim source=DOCUMENT.
                     "AI" if q.answer else "DOCUMENT",
                     section["first_page"],
                     parsed.confidence,
                     "READY" if q.question_text and parsed.confidence >= 0.6 else "NEEDS_REVIEW",
                     q_order),
                )


def _validate(job_id: int, material_id: int, outlined: dict, pages: list[dict]) -> None:
    """Merge any answer key, then count what still needs a human."""
    with db() as conn:
        _set(conn, job_id, status="VALIDATING")
        _step(conn, job_id, "Validate", "running")

    key_text = "\n".join(p["text"] for p in pages if p["page_number"] in outlined["answer_key_pages"])
    answers = ielts_parser.parse_answer_key(key_text) if key_text else {}
    filled = 0

    with db() as conn:
        if answers:
            # Only fill blanks: an answer printed beside the question wins over a
            # key page, and a key entry is never allowed to overwrite it.
            for number, answer in answers.items():
                filled += conn.execute(
                    """UPDATE ielts_questions q SET answer=?, answer_source='DOCUMENT'
                       FROM ielts_sections s JOIN ielts_tests t ON t.id = s.test_id
                       WHERE q.section_id = s.id AND t.material_id=?
                         AND q.question_number=? AND (q.answer IS NULL OR q.answer='')
                       RETURNING q.id""",
                    (answer, material_id, number),
                ).rowcount

        counts = conn.execute(
            """SELECT
                 COUNT(*) FILTER (WHERE q.status='NEEDS_REVIEW') AS needs_review,
                 COUNT(*) FILTER (WHERE q.answer IS NULL OR q.answer='') AS missing_answers,
                 COUNT(*) AS total
               FROM ielts_questions q
               JOIN ielts_sections s ON s.id = q.section_id
               JOIN ielts_tests t ON t.id = s.test_id
               WHERE t.material_id=?""",
            (material_id,),
        ).fetchone()

        detail = f"{counts['total']} questions"
        if answers:
            detail += f", {filled} answers from the answer key"
        if counts["missing_answers"]:
            detail += f", {counts['missing_answers']} without an answer"
            _warn(conn, job_id,
                  f"{counts['missing_answers']} question(s) have no answer yet - add them in the editor "
                  "or they cannot be marked.")
        if counts["needs_review"]:
            _warn(conn, job_id, f"{counts['needs_review']} question(s) need review before practice.")
        _step(conn, job_id, "Validate",
              "warning" if counts["needs_review"] or counts["missing_answers"] else "done", detail)


# --- reading job state -------------------------------------------------------

def job_status(conn, job_id: int, user_id: int) -> dict | None:
    job = conn.execute(
        "SELECT * FROM import_jobs WHERE id=? AND user_id=?", (job_id, user_id)).fetchone()
    if not job:
        return None
    files = conn.execute(
        "SELECT id, kind, filename, size_bytes, page_count FROM import_files WHERE job_id=? ORDER BY id",
        (job_id,)).fetchall()
    total, processed = job["total_pages"] or 0, job["processed_pages"] or 0
    return {
        "id": job["id"],
        "material_id": job["material_id"],
        "status": job["status"],
        "current_step": job["current_step"],
        "steps": json.loads(job["steps_json"] or "[]"),
        "warnings": json.loads(job["warnings_json"] or "[]"),
        "error": job["error"] or "",
        "total_pages": total,
        "processed_pages": processed,
        "progress": round(processed / total, 3) if total else 0.0,
        "files": [dict(f) for f in files],
        "started_at": job["started_at"],
        "completed_at": job["completed_at"],
    }


def _demo():
    """Pure-logic checks. The pipeline itself is exercised by test_import.py,
    which runs it against a real PDF and a real database."""
    from unittest.mock import MagicMock

    # _step appends new steps and updates existing ones in place, so the UI log
    # never grows a second "Extract text" row.
    conn = MagicMock()
    state = {"steps_json": "[]"}
    conn.execute.return_value.fetchone.return_value = state

    def capture(sql, params=None):
        if sql.startswith("UPDATE import_jobs SET steps_json"):
            state["steps_json"] = params[0]
        return MagicMock(fetchone=lambda: state)

    conn.execute.side_effect = capture
    _step(conn, 1, "Extract text", "running", "0 / 10 pages")
    _step(conn, 1, "Extract text", "running", "5 / 10 pages")
    _step(conn, 1, "Validate", "done")
    steps = json.loads(state["steps_json"])
    assert [s["step"] for s in steps] == ["Extract text", "Validate"], steps
    assert steps[0]["detail"] == "5 / 10 pages"
    print("imports self-check OK")


if __name__ == "__main__":
    _demo()

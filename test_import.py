"""End-to-end check of the IELTS import pipeline.

Runs the real pipeline against a real Postgres database and a real PDF that this
script generates (our own text - no copyrighted material anywhere in the repo).
The one thing stubbed out is the AI call, so the test is deterministic and free;
both outcomes are covered - a good parse and a failed parse.

    python test_import.py
"""
import json
import os
import shutil
import tempfile
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

import pymupdf

import storage

storage.STORAGE_DIR = Path(tempfile.mkdtemp(prefix="lexi-test-")).resolve()

import documents  # noqa: E402
import ielts_parser  # noqa: E402
import imports  # noqa: E402
from ai import AIError  # noqa: E402
from db import db, init_db  # noqa: E402

# This test must be free and deterministic, so no model is called: OCR off, and
# the text threshold lowered because the fixture's pages are deliberately short.
# The OCR path itself is covered by documents.py's own self-check.
documents.OCR_PROVIDER = "none"
documents.MIN_TEXT_CHARS = 40

TEST_EMAIL = "import-test@lexi.test"


def build_pdf(path: str) -> None:
    """A miniature two-test IELTS book, written by us for this test."""
    doc = pymupdf.open()

    def page(lines):
        p = doc.new_page()
        y = 80
        for line, size in lines:
            p.insert_text((60, y), line, fontsize=size)
            y += size + 10

    page([("TEST 1", 20), ("LISTENING", 16), ("SECTION 1  Questions 1-10", 13),
          ("Complete the form below.", 11),
          ("Write NO MORE THAN TWO WORDS AND/OR A NUMBER for each answer.", 11),
          ("1  Name of the hall: .............", 11),
          ("2  Booking date: .............", 11)])
    page([("SECTION 2  Questions 11-20", 13),
          ("Choose the correct letter, A, B or C.", 11),
          ("11  The speaker mainly discusses", 11),
          ("A  transport   B  housing   C  recycling", 11)])
    page([("READING PASSAGE 1", 16), ("You should spend about 20 minutes on Questions 1-13.", 11),
          ("The history of the humble teaspoon has been studied surprisingly little.", 11),
          ("Researchers tracked spoons across offices for five months.", 11),
          ("Do the following statements agree with the information in the passage?", 11),
          ("1  Spoons disappeared faster in shared kitchens.  TRUE / FALSE / NOT GIVEN", 11)])
    page([("WRITING TASK 1", 16),
          ("The chart below shows library visits in one city between 2010 and 2020.", 11),
          ("Summarise the information by selecting and reporting the main features.", 11)])
    page([("SPEAKING PART 1", 16), ("Let's talk about where you live.", 11),
          ("Do you live in a house or a flat?", 11)])
    page([("TEST 2", 20), ("LISTENING", 16), ("SECTION 1  Questions 1-10", 13),
          ("Complete the notes below.", 11)])
    page([("AUDIOSCRIPT", 16), ("Test 1, Section 1. You will hear a conversation.", 11)])
    page([("ANSWER KEY", 16), ("Test 1 Listening", 12),
          ("1 Victoria Hall   2 09.30   3 TRUE   4 NOT GIVEN", 11)])
    doc.save(path)
    doc.close()


def fake_parse(section, page_texts):
    """Stand-in for the AI parser: structured output for listening/reading,
    a failure for writing so the error path is exercised too."""
    if section["skill"] == "WRITING":
        raise AIError("model unavailable")
    first = section["first_question"] or 1
    return ielts_parser.ParsedSection(
        title=section["title"],
        instructions="Complete the form below.",
        body="\n".join(page_texts)[:200],
        confidence=0.92,
        groups=[ielts_parser.ParsedGroup(
            question_type="FORM_COMPLETION",
            instruction="Write NO MORE THAN TWO WORDS AND/OR A NUMBER.",
            questions=[
                ielts_parser.ParsedQuestion(question_number=first, question_text="Name of the hall"),
                ielts_parser.ParsedQuestion(question_number=first + 1, question_text="Booking date"),
            ],
        )],
    )


def reset_user(conn) -> int:
    row = conn.execute("SELECT id FROM users WHERE email=?", (TEST_EMAIL,)).fetchone()
    if row:
        conn.execute(
            """DELETE FROM ielts_materials WHERE user_id=?""", (row["id"],))
        conn.execute("DELETE FROM import_jobs WHERE user_id=?", (row["id"],))
        return row["id"]
    return conn.execute(
        "INSERT INTO users (email, password_hash, name) VALUES (?,?,?) RETURNING id",
        (TEST_EMAIL, "x", "Import Test"),
    ).fetchone()["id"]


def main() -> None:
    init_db()
    tmp = Path(tempfile.mkdtemp())
    pdf_path = str(tmp / "mini-ielts.pdf")
    build_pdf(pdf_path)
    pdf_bytes = Path(pdf_path).read_bytes()

    with db() as conn:
        user_id = reset_user(conn)

    # --- a non-PDF upload is refused before anything is stored
    try:
        imports.create_import(user_id, "Bad", "", "", [("notes.txt", b"hello there")])
        raise AssertionError("a text file must be rejected")
    except storage.UploadError as e:
        assert "not a PDF" in str(e), e
    try:
        imports.create_import(user_id, "", "", "", [("a.pdf", pdf_bytes)])
        raise AssertionError("an empty title must be rejected")
    except storage.UploadError:
        pass

    # --- create the import
    created = imports.create_import(
        user_id, "Mini IELTS Practice", "Self-made", "Test fixture", [("mini-ielts.pdf", pdf_bytes)])
    job_id, material_id = created["job_id"], created["material_id"]
    assert created["duplicates"] == []
    assert len(created["files"]) == 1

    # --- run the pipeline with the AI parser stubbed out
    real_extract = ielts_parser.extract_section
    imports.ielts_parser.extract_section = fake_parse
    try:
        imports.run_job(job_id)
    finally:
        imports.ielts_parser.extract_section = real_extract

    with db() as conn:
        status = imports.job_status(conn, job_id, user_id)
    assert status["status"] == "READY", status
    assert status["progress"] == 1.0 and status["processed_pages"] == 8, status
    assert [s["step"] for s in status["steps"]] == imports.STEPS, status["steps"]
    assert all(s["status"] in ("done", "warning") for s in status["steps"]), status["steps"]

    # The writing section failed to parse: that is a warning, not silence.
    assert any("Writing" in w for w in status["warnings"]), status["warnings"]

    # --- pages were stored, so a re-run can resume
    with db() as conn:
        pages = conn.execute(
            """SELECT p.* FROM document_pages p JOIN import_files f ON f.id = p.file_id
               WHERE f.job_id=? ORDER BY p.page_number""", (job_id,)).fetchall()
    assert len(pages) == 8
    assert all(p["method"] == "TEXT" for p in pages), [p["method"] for p in pages]
    assert "SECTION 1" in pages[0]["text"]

    # --- structure
    with db() as conn:
        tests = conn.execute(
            "SELECT * FROM ielts_tests WHERE material_id=? ORDER BY test_number", (material_id,)
        ).fetchall()
        sections = conn.execute(
            """SELECT s.*, t.test_number FROM ielts_sections s
               JOIN ielts_tests t ON t.id = s.test_id WHERE t.material_id=?
               ORDER BY t.test_number, s.skill, s.section_number""", (material_id,)).fetchall()
        questions = conn.execute(
            """SELECT q.* FROM ielts_questions q JOIN ielts_sections s ON s.id = q.section_id
               JOIN ielts_tests t ON t.id = s.test_id WHERE t.material_id=?
               ORDER BY s.id, q.question_number""", (material_id,)).fetchall()

    assert [t["test_number"] for t in tests] == [1, 2], tests
    found = [(s["test_number"], s["skill"], s["section_number"]) for s in sections]
    assert found == [
        (1, "LISTENING", 1), (1, "LISTENING", 2), (1, "READING", 1),
        (1, "SPEAKING", 1), (1, "WRITING", 1), (2, "LISTENING", 1),
    ], found

    listening1 = next(s for s in sections if found[sections.index(s)] == (1, "LISTENING", 1))
    assert listening1["first_question"] == 1 and listening1["last_question"] == 10
    assert listening1["source_pages"] == "1" and listening1["status"] == "READY"
    assert listening1["confidence"] == 0.92

    # The section the parser could not read keeps its page text and is flagged.
    writing = next(s for s in sections if s["skill"] == "WRITING")
    assert writing["status"] == "NEEDS_REVIEW" and "library visits" in writing["body"]

    # Transcript and answer-key pages never became practice sections.
    assert not any(s["source_pages"] in ("7", "8") for s in sections)

    assert len(questions) == 10, len(questions)   # 5 parsed sections x 2 questions
    assert all(q["source_page"] for q in questions), "provenance is required"
    assert all(q["parser_confidence"] == 0.92 for q in questions)

    # --- the answer key filled in the blanks it could
    with db() as conn:
        q1 = conn.execute(
            """SELECT q.answer, q.answer_source FROM ielts_questions q JOIN ielts_sections s ON s.id=q.section_id
               WHERE s.id=? AND q.question_number=1""", (listening1["id"],)).fetchone()
    assert q1["answer"] == "Victoria Hall", q1
    assert q1["answer_source"] == "DOCUMENT", "key answers are the only DOCUMENT answers"

    # --- idempotency: same file again is flagged as a duplicate
    again = imports.create_import(user_id, "Mini IELTS Practice (again)", "", "",
                                  [("mini-ielts.pdf", pdf_bytes)])
    assert again["duplicates"] and again["duplicates"][0]["material"] == "Mini IELTS Practice"

    # --- re-running a finished job must not duplicate content
    imports.ielts_parser.extract_section = fake_parse
    try:
        imports.run_job(job_id)
    finally:
        imports.ielts_parser.extract_section = real_extract
    with db() as conn:
        after = conn.execute(
            """SELECT COUNT(*) c FROM ielts_questions q JOIN ielts_sections s ON s.id=q.section_id
               JOIN ielts_tests t ON t.id = s.test_id WHERE t.material_id=?""",
            (material_id,)).fetchone()["c"]
        sections_after = conn.execute(
            """SELECT COUNT(*) c FROM ielts_sections s JOIN ielts_tests t ON t.id=s.test_id
               WHERE t.material_id=?""", (material_id,)).fetchone()["c"]
    assert after == 10 and sections_after == 6, (after, sections_after)

    # --- cancelling stops the run and says so
    cancelled = imports.create_import(user_id, "Cancel me", "", "", [("mini-ielts.pdf", pdf_bytes)])
    with db() as conn:
        conn.execute("UPDATE import_jobs SET cancel_requested=TRUE WHERE id=?", (cancelled["job_id"],))
    imports.run_job(cancelled["job_id"])
    with db() as conn:
        assert imports.job_status(conn, cancelled["job_id"], user_id)["status"] == "CANCELLED"

    # --- a corrupt PDF fails the job with a readable message, not a crash
    broken = imports.create_import(user_id, "Broken", "", "", [("broken.pdf", b"%PDF-1.4 truncated")])
    imports.run_job(broken["job_id"])
    with db() as conn:
        state = imports.job_status(conn, broken["job_id"], user_id)
    assert state["status"] == "FAILED" and state["error"], state

    # --- privacy: another user cannot read this job
    with db() as conn:
        other = conn.execute(
            "INSERT INTO users (email, password_hash) VALUES (?,?) RETURNING id",
            (f"other-{os.urandom(4).hex()}@lexi.test", "x")).fetchone()["id"]
        assert imports.job_status(conn, job_id, other) is None
        conn.execute("DELETE FROM users WHERE id=?", (other,))

    # --- cleanup
    with db() as conn:
        conn.execute("DELETE FROM ielts_materials WHERE user_id=?", (user_id,))
        conn.execute("DELETE FROM import_jobs WHERE user_id=?", (user_id,))
        conn.execute("DELETE FROM users WHERE id=?", (user_id,))
    shutil.rmtree(storage.STORAGE_DIR, ignore_errors=True)
    shutil.rmtree(tmp, ignore_errors=True)
    print("import pipeline test OK")


if __name__ == "__main__":
    main()

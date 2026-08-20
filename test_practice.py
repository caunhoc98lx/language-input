"""End-to-end check of the practice engine against the real API and database.

Builds a small imported material directly in the database (no AI, no PDF), then
drives it through the HTTP API exactly as the browser does: start a session,
autosave, resume, submit, re-read the results.

    python test_practice.py
"""
import uuid

from dotenv import load_dotenv

load_dotenv()

from fastapi.testclient import TestClient  # noqa: E402

import main  # noqa: E402
from db import db  # noqa: E402


def build_material(user_id: int) -> dict:
    """A one-test material: a reading passage and a listening section."""
    with db() as conn:
        material_id = conn.execute(
            """INSERT INTO ielts_materials (user_id, title, status)
               VALUES (?,?, 'READY') RETURNING id""", (user_id, "Practice Fixture")
        ).fetchone()["id"]
        test_id = conn.execute(
            """INSERT INTO ielts_tests (material_id, test_number, title)
               VALUES (?,1,'Test 1') RETURNING id""", (material_id,)
        ).fetchone()["id"]

        reading_id = conn.execute(
            """INSERT INTO ielts_sections
               (test_id, skill, section_number, title, instructions, body, first_question, last_question)
               VALUES (?, 'READING', 1, 'Passage 1', 'Read the passage.',
                       'Teaspoons vanish from shared kitchens twice as fast.', 1, 3)
               RETURNING id""", (test_id,)
        ).fetchone()["id"]
        listening_id = conn.execute(
            """INSERT INTO ielts_sections
               (test_id, skill, section_number, title, transcript, first_question, last_question)
               VALUES (?, 'LISTENING', 1, 'Section 1', 'You will hear a conversation.', 1, 1)
               RETURNING id""", (test_id,)
        ).fetchone()["id"]

        group_id = conn.execute(
            """INSERT INTO ielts_question_groups
               (section_id, question_type, instruction, options_json, first_question, last_question)
               VALUES (?, 'TRUE_FALSE_NOT_GIVEN', 'Do the statements agree with the passage', '[]', 1, 2)
               RETURNING id""", (reading_id,)
        ).fetchone()["id"]

        q_ids = []
        for number, qtype, text, answer, options, word_limit in [
            (1, "TRUE_FALSE_NOT_GIVEN", "Spoons vanish faster in shared kitchens.", "TRUE", "[]", ""),
            (2, "TRUE_FALSE_NOT_GIVEN", "Every spoon was replaced.", "NOT GIVEN", "[]", ""),
            (3, "SENTENCE_COMPLETION", "The study lasted ...... months.", "five", "[]",
             "NO MORE THAN ONE WORD"),
        ]:
            q_ids.append(conn.execute(
                """INSERT INTO ielts_questions
                   (section_id, group_id, question_number, question_type, question_text, answer,
                    options_json, word_limit, status, source_page)
                   VALUES (?,?,?,?,?,?,?,?, 'READY', 4) RETURNING id""",
                (reading_id, group_id if number <= 2 else None, number, qtype, text, answer,
                 options, word_limit),
            ).fetchone()["id"])

        listening_q = conn.execute(
            """INSERT INTO ielts_questions
               (section_id, question_number, question_type, question_text, answer, options_json,
                status, source_page)
               VALUES (?, 1, 'MULTIPLE_CHOICE', 'The speaker discusses', 'B',
                       '["A transport","B housing","C recycling"]', 'READY', 1) RETURNING id""",
            (listening_id,),
        ).fetchone()["id"]

    return {"material_id": material_id, "test_id": test_id, "reading_id": reading_id,
            "listening_id": listening_id, "questions": q_ids, "listening_q": listening_q}


def main_test() -> None:
    client = TestClient(main.app)
    email = f"practice-{uuid.uuid4().hex[:8]}@lexi.test"
    user = client.post("/api/auth/signup",
                       json={"email": email, "password": "password123", "name": "P"}).json()
    fixture = build_material(user["id"])

    # --- start a session in exam mode
    r = client.post("/api/practice/sessions",
                    json={"section_id": fixture["reading_id"], "mode": "EXAM"})
    assert r.status_code == 200, r.text
    payload = r.json()
    session_id = payload["session"]["id"]
    assert payload["session"]["mode"] == "EXAM"
    assert len(payload["questions"]) == 3
    assert payload["sections"][0]["body"].startswith("Teaspoons")

    # Exam mode must not leak answers or explanations to the client.
    assert all("answer" not in q for q in payload["questions"]), payload["questions"]
    assert payload["answers"] == {}

    # --- autosave, then resume: the answers come back
    q1, q2, q3 = fixture["questions"]
    r = client.patch(f"/api/practice/sessions/{session_id}/answers",
                     json={"answers": {str(q1): "true", str(q2): "TRUE"}})
    assert r.status_code == 200, r.text
    resumed = client.get(f"/api/practice/sessions/{session_id}").json()
    assert resumed["answers"] == {str(q1): "true", str(q2): "TRUE"}
    assert all("answer" not in q for q in resumed["questions"])

    # Starting again resumes the same session instead of losing the answers.
    again = client.post("/api/practice/sessions",
                        json={"section_id": fixture["reading_id"], "mode": "EXAM"}).json()
    assert again["session"]["id"] == session_id
    assert again["answers"] == {str(q1): "true", str(q2): "TRUE"}

    # An answer for a question outside the session is ignored, not stored.
    client.patch(f"/api/practice/sessions/{session_id}/answers",
                 json={"answers": {str(fixture["listening_q"]): "B"}})
    assert str(fixture["listening_q"]) not in client.get(
        f"/api/practice/sessions/{session_id}").json()["answers"]

    # --- submit: q1 right, q2 wrong, q3 over the word limit
    r = client.post(f"/api/practice/sessions/{session_id}/submit",
                    json={"answers": {str(q3): "about five"}, "duration_sec": 240})
    assert r.status_code == 200, r.text
    done = r.json()
    result = done["result"]
    assert result["score"] == 1 and result["total"] == 3, result
    assert result["band_is_estimate"] is True
    by_number = {r["question_number"]: r for r in result["results"]}
    assert by_number[1]["correct"] and not by_number[2]["correct"]
    assert not by_number[3]["correct"], "over the word limit must be marked wrong"
    assert by_number[3]["given"] == "about five"
    assert done["session"]["status"] == "SUBMITTED"

    # After submitting, answers and explanations are revealed.
    assert all("answer" in q for q in done["questions"])
    types = {t["type"]: t for t in result["by_type"]}
    assert types["TRUE_FALSE_NOT_GIVEN"]["attempts"] == 2 and types["TRUE_FALSE_NOT_GIVEN"]["correct"] == 1

    # --- results survive a reload, and re-submitting is a no-op, not a double count
    reread = client.get(f"/api/practice/sessions/{session_id}").json()
    assert reread["result"]["score"] == 1 and reread["result"]["duration_sec"] == 240
    resubmit = client.post(f"/api/practice/sessions/{session_id}/submit", json={"answers": {}}).json()
    assert resubmit["result"]["score"] == 1
    assert client.patch(f"/api/practice/sessions/{session_id}/answers",
                        json={"answers": {str(q1): "false"}}).status_code == 400

    # --- learning mode reveals the transcript only after submitting
    lr = client.post("/api/practice/sessions",
                     json={"section_id": fixture["listening_id"], "mode": "LEARNING"}).json()
    assert lr["sections"][0]["transcript"] == "", "no transcript during the attempt"
    lid = lr["session"]["id"]
    done_l = client.post(f"/api/practice/sessions/{lid}/submit",
                         json={"answers": {str(fixture["listening_q"]): "housing"}}).json()
    assert done_l["result"]["score"] == 1, "option text must mark the same as its letter"
    assert done_l["sections"][0]["transcript"].startswith("You will hear")
    assert done_l["result"]["band"] > 0

    # --- a whole-skill session covers every section of that skill
    whole = client.post("/api/practice/sessions",
                        json={"test_id": fixture["test_id"], "skill": "READING", "mode": "EXAM"}).json()
    assert len(whole["questions"]) == 3 and whole["session"]["section_id"] is None

    # --- history and dashboard see the results
    history = client.get("/api/practice/sessions").json()["sessions"]
    assert len(history) >= 2 and history[0]["material_title"] == "Practice Fixture"
    dash = client.get("/api/dashboard").json()
    assert dash["bands"]["skills"].get("reading") is not None, dash["bands"]
    assert any(t["type"] == "TRUE_FALSE_NOT_GIVEN" for t in dash["question_type_accuracy"])

    # --- privacy: another account cannot touch this session
    other = f"other-{uuid.uuid4().hex[:8]}@lexi.test"
    client2 = TestClient(main.app)
    client2.post("/api/auth/signup", json={"email": other, "password": "password123"})
    assert client2.get(f"/api/practice/sessions/{session_id}").status_code == 404
    assert client2.post(f"/api/practice/sessions/{session_id}/submit", json={}).status_code == 404
    assert client2.post("/api/practice/sessions",
                        json={"section_id": fixture["reading_id"]}).status_code == 404

    # --- cleanup
    with db() as conn:
        for row in conn.execute("SELECT id FROM users WHERE email IN (?,?)", (email, other)).fetchall():
            conn.execute("DELETE FROM practice_sessions WHERE user_id=?", (row["id"],))
            conn.execute("DELETE FROM ielts_materials WHERE user_id=?", (row["id"],))
            conn.execute("DELETE FROM users WHERE id=?", (row["id"],))
    print("practice engine test OK")


if __name__ == "__main__":
    main_test()

"""End-to-end check of the adaptive layer: weaknesses -> targeted practice ->
progress analytics.

    python test_adaptive.py
"""
import uuid

from dotenv import load_dotenv

load_dotenv()

from fastapi.testclient import TestClient  # noqa: E402

import main  # noqa: E402
from db import db, init_db  # noqa: E402
from test_practice import build_material  # noqa: E402


def main_test() -> None:
    init_db()
    client = TestClient(main.app)
    email = f"adaptive-{uuid.uuid4().hex[:8]}@lexi.test"
    user = client.post("/api/auth/signup", json={"email": email, "password": "password123"}).json()
    fx = build_material(user["id"])
    q1, q2, q3 = fx["questions"]

    # With no history, targeted practice has nothing to offer and says so.
    empty = client.post("/api/practice/targeted", json={"source": "MISTAKES"})
    assert empty.status_code == 400 and "no unresolved mistakes" in empty.json()["detail"].lower()

    # --- fail two questions in a normal session
    session = client.post("/api/practice/sessions",
                          json={"section_id": fx["reading_id"], "mode": "EXAM"}).json()
    client.post(f"/api/practice/sessions/{session['session']['id']}/submit",
                json={"answers": {str(q1): "TRUE", str(q2): "TRUE", str(q3): "wrong"}})

    weaknesses = client.get("/api/practice/weaknesses").json()
    assert weaknesses["unresolved_mistakes"] == 2, weaknesses
    assert "TRUE_FALSE_NOT_GIVEN" in weaknesses["available_types"]

    # --- redo my mistakes builds a session of exactly those questions
    redo = client.post("/api/practice/targeted", json={"source": "MISTAKES", "limit": 10}).json()
    assert sorted(q["id"] for q in redo["questions"]) == sorted([q2, q3]), redo["questions"]
    assert redo["session"]["label"] == "Redo my mistakes"
    assert all("answer" not in q for q in redo["questions"]), "answers stay server-side"
    # It carries the passage its questions came from.
    assert redo["sections"][0]["body"].startswith("Teaspoons")

    # Answering them correctly clears them from the mistake pool.
    client.post(f"/api/practice/sessions/{redo['session']['id']}/submit",
                json={"answers": {str(q2): "NOT GIVEN", str(q3): "five"}})
    assert client.get("/api/practice/weaknesses").json()["unresolved_mistakes"] == 0

    # --- practice by question type
    typed = client.post("/api/practice/targeted",
                        json={"source": "TYPE", "question_type": "TRUE_FALSE_NOT_GIVEN",
                              "limit": 5}).json()
    assert len(typed["questions"]) == 2
    assert all(q["question_type"] == "TRUE_FALSE_NOT_GIVEN" for q in typed["questions"])
    assert "Matching" not in typed["session"]["label"]
    bad_type = client.post("/api/practice/targeted",
                           json={"source": "TYPE", "question_type": "NOT_A_TYPE"})
    assert bad_type.status_code == 400
    none_left = client.post("/api/practice/targeted",
                            json={"source": "TYPE", "question_type": "MATCHING_HEADINGS"})
    assert none_left.status_code == 400

    # Autosave on a targeted session only accepts its own questions.
    sid = typed["session"]["id"]
    client.patch(f"/api/practice/sessions/{sid}/answers", json={"answers": {str(q2): "TRUE"}})
    saved = client.get(f"/api/practice/sessions/{sid}").json()["answers"]
    assert saved == {str(q2): "TRUE"}, saved

    # --- progress analytics see all of it
    progress = client.get("/api/progress").json()
    assert progress["tests_completed"] >= 2
    assert progress["bands"]["skills"].get("reading") is not None
    assert len(progress["history"]) >= 2
    assert progress["activity"], "study activity per day must be recorded"
    assert any(t["type"] == "TRUE_FALSE_NOT_GIVEN" for t in progress["question_type_accuracy"])
    assert progress["vocabulary"]["total"] == 0 and progress["vocabulary"]["retention"] is None

    # --- privacy
    stranger = TestClient(main.app)
    stranger.post("/api/auth/signup",
                  json={"email": f"a-{uuid.uuid4().hex[:6]}@lexi.test", "password": "password123"})
    assert stranger.get("/api/practice/weaknesses").json()["unresolved_mistakes"] == 0
    assert stranger.get("/api/progress").json()["tests_completed"] == 0
    assert stranger.get(f"/api/practice/sessions/{sid}").status_code == 404

    # --- cleanup
    with db() as conn:
        for row in conn.execute("SELECT id FROM users WHERE email=?", (email,)).fetchall():
            conn.execute("DELETE FROM practice_sessions WHERE user_id=?", (row["id"],))
            conn.execute("DELETE FROM ielts_materials WHERE user_id=?", (row["id"],))
            conn.execute("DELETE FROM users WHERE id=?", (row["id"],))
        conn.execute("DELETE FROM users WHERE email LIKE 'a-%@lexi.test'")
    print("adaptive + progress test OK")


if __name__ == "__main__":
    main_test()

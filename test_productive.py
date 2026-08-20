"""End-to-end check of writing and speaking submissions.

The examiner and transcription calls are stubbed, so this is free and
deterministic; what it proves is the plumbing - prompts come from imported
material, submissions are stored with per-criterion bands, grammar mistakes are
filed by topic, recordings stay private, and the dashboard picks the bands up.

    python test_productive.py
"""
import tempfile
import uuid
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

import storage  # noqa: E402

storage.STORAGE_DIR = Path(tempfile.mkdtemp(prefix="lexi-prod-")).resolve()

from fastapi.testclient import TestClient  # noqa: E402

import ai  # noqa: E402
import main  # noqa: E402
from db import db, init_db  # noqa: E402


def fake_writing_feedback(prompt: str, essay: str):
    return ai.WritingFeedback(
        band_overall=6.5, task_response=6.0, coherence_cohesion=7.0,
        lexical_resource=6.5, grammatical_range=6.0,
        summary="Bài viết rõ ràng nhưng còn lỗi ngữ pháp.",
        strengths=["Clear position"], weaknesses=["Subject-verb agreement"],
        corrections=[ai.Correction(
            original="People is becoming more aware.",
            improved="People are becoming more aware.",
            why="'People' là danh từ số nhiều.",
            error_type="subject-verb agreement", grammar_topic="Subject-Verb Agreement")],
        suggested_vocabulary=[ai.VocabItem(word="mitigate", translation="giảm thiểu")],
    )


def fake_speaking_feedback(prompt: str, transcript: str):
    return ai.SpeakingFeedback(
        band_overall=6.0, fluency_coherence=6.0, lexical_resource=6.0,
        grammatical_range=5.5, pronunciation=6.5,
        summary="Nói khá trôi chảy.", fillers=["like", "you know"],
        overused_words=["good"],
        corrections=[ai.Correction(
            original="I go there last year.", improved="I went there last year.",
            why="Quá khứ đơn.", error_type="tense", grammar_topic="Tenses")],
    )


def build_prompts(user_id: int) -> dict:
    with db() as conn:
        material_id = conn.execute(
            "INSERT INTO ielts_materials (user_id, title, status) VALUES (?,?,'READY') RETURNING id",
            (user_id, "Productive Fixture")).fetchone()["id"]
        test_id = conn.execute(
            "INSERT INTO ielts_tests (material_id, test_number, title) VALUES (?,1,'Test 1') RETURNING id",
            (material_id,)).fetchone()["id"]
        writing = conn.execute(
            """INSERT INTO ielts_sections (test_id, skill, section_number, title, instructions, body)
               VALUES (?, 'WRITING', 2, 'Task 2', 'You should spend about 40 minutes.',
                       'Some people think technology makes life complex. Discuss.') RETURNING id""",
            (test_id,)).fetchone()["id"]
        speaking = conn.execute(
            """INSERT INTO ielts_sections (test_id, skill, section_number, title, instructions, body)
               VALUES (?, 'SPEAKING', 2, 'Part 2', 'Speak for one to two minutes.',
                       'Describe a book you enjoyed reading.') RETURNING id""",
            (test_id,)).fetchone()["id"]
    return {"material_id": material_id, "writing": writing, "speaking": speaking}


def main_test() -> None:
    init_db()
    client = TestClient(main.app)
    email = f"prod-{uuid.uuid4().hex[:8]}@lexi.test"
    user = client.post("/api/auth/signup", json={"email": email, "password": "password123"}).json()
    fx = build_prompts(user["id"])

    # --- prompts come from imported material, per skill
    prompts = client.get("/api/writing/prompts").json()["prompts"]
    assert [p["id"] for p in prompts] == [fx["writing"]], prompts
    assert prompts[0]["attempts"] == 0
    speaking_prompts = client.get("/api/speaking/prompts").json()["prompts"]
    assert [p["id"] for p in speaking_prompts] == [fx["speaking"]]

    # --- a too-short essay is refused before any model is called
    short = client.post("/api/writing/submissions",
                        json={"section_id": fx["writing"], "response": "Too short."})
    assert short.status_code == 400 and "40 words" in short.json()["detail"]

    # --- submit an essay
    real_grade = ai.grade_writing
    main.ai.grade_writing = fake_writing_feedback
    try:
        essay = " ".join(["Technology has changed daily life in many ways."] * 12)
        r = client.post("/api/writing/submissions",
                        json={"section_id": fx["writing"], "response": essay, "duration_sec": 1500})
    finally:
        main.ai.grade_writing = real_grade
    assert r.status_code == 200, r.text
    submission = r.json()
    assert submission["band"] == 6.5 and submission["kind"] == "WRITING"
    assert submission["criteria"] == {"task_response": 6.0, "coherence_cohesion": 7.0,
                                      "lexical_resource": 6.5, "grammatical_range": 6.0}
    assert submission["task_label"] == "Task 2"
    assert submission["word_count"] == len(essay.split())
    assert "Some people think technology" in submission["prompt"]

    # --- the grammar mistake was filed by topic, ready for targeted practice
    grammar = client.get("/api/grammar/mistakes").json()
    assert grammar["topics"][0]["topic"] == "Subject-Verb Agreement"
    assert grammar["topics"][0]["count"] == 1
    assert grammar["mistakes"][0]["correction"] == "People are becoming more aware."

    # --- the attempt shows on the prompt list, and the submission is re-readable
    assert client.get("/api/writing/prompts").json()["prompts"][0]["attempts"] == 1
    detail = client.get(f"/api/submissions/{submission['id']}").json()
    assert detail["feedback"]["summary"].startswith("Bài viết")
    assert detail["has_audio"] is False

    # --- speaking: a recording is transcribed, then marked
    real_transcribe, real_speak = ai.transcribe_audio, ai.grade_speaking
    main.ai.transcribe_audio = lambda path, filename="a.webm": "I go there last year and it was good."
    main.ai.grade_speaking = fake_speaking_feedback
    try:
        r = client.post("/api/speaking/submissions",
                        data={"section_id": str(fx["speaking"]), "duration_sec": "95"},
                        files={"audio": ("recording.webm", b"\x1aE\xdf\xa3fake-webm", "audio/webm")})
    finally:
        main.ai.transcribe_audio, main.ai.grade_speaking = real_transcribe, real_speak
    assert r.status_code == 200, r.text
    spoken = r.json()
    assert spoken["kind"] == "SPEAKING" and spoken["band"] == 6.0
    assert spoken["response"].startswith("I go there")
    assert spoken["has_audio"] is True
    assert spoken["criteria"]["pronunciation"] == 6.5
    assert spoken["task_label"] == "Part 2"

    # A recording with no audio attached is refused.
    assert client.post("/api/speaking/submissions", data={"prompt": "x"}).status_code == 400

    # --- the recording plays back for its owner only
    assert client.get(f"/api/submissions/{spoken['id']}/audio").status_code == 200
    stranger = TestClient(main.app)
    stranger.post("/api/auth/signup",
                  json={"email": f"s-{uuid.uuid4().hex[:6]}@lexi.test", "password": "password123"})
    assert stranger.get(f"/api/submissions/{spoken['id']}/audio").status_code == 404
    assert stranger.get(f"/api/submissions/{submission['id']}").status_code == 404
    assert stranger.get("/api/grammar/mistakes").json()["mistakes"] == []
    assert stranger.get("/api/writing/prompts").json()["prompts"] == []

    # --- both skills reach the dashboard band estimate
    listed = client.get("/api/submissions").json()["submissions"]
    assert len(listed) == 2

    # --- cleanup
    with db() as conn:
        for row in conn.execute("SELECT id FROM users WHERE email=?", (email,)).fetchall():
            conn.execute("DELETE FROM grammar_mistakes WHERE user_id=?", (row["id"],))
            conn.execute("DELETE FROM productive_submissions WHERE user_id=?", (row["id"],))
            conn.execute("DELETE FROM ielts_materials WHERE user_id=?", (row["id"],))
            conn.execute("DELETE FROM users WHERE id=?", (row["id"],))
        conn.execute("DELETE FROM users WHERE email LIKE 's-%@lexi.test'")
    print("writing + speaking test OK")


if __name__ == "__main__":
    main_test()

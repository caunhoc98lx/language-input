"""End-to-end check of audio upload, matching, transcripts and dictation.

Uses a real (tiny, generated) WAV file and the real API. No model calls.

    python test_audio.py
"""
import struct
import tempfile
import uuid
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

import storage  # noqa: E402

storage.STORAGE_DIR = Path(tempfile.mkdtemp(prefix="lexi-audio-")).resolve()

from fastapi.testclient import TestClient  # noqa: E402

import main  # noqa: E402
from db import db  # noqa: E402


def wav_bytes(seconds: float = 0.2) -> bytes:
    """A real, valid WAV file - silence, but with a correct header."""
    rate, frames = 8000, int(8000 * seconds)
    data = b"\x00\x00" * frames
    return (b"RIFF" + struct.pack("<I", 36 + len(data)) + b"WAVEfmt " +
            struct.pack("<IHHIIHH", 16, 1, 1, rate, rate * 2, 2, 16) +
            b"data" + struct.pack("<I", len(data)) + data)


def build_listening_material(user_id: int) -> dict:
    with db() as conn:
        material_id = conn.execute(
            "INSERT INTO ielts_materials (user_id, title, status) VALUES (?,?,'READY') RETURNING id",
            (user_id, "Audio Fixture"),
        ).fetchone()["id"]
        test_id = conn.execute(
            "INSERT INTO ielts_tests (material_id, test_number, title) VALUES (?,1,'Test 1') RETURNING id",
            (material_id,),
        ).fetchone()["id"]
        sections = [
            conn.execute(
                """INSERT INTO ielts_sections (test_id, skill, section_number, title)
                   VALUES (?, 'LISTENING', ?, ?) RETURNING id""",
                (test_id, n, f"Section {n}"),
            ).fetchone()["id"]
            for n in range(1, 5)
        ]
    return {"material_id": material_id, "test_id": test_id, "sections": sections}


def main_test() -> None:
    client = TestClient(main.app)
    email = f"audio-{uuid.uuid4().hex[:8]}@lexi.test"
    user = client.post("/api/auth/signup",
                       json={"email": email, "password": "password123"}).json()
    fx = build_listening_material(user["id"])
    mid = fx["material_id"]

    # --- upload four audio files with recognisable names
    audio = wav_bytes()
    files = [("files", (f"Test1_Section{n}.wav", audio, "audio/wav")) for n in range(1, 5)]
    r = client.post(f"/api/library/materials/{mid}/audio", files=files)
    assert r.status_code == 200, r.text
    uploaded = r.json()["files"]
    assert len(uploaded) == 4

    # A PDF is not audio, and is refused here.
    bad = client.post(f"/api/library/materials/{mid}/audio",
                      files=[("files", ("notes.pdf", b"%PDF-1.7 hello", "application/pdf"))])
    assert bad.status_code == 400 and "not an audio file" in bad.json()["detail"]

    # --- matching proposes the right file for every section, confidently
    state = client.get(f"/api/library/materials/{mid}/audio").json()
    assert state["summary"]["total"] == 4
    assert all(s["confidence"] >= 0.9 for s in state["suggestions"]), state["suggestions"]

    applied = client.post(f"/api/library/materials/{mid}/audio/match").json()
    assert applied["applied"] == 4, applied
    linked = client.get(f"/api/library/materials/{mid}/audio").json()
    assert all(s["audio_file_id"] for s in linked["sections"])
    # Every section got a different file.
    assert len({s["audio_file_id"] for s in linked["sections"]}) == 4

    # --- a section's audio can be corrected by hand, with a segment
    section_id = fx["sections"][0]
    other_file = uploaded[3]["id"]
    r = client.patch(f"/api/library/sections/{section_id}/audio",
                     json={"file_id": other_file, "start_sec": 0, "end_sec": 0.1})
    assert r.status_code == 200 and r.json()["audio_file_id"] == other_file
    assert r.json()["audio_end_sec"] == 0.1
    # An invalid segment is rejected.
    assert client.patch(f"/api/library/sections/{section_id}/audio",
                        json={"file_id": other_file, "start_sec": 5, "end_sec": 1}).status_code == 400
    # Unlinking is allowed.
    assert client.patch(f"/api/library/sections/{section_id}/audio",
                        json={"file_id": None}).json()["audio_file_id"] is None

    # --- the private audio file streams back to its owner, and nobody else
    file_id = uploaded[0]["id"]
    raw = client.get(f"/api/library/files/{file_id}/raw")
    assert raw.status_code == 200 and raw.content[:4] == b"RIFF"
    stranger = TestClient(main.app)
    stranger.post("/api/auth/signup", json={"email": f"x-{uuid.uuid4().hex[:6]}@lexi.test",
                                            "password": "password123"})
    assert stranger.get(f"/api/library/files/{file_id}/raw").status_code == 404
    assert stranger.get(f"/api/library/materials/{mid}/audio").status_code == 404

    # --- dictation needs a transcript; without one the section is not offered
    assert client.get("/api/dictation/sections").json()["sections"] == []
    transcript = "The government has introduced a new policy for the city library."
    s2 = fx["sections"][1]
    assert client.patch(f"/api/library/sections/{s2}/transcript",
                        json={"transcript": transcript}).status_code == 200
    options = client.get("/api/dictation/sections").json()["sections"]
    assert [o["id"] for o in options] == [s2], options
    assert options[0]["words"] == 11

    # The dictation payload gives audio but never the transcript text.
    target = client.get(f"/api/dictation/sections/{s2}").json()
    assert target["audio"]["file_id"] and "transcript" not in target

    # --- marking a dictation attempt
    check = client.post(f"/api/dictation/sections/{s2}/check",
                        json={"typed": "The government introduced a new policy for the city library"}).json()
    assert check["missing"] == 1 and check["correct"] == 10
    assert [w["word"] for w in check["words"] if w["status"] == "missing"] == ["has"]
    perfect = client.post(f"/api/dictation/sections/{s2}/check", json={"typed": transcript}).json()
    assert perfect["accuracy"] == 1.0
    assert stranger.post(f"/api/dictation/sections/{s2}/check", json={"typed": "x"}).status_code == 404

    # --- practice picks the audio up automatically
    with db() as conn:
        conn.execute(
            """INSERT INTO ielts_questions (section_id, question_number, question_type,
                 question_text, answer, status) VALUES (?,1,'SHORT_ANSWER','Where?','library','READY')""",
            (s2,),
        )
    session = client.post("/api/practice/sessions", json={"section_id": s2, "mode": "LEARNING"}).json()
    assert session["sections"][0]["audio"]["file_id"], session["sections"][0]
    assert session["sections"][0]["transcript"] == "", "transcript stays hidden until submit"
    done = client.post(f"/api/practice/sessions/{session['session']['id']}/submit",
                       json={"answers": {str(session["questions"][0]["id"]): "library"}}).json()
    assert done["result"]["score"] == 1
    assert done["sections"][0]["transcript"] == transcript

    # --- cleanup
    with db() as conn:
        for row in conn.execute("SELECT id FROM users WHERE email=?", (email,)).fetchall():
            conn.execute("DELETE FROM practice_sessions WHERE user_id=?", (row["id"],))
            conn.execute("DELETE FROM ielts_materials WHERE user_id=?", (row["id"],))
            conn.execute("DELETE FROM import_files WHERE user_id=?", (row["id"],))
            conn.execute("DELETE FROM users WHERE id=?", (row["id"],))
        conn.execute("DELETE FROM users WHERE email LIKE 'x-%@lexi.test'")
    print("audio + dictation test OK")


if __name__ == "__main__":
    main_test()

"use client";

import { useEffect, useRef, useState } from "react";
import Link from "next/link";
import { useParams, useRouter } from "next/navigation";
import Protected from "@/components/Protected";
import { api } from "@/lib/api";
import { formatDuration } from "@/lib/practice";

interface Prompt {
  id: number;
  title: string;
  instructions: string;
  body: string;
  section_number: number;
  test_number: number;
  material_title: string;
}

const API_URL = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";
// Part 2 gives a minute to prepare and up to two to speak; the others are shorter.
const SPEAK_LIMIT_SEC = 180;

function RecorderContent({ sectionId }: { sectionId: number }) {
  const router = useRouter();
  const [prompt, setPrompt] = useState<Prompt | null>(null);
  const [recording, setRecording] = useState(false);
  const [seconds, setSeconds] = useState(0);
  const [blob, setBlob] = useState<Blob | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const recorderRef = useRef<MediaRecorder | null>(null);
  const chunksRef = useRef<Blob[]>([]);

  useEffect(() => {
    api
      .get("/api/speaking/prompts")
      .then((d) => {
        const found = d.prompts.find((p: Prompt) => p.id === sectionId);
        if (!found) setError("That speaking prompt was not found.");
        setPrompt(found ?? null);
      })
      .catch((e) => setError(e.message));
  }, [sectionId]);

  useEffect(() => {
    if (!recording) return;
    const t = setInterval(() => {
      setSeconds((s) => {
        if (s + 1 >= SPEAK_LIMIT_SEC) recorderRef.current?.stop();
        return s + 1;
      });
    }, 1000);
    return () => clearInterval(t);
  }, [recording]);

  async function start() {
    setError("");
    setBlob(null);
    setSeconds(0);
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      const recorder = new MediaRecorder(stream);
      chunksRef.current = [];
      recorder.ondataavailable = (e) => chunksRef.current.push(e.data);
      recorder.onstop = () => {
        setBlob(new Blob(chunksRef.current, { type: recorder.mimeType || "audio/webm" }));
        setRecording(false);
        stream.getTracks().forEach((t) => t.stop());
      };
      recorderRef.current = recorder;
      recorder.start();
      setRecording(true);
    } catch {
      setError("Microphone access was refused, so nothing can be recorded.");
    }
  }

  async function submit() {
    if (!blob) return;
    setBusy(true);
    setError("");
    const form = new FormData();
    form.append("section_id", String(sectionId));
    form.append("duration_sec", String(seconds));
    form.append("audio", blob, "recording.webm");
    try {
      const res = await fetch(`${API_URL}/api/speaking/submissions`, {
        method: "POST",
        credentials: "include",
        body: form,
      });
      const body = await res.json().catch(() => ({}));
      if (!res.ok) throw new Error(body.detail || "Could not submit the recording.");
      router.push(`/writing/submissions/${body.id}`);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Could not submit.");
      setBusy(false);
    }
  }

  if (error && !prompt) return <div className="card empty-state"><h2>Not found</h2><p>{error}</p></div>;
  if (!prompt) return null;

  return (
    <>
      <div className="toolbar">
        <div>
          <h1>{prompt.title}</h1>
          <p className="subtitle" style={{ margin: 0 }}>
            {prompt.material_title} · Test {prompt.test_number}
          </p>
        </div>
        <div className="spacer" />
        <Link href="/speaking" className="btn secondary small">
          Back
        </Link>
      </div>

      <div className="card" style={{ marginBottom: 16 }}>
        {prompt.instructions && <p className="subtitle">{prompt.instructions}</p>}
        <div className="passage-body">{prompt.body}</div>
      </div>

      <div className="card recorder">
        <button
          className={`record-btn ${recording ? "recording" : ""}`}
          onClick={() => (recording ? recorderRef.current?.stop() : start())}
          disabled={busy}
        >
          {recording ? "■" : "●"}
        </button>
        <div style={{ flex: 1 }}>
          <div className="timer" style={{ display: "inline-block" }}>{formatDuration(seconds)}</div>
          <p className="subtitle" style={{ margin: "6px 0 0" }}>
            {recording
              ? "Recording — press stop when you finish."
              : blob
                ? "Listen back, record again, or send it for marking."
                : `Press record and answer out loud. Up to ${SPEAK_LIMIT_SEC / 60} minutes.`}
          </p>
        </div>
      </div>

      {blob && !recording && (
        <div className="card" style={{ marginTop: 16 }}>
          <audio controls src={URL.createObjectURL(blob)} style={{ width: "100%" }} />
          <div style={{ display: "flex", gap: 10, marginTop: 12 }}>
            <button className="btn" onClick={submit} disabled={busy}>
              {busy ? "Transcribing and marking…" : "Submit for marking"}
            </button>
            <button className="btn secondary" onClick={start} disabled={busy}>
              Record again
            </button>
          </div>
          {busy && (
            <p className="subtitle" style={{ margin: "10px 0 0" }}>
              This takes a moment: the recording is transcribed, then marked.
            </p>
          )}
        </div>
      )}

      {error && <div className="error">{error}</div>}
    </>
  );
}

export default function SpeakingRecorderPage() {
  const params = useParams<{ id: string }>();
  return <Protected>{() => <RecorderContent sectionId={Number(params.id)} />}</Protected>;
}

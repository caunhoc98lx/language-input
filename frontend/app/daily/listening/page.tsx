"use client";

import { useEffect, useRef, useState } from "react";
import Link from "next/link";
import Countdown from "@/components/Countdown";
import Protected from "@/components/Protected";
import PracticeQuestions from "@/components/PracticeQuestions";
import SaveVocabList from "@/components/SaveVocabList";
import { api, ApiError } from "@/lib/api";
import { bandColor, splitVocabByMistakes } from "@/lib/daily";
import type { DailyAttempt, DailyTask } from "@/lib/daily";

// Scaled down from the real ~30-minute section for a single 6-question recording.
const LISTENING_SECONDS = 12 * 60;

// ponytail: browser speech synthesis, not generated audio files. Free, offline,
// and instant; swap in OpenAI TTS here if the robotic voice starts costing marks.
function speakable(transcript: string): string {
  return transcript.replace(/^([A-Z][A-Z ]{1,20}):/gm, "$1,");
}

function ListeningContent() {
  const [task, setTask] = useState<DailyTask | null>(null);
  const [attempt, setAttempt] = useState<DailyAttempt | null>(null);
  const [answers, setAnswers] = useState<string[]>([]);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [playing, setPlaying] = useState(false);
  const [plays, setPlays] = useState(0);
  const [showTranscript, setShowTranscript] = useState(false);
  const utterRef = useRef<SpeechSynthesisUtterance | null>(null);
  const startedAtRef = useRef(Date.now());

  useEffect(() => {
    api
      .get("/api/daily/listening")
      .then((data) => {
        setTask(data.task);
        setAttempt(data.attempt);
        if (data.attempt) {
          setAnswers(data.attempt.answers);
          setShowTranscript(true);
        }
      })
      .finally(() => setLoading(false));
  }, []);

  // Never leave audio running when the learner navigates away.
  useEffect(() => () => window.speechSynthesis?.cancel(), []);

  function play() {
    if (!task?.content.transcript) return;
    window.speechSynthesis.cancel();
    const u = new SpeechSynthesisUtterance(speakable(task.content.transcript));
    u.lang = "en-GB";
    u.rate = 0.95;
    u.onend = () => setPlaying(false);
    u.onerror = () => setPlaying(false);
    utterRef.current = u;
    setPlaying(true);
    setPlays((n) => n + 1);
    window.speechSynthesis.speak(u);
  }

  function stop() {
    window.speechSynthesis.cancel();
    setPlaying(false);
  }

  async function generate() {
    setBusy(true);
    setError(null);
    try {
      const data = await api.post("/api/daily/listening/generate");
      setTask(data.task);
      setAttempt(data.attempt);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Could not generate today's listening.");
    } finally {
      setBusy(false);
    }
  }

  async function submit() {
    if (busy || attempt) return;
    stop();
    setBusy(true);
    setError(null);
    try {
      const duration_sec = Math.round((Date.now() - startedAtRef.current) / 1000);
      const data = await api.post("/api/daily/listening/submit", { answers, duration_sec });
      setAttempt(data.attempt);
      setTask((prev) => (prev ? { ...prev, content: data.content } : prev));
      setShowTranscript(true);
      window.scrollTo({ top: 0, behavior: "smooth" });
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Could not submit.");
    } finally {
      setBusy(false);
    }
  }

  if (loading) return null;

  if (!task) {
    return (
      <>
        <Header />
        <div className="card empty-state">
          <h2>Today&apos;s listening isn&apos;t ready yet</h2>
          <p>Generate an IELTS-style talk or conversation with 6 questions.</p>
          {error && <div className="error">{error}</div>}
          <button className="btn" style={{ marginTop: 12 }} onClick={generate} disabled={busy}>
            {busy ? "Writing your script..." : "Generate today's listening"}
          </button>
        </div>
      </>
    );
  }

  const questions = task.content.questions || [];
  const results = attempt?.feedback?.results;
  const { missed, extra } = splitVocabByMistakes(task.content, results);

  return (
    <>
      <Header />

      {attempt && (
        <div className="card" style={{ marginBottom: 24, display: "flex", alignItems: "center", gap: 20 }}>
          <div>
            <div style={{ fontSize: "2rem", fontWeight: 700, color: bandColor(attempt.band) }}>
              {attempt.band?.toFixed(1)}
            </div>
            <div className="subtitle" style={{ margin: 0 }}>estimated band</div>
          </div>
          <div>
            <div style={{ fontSize: "2rem", fontWeight: 700 }}>{attempt.score}/{attempt.total}</div>
            <div className="subtitle" style={{ margin: 0 }}>correct</div>
          </div>
          <div style={{ flex: 1 }} />
          <Link href="/daily" className="btn secondary">Back to today</Link>
        </div>
      )}

      {!attempt && (
        <div className="practice-bar">
          <span className="subtitle" style={{ margin: 0 }}>Time limit for this section</span>
          <div className="spacer" />
          <Countdown seconds={LISTENING_SECONDS} onExpire={submit} />
        </div>
      )}

      <h2>{task.content.title}</h2>

      <div className="card" style={{ marginBottom: 24 }}>
        <div style={{ display: "flex", gap: 10, alignItems: "center", flexWrap: "wrap" }}>
          <button className="btn" onClick={play} disabled={playing}>
            {playing ? "▶ Playing..." : plays === 0 ? "▶ Play audio" : "↻ Play again"}
          </button>
          {playing && <button className="btn secondary" onClick={stop}>■ Stop</button>}
          <span className="subtitle" style={{ margin: 0 }}>
            {plays === 0 ? "In the real exam you hear it once." : `Played ${plays}×`}
          </span>
        </div>
        {!attempt && (
          <p className="subtitle" style={{ margin: "12px 0 0" }}>
            Listen and answer below. The transcript stays hidden until you submit.
          </p>
        )}
      </div>

      {showTranscript && task.content.transcript && (
        <div style={{ marginBottom: 24 }}>
          <h2>Transcript</h2>
          <div className="card" style={{ whiteSpace: "pre-wrap", lineHeight: 1.75 }}>
            {task.content.transcript}
          </div>
        </div>
      )}

      <h2>Questions</h2>
      <PracticeQuestions
        questions={questions}
        answers={answers}
        results={results}
        onChange={(i, v) => setAnswers((prev) => { const next = [...prev]; next[i] = v; return next; })}
      />

      {error && <div className="error">{error}</div>}

      {!attempt ? (
        <button className="btn" style={{ marginTop: 20 }} onClick={submit} disabled={busy}>
          {busy ? "Marking..." : "Submit answers"}
        </button>
      ) : (
        <div style={{ marginTop: 32 }}>
          <h2>Vocabulary from the questions you missed</h2>
          <p className="subtitle">Save these into your deck to review them as flashcards.</p>
          <SaveVocabList items={missed} emptyHint="Nothing missed — no new words to collect from this one." />

          {extra.length > 0 && (
            <div style={{ marginTop: 32 }}>
              <h2>More useful words from this recording</h2>
              <p className="subtitle">Worth learning even where you answered correctly.</p>
              <SaveVocabList items={extra} />
            </div>
          )}
        </div>
      )}
    </>
  );
}

function Header() {
  return (
    <div className="toolbar">
      <Link href="/daily" className="subtitle">&larr; Today&apos;s practice</Link>
      <div className="spacer" />
      <h1 style={{ margin: 0 }}>🎧 Listening</h1>
    </div>
  );
}

export default function DailyListeningPage() {
  return <Protected>{() => <ListeningContent />}</Protected>;
}

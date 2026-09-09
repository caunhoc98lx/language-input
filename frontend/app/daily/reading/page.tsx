"use client";

import { useEffect, useRef, useState } from "react";
import Link from "next/link";
import Protected from "@/components/Protected";
import PracticeQuestions from "@/components/PracticeQuestions";
import SaveVocabList from "@/components/SaveVocabList";
import { api, ApiError } from "@/lib/api";
import { bandColor, splitVocabByMistakes } from "@/lib/daily";
import type { DailyAttempt, DailyTask } from "@/lib/daily";

function ReadingContent() {
  const [task, setTask] = useState<DailyTask | null>(null);
  const [attempt, setAttempt] = useState<DailyAttempt | null>(null);
  const [answers, setAnswers] = useState<string[]>([]);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const startedAtRef = useRef(Date.now());

  useEffect(() => {
    api
      .get("/api/daily/reading")
      .then((data) => {
        setTask(data.task);
        setAttempt(data.attempt);
        if (data.attempt) setAnswers(data.attempt.answers);
      })
      .finally(() => setLoading(false));
  }, []);

  async function generate() {
    setBusy(true);
    setError(null);
    try {
      const data = await api.post("/api/daily/reading/generate");
      setTask(data.task);
      setAttempt(data.attempt);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Could not generate today's reading.");
    } finally {
      setBusy(false);
    }
  }

  async function submit() {
    setBusy(true);
    setError(null);
    try {
      const duration_sec = Math.round((Date.now() - startedAtRef.current) / 1000);
      const data = await api.post("/api/daily/reading/submit", { answers, duration_sec });
      setAttempt(data.attempt);
      setTask((prev) => (prev ? { ...prev, content: data.content } : prev));
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
          <h2>Today&apos;s reading isn&apos;t ready yet</h2>
          <p>Generate an original IELTS Academic passage with 8 questions. It takes a few seconds.</p>
          {error && <div className="error">{error}</div>}
          <button className="btn" style={{ marginTop: 12 }} onClick={generate} disabled={busy}>
            {busy ? "Writing your passage..." : "Generate today's reading"}
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
          <div className="spacer" style={{ flex: 1 }} />
          <Link href="/daily" className="btn secondary">Back to today</Link>
        </div>
      )}

      <h2>{task.content.title}</h2>
      {task.content.topic && <span className="badge" style={{ marginBottom: 12, display: "inline-block" }}>{task.content.topic}</span>}
      <div className="card" style={{ marginBottom: 24, whiteSpace: "pre-wrap", lineHeight: 1.75 }}>
        {task.content.passage}
      </div>

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
          <p className="subtitle">
            Save these into your deck and they&apos;ll come back as flashcards on a spaced-repetition schedule.
          </p>
          <SaveVocabList
            items={missed}
            emptyHint="Nothing missed — no new words to collect from this one. Nice work."
          />

          {extra.length > 0 && (
            <div style={{ marginTop: 32 }}>
              <h2>More useful words from this passage</h2>
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
      <h1 style={{ margin: 0 }}>📖 Reading</h1>
    </div>
  );
}

export default function DailyReadingPage() {
  return <Protected>{() => <ReadingContent />}</Protected>;
}

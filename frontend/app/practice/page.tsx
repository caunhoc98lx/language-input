"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import Protected from "@/components/Protected";
import { api } from "@/lib/api";
import { typeLabel } from "@/lib/practice";
import type { Coaching, QuestionTypeAccuracy } from "@/lib/types";

interface Weaknesses extends Coaching {
  unresolved_mistakes: number;
  grammar_topics: { topic: string; count: number }[];
  weak_words: { word: string; translation: string; lapses: number }[];
  available_types: string[];
}

const SIZES = [5, 10, 20];

function PracticeHub() {
  const router = useRouter();
  const [data, setData] = useState<Weaknesses | null>(null);
  const [type, setType] = useState("");
  const [count, setCount] = useState(10);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => {
    api.get("/api/practice/weaknesses").then(setData).catch((e) => setError(e.message));
  }, []);

  async function start(source: "MISTAKES" | "TYPE", questionType?: string) {
    setBusy(true);
    setError("");
    try {
      const payload = await api.post("/api/practice/targeted", {
        source,
        question_type: questionType ?? type,
        limit: count,
        mode: "LEARNING",
      });
      router.push(`/practice/${payload.session.id}`);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Could not start practice.");
      setBusy(false);
    }
  }

  if (error && !data) return <div className="card empty-state"><h2>Not available</h2><p>{error}</p></div>;
  if (!data) return null;

  const weak: QuestionTypeAccuracy[] = data.weak_areas;

  return (
    <>
      <h1>Practice</h1>
      <p className="subtitle">Work on one question type, or redo the questions you got wrong.</p>

      <div className="grid grid-2" style={{ marginBottom: 20 }}>
        <div className="card">
          <h2>Redo my mistakes</h2>
          <p className="subtitle">
            {data.unresolved_mistakes > 0
              ? `${data.unresolved_mistakes} question${data.unresolved_mistakes === 1 ? "" : "s"} you have never got right.`
              : "Nothing outstanding — every question you have missed, you have since answered correctly."}
          </p>
          <button
            className="btn"
            disabled={busy || data.unresolved_mistakes === 0}
            onClick={() => start("MISTAKES")}
          >
            Practise my mistakes
          </button>
        </div>

        <div className="card">
          <h2>Practice by question type</h2>
          {data.available_types.length === 0 ? (
            <p className="subtitle">
              No imported questions yet. <Link href="/library/import">Import a book</Link> to unlock this.
            </p>
          ) : (
            <>
              <select value={type} onChange={(e) => setType(e.target.value)} style={{ width: "100%" }}>
                <option value="">Choose a question type…</option>
                {data.available_types.map((t) => (
                  <option key={t} value={t}>
                    {typeLabel(t)}
                  </option>
                ))}
              </select>
              <div className="option-row" style={{ margin: "12px 0" }}>
                {SIZES.map((n) => (
                  <button
                    key={n}
                    className={`chip-select ${count === n ? "active" : ""}`}
                    onClick={() => setCount(n)}
                  >
                    {n} questions
                  </button>
                ))}
              </div>
              <button className="btn" disabled={busy || !type} onClick={() => start("TYPE")}>
                Start practice
              </button>
            </>
          )}
        </div>
      </div>

      {error && <div className="error">{error}</div>}

      <div className="card" style={{ marginBottom: 20 }}>
        <h2>What to work on</h2>
        {weak.length === 0 ? (
          <p className="subtitle" style={{ margin: 0 }}>
            Not enough answered questions yet to call anything a weakness.
          </p>
        ) : (
          weak.map((row) => (
            <div key={row.type} className="weak-row">
              <span className="label">{row.label}</span>
              <span className={`meter ${row.accuracy < 0.6 ? "weak" : "ok"}`}>
                <span style={{ width: `${Math.round(row.accuracy * 100)}%` }} />
              </span>
              <span className="pct">
                {Math.round(row.accuracy * 100)}% · {row.attempts}q
              </span>
              {data.available_types.includes(row.type) && (
                <button className="btn small" disabled={busy} onClick={() => start("TYPE", row.type)}>
                  Practise
                </button>
              )}
            </div>
          ))
        )}
      </div>

      {(data.grammar_topics.length > 0 || data.weak_words.length > 0) && (
        <div className="grid grid-2">
          {data.grammar_topics.length > 0 && (
            <div className="card">
              <h2>Grammar to fix</h2>
              {data.grammar_topics.map((g) => (
                <div key={g.topic} className="weak-row">
                  <span className="label">{g.topic}</span>
                  <span className="pct">{g.count} mistake{g.count === 1 ? "" : "s"}</span>
                </div>
              ))}
              <Link href="/writing" className="btn secondary small" style={{ marginTop: 12, display: "inline-flex" }}>
                Write another task
              </Link>
            </div>
          )}
          {data.weak_words.length > 0 && (
            <div className="card">
              <h2>Words you keep forgetting</h2>
              {data.weak_words.map((w) => (
                <div key={w.word} className="weak-row">
                  <span className="label">
                    {w.word} <span className="subtitle" style={{ margin: 0 }}>{w.translation}</span>
                  </span>
                  <span className="pct">{w.lapses}×</span>
                </div>
              ))}
              <Link href="/study/flashcards" className="btn secondary small" style={{ marginTop: 12, display: "inline-flex" }}>
                Review them
              </Link>
            </div>
          )}
        </div>
      )}
    </>
  );
}

export default function PracticePage() {
  return <Protected>{() => <PracticeHub />}</Protected>;
}

"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import Protected from "@/components/Protected";
import SaveVocabList from "@/components/SaveVocabList";
import { api, ApiError } from "@/lib/api";
import { bandColor } from "@/lib/daily";
import type { DailyAttempt, DailyTask, WritingFeedback } from "@/lib/daily";

const CRITERIA: [keyof WritingFeedback, string][] = [
  ["task_response", "Task Response"],
  ["coherence_cohesion", "Coherence & Cohesion"],
  ["lexical_resource", "Lexical Resource"],
  ["grammatical_range", "Grammatical Range & Accuracy"],
];

function WritingContent() {
  const [task, setTask] = useState<DailyTask | null>(null);
  const [attempt, setAttempt] = useState<DailyAttempt | null>(null);
  const [essay, setEssay] = useState("");
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    api
      .get("/api/daily/writing")
      .then((data) => {
        setTask(data.task);
        setAttempt(data.attempt);
        if (data.attempt?.answers?.[0]) setEssay(data.attempt.answers[0]);
      })
      .finally(() => setLoading(false));
  }, []);

  async function generate() {
    setBusy(true);
    setError(null);
    try {
      const data = await api.post("/api/daily/writing/generate");
      setTask(data.task);
      setAttempt(data.attempt);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Could not generate today's writing task.");
    } finally {
      setBusy(false);
    }
  }

  async function submit() {
    setBusy(true);
    setError(null);
    try {
      const data = await api.post("/api/daily/writing/submit", { essay });
      setAttempt(data.attempt);
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
          <h2>Today&apos;s writing task isn&apos;t ready yet</h2>
          <p>Generate an IELTS Writing Task 2 question. An AI examiner will mark what you write against the four official criteria.</p>
          {error && <div className="error">{error}</div>}
          <button className="btn" style={{ marginTop: 12 }} onClick={generate} disabled={busy}>
            {busy ? "Setting your question..." : "Generate today's writing task"}
          </button>
        </div>
      </>
    );
  }

  const words = essay.trim() ? essay.trim().split(/\s+/).length : 0;
  const minWords = task.content.min_words || 250;
  const fb = attempt?.feedback as WritingFeedback | undefined;

  return (
    <>
      <Header />

      {fb && (
        <>
          <div className="card" style={{ marginBottom: 16, display: "flex", alignItems: "center", gap: 24 }}>
            <div>
              <div style={{ fontSize: "2.6rem", fontWeight: 700, lineHeight: 1, color: bandColor(fb.band_overall) }}>
                {fb.band_overall?.toFixed(1)}
              </div>
              <div className="subtitle" style={{ margin: "4px 0 0" }}>overall band</div>
            </div>
            <div className="grid grid-4" style={{ flex: 1, gap: 12 }}>
              {CRITERIA.map(([key, label]) => (
                <div key={key}>
                  <div style={{ fontWeight: 700, fontSize: "1.2rem", color: bandColor(fb[key] as number) }}>
                    {(fb[key] as number)?.toFixed(1)}
                  </div>
                  <div className="subtitle" style={{ margin: 0, fontSize: "0.78rem" }}>{label}</div>
                </div>
              ))}
            </div>
          </div>

          {fb.summary && <div className="card" style={{ marginBottom: 16 }}><p style={{ margin: 0 }}>{fb.summary}</p></div>}

          <div className="grid grid-2" style={{ marginBottom: 16, alignItems: "start" }}>
            {fb.strengths?.length > 0 && (
              <div className="card">
                <h2 style={{ color: "var(--success)" }}>Điểm mạnh</h2>
                <ul style={{ margin: 0, paddingLeft: 18 }}>{fb.strengths.map((s, i) => <li key={i}>{s}</li>)}</ul>
              </div>
            )}
            {fb.weaknesses?.length > 0 && (
              <div className="card">
                <h2 style={{ color: "var(--danger)" }}>Cần cải thiện</h2>
                <ul style={{ margin: 0, paddingLeft: 18 }}>{fb.weaknesses.map((s, i) => <li key={i}>{s}</li>)}</ul>
              </div>
            )}
          </div>

          {fb.corrections?.length > 0 && (
            <div style={{ marginBottom: 24 }}>
              <h2>Sentence-by-sentence feedback</h2>
              <p className="subtitle">Câu bạn viết, cách viết tốt hơn, và tại sao.</p>
              <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
                {fb.corrections.map((c, i) => (
                  <div className="card" key={i}>
                    <p style={{ margin: "0 0 8px", color: "var(--danger)", textDecoration: "line-through", opacity: 0.75 }}>
                      {c.original}
                    </p>
                    <p style={{ margin: "0 0 10px", color: "var(--success)", fontWeight: 600 }}>{c.improved}</p>
                    <p className="subtitle" style={{ margin: 0 }}>{c.why}</p>
                  </div>
                ))}
              </div>
            </div>
          )}

          <div style={{ marginBottom: 32 }}>
            <h2>Higher-band vocabulary for this topic</h2>
            <p className="subtitle">Save these to practise them before your next essay.</p>
            <SaveVocabList items={fb.suggested_vocabulary || []} />
          </div>
        </>
      )}

      <h2>{task.content.task_type} {task.content.title && `— ${task.content.title}`}</h2>
      <div className="card" style={{ marginBottom: 16 }}>
        <p style={{ margin: 0, whiteSpace: "pre-wrap", lineHeight: 1.7 }}>{task.content.prompt}</p>
        {task.content.guidance && (
          <p className="subtitle" style={{ margin: "14px 0 0", paddingTop: 14, borderTop: "1px solid var(--border)" }}>
            💡 {task.content.guidance}
          </p>
        )}
      </div>

      {attempt ? (
        <>
          <h2>Your essay</h2>
          <div className="card" style={{ whiteSpace: "pre-wrap", lineHeight: 1.7 }}>{essay}</div>
          <div style={{ marginTop: 20 }}>
            <Link href="/daily" className="btn secondary">Back to today</Link>
          </div>
        </>
      ) : (
        <>
          <textarea
            rows={16}
            placeholder="Write your essay here..."
            value={essay}
            onChange={(e) => setEssay(e.target.value)}
          />
          <div className="toolbar" style={{ marginTop: 12 }}>
            <span className="subtitle" style={{ margin: 0, color: words < minWords ? "var(--warning)" : "var(--success)" }}>
              {words} words {words < minWords && `· ${minWords} minimum`}
            </span>
            <div className="spacer" />
            <button className="btn" onClick={submit} disabled={busy || words < 20}>
              {busy ? "Examiner is marking..." : "Submit for marking"}
            </button>
          </div>
          {error && <div className="error">{error}</div>}
        </>
      )}
    </>
  );
}

function Header() {
  return (
    <div className="toolbar">
      <Link href="/daily" className="subtitle">&larr; Today&apos;s practice</Link>
      <div className="spacer" />
      <h1 style={{ margin: 0 }}>✍️ Writing</h1>
    </div>
  );
}

export default function DailyWritingPage() {
  return <Protected>{() => <WritingContent />}</Protected>;
}

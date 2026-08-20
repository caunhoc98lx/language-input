"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import Protected from "@/components/Protected";
import { api } from "@/lib/api";

interface Prompt {
  id: number;
  title: string;
  instructions: string;
  body: string;
  section_number: number;
  test_number: number;
  material_id: number;
  material_title: string;
  attempts: number;
}

interface Submission {
  id: number;
  task_label: string;
  prompt: string;
  band: number | null;
  word_count: number;
  created_at: string;
}

function WritingContent() {
  const [prompts, setPrompts] = useState<Prompt[]>([]);
  const [submissions, setSubmissions] = useState<Submission[]>([]);
  const [loaded, setLoaded] = useState(false);

  useEffect(() => {
    Promise.all([
      api.get("/api/writing/prompts").catch(() => ({ prompts: [] })),
      api.get("/api/submissions?kind=WRITING").catch(() => ({ submissions: [] })),
    ]).then(([p, s]) => {
      setPrompts(p.prompts);
      setSubmissions(s.submissions);
      setLoaded(true);
    });
  }, []);

  if (!loaded) return null;

  return (
    <>
      <h1>Writing</h1>
      <p className="subtitle">
        Answer a task from your imported material and get an examiner report on all four criteria.
      </p>

      <h2>Imported tasks</h2>
      {prompts.length === 0 ? (
        <div className="card empty-state">
          <p>
            No writing tasks yet. Import a book with Writing Task 1 or Task 2 pages and they appear here.
          </p>
          <Link href="/library/import" className="btn" style={{ marginTop: 10, display: "inline-flex" }}>
            Import material
          </Link>
        </div>
      ) : (
        <div className="card" style={{ padding: 0, marginBottom: 24 }}>
          {prompts.map((p) => (
            <Link key={p.id} href={`/writing/${p.id}`} className="list-row" style={{ display: "flex" }}>
              <div style={{ flex: 1 }}>
                <div style={{ fontWeight: 600 }}>
                  {p.material_title} · Test {p.test_number} · {p.title}
                </div>
                <div className="subtitle" style={{ margin: 0 }}>
                  {(p.body || p.instructions).slice(0, 120)}…
                </div>
              </div>
              {p.attempts > 0 && <span className="badge mastered">{p.attempts} attempt{p.attempts === 1 ? "" : "s"}</span>}
            </Link>
          ))}
        </div>
      )}

      <h2>Your submissions</h2>
      {submissions.length === 0 ? (
        <div className="card empty-state">
          <p>Nothing submitted yet.</p>
        </div>
      ) : (
        <div className="card" style={{ padding: 0 }}>
          {submissions.map((s) => (
            <Link key={s.id} href={`/writing/submissions/${s.id}`} className="list-row" style={{ display: "flex" }}>
              <div style={{ flex: 1 }}>
                <div style={{ fontWeight: 600 }}>{s.task_label}</div>
                <div className="subtitle" style={{ margin: 0 }}>
                  {s.word_count} words · {s.created_at.slice(0, 16).replace("T", " ")}
                </div>
              </div>
              {s.band !== null && <span className="badge">Band {s.band.toFixed(1)}</span>}
            </Link>
          ))}
        </div>
      )}
    </>
  );
}

export default function WritingPage() {
  return <Protected>{() => <WritingContent />}</Protected>;
}

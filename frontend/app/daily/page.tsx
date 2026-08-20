"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import Protected from "@/components/Protected";
import { api } from "@/lib/api";
import { bandColor } from "@/lib/daily";
import type { DailyKind, DailyOverviewItem } from "@/lib/daily";

const TASKS: { kind: DailyKind; label: string; blurb: string; icon: string }[] = [
  { kind: "reading", label: "Reading", blurb: "An IELTS Academic passage with 8 questions", icon: "📖" },
  { kind: "listening", label: "Listening", blurb: "A spoken talk or conversation with 6 questions", icon: "🎧" },
  { kind: "writing", label: "Writing", blurb: "A Task 2 essay, marked by an AI examiner", icon: "✍️" },
];

interface Overview {
  date: string;
  tasks: Record<DailyKind, DailyOverviewItem>;
  history: { kind: string; task_date: string; title: string; score: number | null; total: number | null; band: number | null }[];
}

function DailyContent() {
  const [data, setData] = useState<Overview | null>(null);

  useEffect(() => {
    api.get("/api/daily").then(setData);
  }, []);

  if (!data) return null;

  const done = TASKS.filter((t) => data.tasks[t.kind]?.attempted).length;

  return (
    <>
      <h1>Today&apos;s practice</h1>
      <p className="subtitle">
        {new Date(data.date).toLocaleDateString(undefined, { weekday: "long", day: "numeric", month: "long" })}
        {" · "}{done} of {TASKS.length} finished
      </p>

      <div className="grid" style={{ gap: 16, marginBottom: 32 }}>
        {TASKS.map((t) => {
          const state = data.tasks[t.kind];
          return (
            <div className="card" key={t.kind} style={{ display: "flex", alignItems: "center", gap: 16 }}>
              <div style={{ fontSize: "1.8rem" }}>{t.icon}</div>
              <div style={{ flex: 1 }}>
                <div style={{ display: "flex", gap: 10, alignItems: "center", flexWrap: "wrap" }}>
                  <strong>{t.label}</strong>
                  {state?.attempted && <span className="badge mastered">Done</span>}
                  {state?.generated && !state.attempted && <span className="badge due">Ready</span>}
                </div>
                <div className="subtitle" style={{ margin: "4px 0 0" }}>
                  {state?.generated && state.title ? state.title : t.blurb}
                </div>
              </div>

              {state?.attempted && (
                <div style={{ textAlign: "right" }}>
                  <div style={{ fontSize: "1.4rem", fontWeight: 700, color: bandColor(state.band) }}>
                    {state.band?.toFixed(1)}
                  </div>
                  <div className="subtitle" style={{ margin: 0, fontSize: "0.8rem" }}>
                    {state.total ? `${state.score}/${state.total}` : "band"}
                  </div>
                </div>
              )}

              <Link href={`/daily/${t.kind}`} className={state?.attempted ? "btn secondary" : "btn"}>
                {state?.attempted ? "Review" : state?.generated ? "Continue" : "Start"}
              </Link>
            </div>
          );
        })}
      </div>

      <h2>Recent results</h2>
      {data.history.length > 0 ? (
        <div className="card" style={{ padding: 0 }}>
          {data.history.map((h, i) => (
            <div className="list-row" key={i}>
              <div>
                <div style={{ fontWeight: 600, textTransform: "capitalize" }}>{h.kind}</div>
                <div className="subtitle" style={{ margin: 0 }}>{h.title || h.task_date}</div>
              </div>
              <div style={{ display: "flex", gap: 10, alignItems: "center" }}>
                {h.total !== null && <span className="subtitle" style={{ margin: 0 }}>{h.score}/{h.total}</span>}
                <span className="badge" style={{ background: "transparent", color: bandColor(h.band), border: `1px solid ${bandColor(h.band)}` }}>
                  Band {h.band?.toFixed(1)}
                </span>
                <span className="subtitle" style={{ margin: 0, fontSize: "0.8rem" }}>{h.task_date}</span>
              </div>
            </div>
          ))}
        </div>
      ) : (
        <div className="card empty-state">
          <p>No practice yet. Finish a task above and your band scores will build up here.</p>
        </div>
      )}
    </>
  );
}

export default function DailyPage() {
  return <Protected>{() => <DailyContent />}</Protected>;
}

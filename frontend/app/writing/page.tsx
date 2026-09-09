"use client";

import { useEffect, useState } from "react";
import Protected from "@/components/Protected";
import DailyWritingTask from "@/components/DailyWritingTask";
import { api } from "@/lib/api";
import { bandColor } from "@/lib/daily";

interface HistoryItem {
  kind: string;
  task_date: string;
  title: string;
  band: number | null;
}

function WritingContent() {
  const [history, setHistory] = useState<HistoryItem[] | null>(null);
  const [refreshKey, setRefreshKey] = useState(0);

  useEffect(() => {
    api.get("/api/daily").then((data) => {
      setHistory(data.history.filter((h: HistoryItem) => h.kind === "writing"));
    });
  }, [refreshKey]);

  if (!history) return null;

  return (
    <>
      <h1>Writing</h1>
      <p className="subtitle">Every day, a fresh IELTS Writing Task 2 question - write your essay and an AI examiner marks it on all four criteria.</p>

      <DailyWritingTask onSubmitted={() => setRefreshKey((k) => k + 1)} />

      <h2>Your submissions</h2>
      {history.length === 0 ? (
        <div className="card empty-state">
          <p>Nothing submitted yet.</p>
        </div>
      ) : (
        <div className="card" style={{ padding: 0 }}>
          {history.map((h, i) => (
            <div className="list-row" key={i}>
              <div style={{ fontWeight: 600 }}>{h.title || h.task_date}</div>
              <div style={{ display: "flex", gap: 10, alignItems: "center" }}>
                <span className="badge" style={{ background: "transparent", color: bandColor(h.band), border: `1px solid ${bandColor(h.band)}` }}>
                  Band {h.band?.toFixed(1)}
                </span>
                <span className="subtitle" style={{ margin: 0, fontSize: "0.8rem" }}>{h.task_date}</span>
              </div>
            </div>
          ))}
        </div>
      )}
    </>
  );
}

export default function WritingPage() {
  return <Protected>{() => <WritingContent />}</Protected>;
}

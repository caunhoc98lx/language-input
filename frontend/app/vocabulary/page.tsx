"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import Protected from "@/components/Protected";
import { api } from "@/lib/api";
import type { Vocab } from "@/lib/types";

const FILTERS: [string, string][] = [
  ["", "All"],
  ["due", "Due"],
  ["NEW", "New"],
  ["LEARNING", "Learning"],
  ["REVIEW", "Review"],
  ["MASTERED", "Mastered"],
];

function VocabularyContent() {
  const [items, setItems] = useState<Vocab[]>([]);
  const [state, setState] = useState("");
  const [q, setQ] = useState("");

  useEffect(() => {
    const params = new URLSearchParams();
    if (state) params.set("state", state);
    if (q) params.set("q", q);
    api.get(`/api/vocabulary?${params}`).then((data) => setItems(data.items));
  }, [state, q]);

  return (
    <>
      <div className="toolbar">
        <h1 style={{ margin: 0 }}>Vocabulary</h1>
        <div className="spacer" />
        <Link href="/vocabulary/new" className="btn">+ Add vocabulary</Link>
      </div>

      <input
        type="text"
        placeholder="Search word or translation..."
        defaultValue={q}
        onChange={(e) => setQ(e.target.value)}
        style={{ marginBottom: 16 }}
      />

      <div className="toolbar">
        {FILTERS.map(([key, label]) => (
          <button
            key={key}
            className={`chip-select ${state === key ? "active" : ""}`}
            onClick={() => setState(key)}
          >
            {label}
          </button>
        ))}
      </div>

      {items.length > 0 ? (
        <div className="card" style={{ padding: 0 }}>
          {items.map((v) => (
            <Link key={v.id} href={`/vocabulary/${v.id}`} className="list-row" style={{ display: "flex" }}>
              <div>
                <div style={{ fontWeight: 600 }}>
                  {v.word} {v.part_of_speech && <span className="subtitle" style={{ margin: 0 }}>({v.part_of_speech})</span>} {v.starred ? "★" : ""}
                </div>
                <div className="subtitle" style={{ margin: 0 }}>{v.translation}</div>
              </div>
              <div className={`badge ${v.srs_state.toLowerCase()}`}>{v.srs_state}</div>
            </Link>
          ))}
        </div>
      ) : (
        <div className="card empty-state">
          <h2>No vocabulary yet</h2>
          <p>Add your first English word and we&apos;ll automatically translate it, explain it, and schedule it for review.</p>
          <Link href="/vocabulary/new" className="btn" style={{ marginTop: 10, display: "inline-flex" }}>Add vocabulary</Link>
        </div>
      )}
    </>
  );
}

export default function VocabularyPage() {
  return <Protected>{() => <VocabularyContent />}</Protected>;
}

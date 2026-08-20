"use client";

import { useState } from "react";
import Link from "next/link";
import { api } from "@/lib/api";
import type { VocabItem } from "@/lib/types";

/**
 * Shows vocabulary harvested from a practice task and lets the learner push the
 * selected words into their spaced-repetition deck. This is the loop that turns
 * a wrong answer into something they will actually revise.
 */
export default function SaveVocabList({ items, emptyHint }: { items: VocabItem[]; emptyHint?: string }) {
  const [selected, setSelected] = useState<Set<number>>(new Set(items.map((_, i) => i)));
  const [saved, setSaved] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  if (items.length === 0) {
    return emptyHint ? <p className="subtitle">{emptyHint}</p> : null;
  }

  function toggle(i: number) {
    setSelected((prev) => {
      const next = new Set(prev);
      if (next.has(i)) next.delete(i);
      else next.add(i);
      return next;
    });
  }

  async function save() {
    setBusy(true);
    setError(null);
    try {
      await api.post("/api/vocabulary/save", { items: items.filter((_, i) => selected.has(i)) });
      setSaved(true);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not save.");
    } finally {
      setBusy(false);
    }
  }

  if (saved) {
    return (
      <div className="card" style={{ background: "#f0fdf4", borderColor: "#bbf7d0" }}>
        <strong style={{ color: "var(--success)" }}>✓ Added {selected.size} word{selected.size === 1 ? "" : "s"} to your vocabulary.</strong>
        <p className="subtitle" style={{ margin: "6px 0 0" }}>
          They&apos;re scheduled for review now — <Link href="/study/flashcards" style={{ color: "var(--primary)", fontWeight: 600 }}>start studying</Link> or{" "}
          <Link href="/vocabulary" style={{ color: "var(--primary)", fontWeight: 600 }}>see your list</Link>.
        </p>
      </div>
    );
  }

  return (
    <div className="card" style={{ padding: "4px 20px 20px" }}>
      {items.map((v, i) => (
        <div className="preview-item" key={`${v.word}-${i}`}>
          <input type="checkbox" checked={selected.has(i)} onChange={() => toggle(i)} style={{ marginTop: 6 }} />
          <div className="fields">
            <div className="top">
              <span className="word">{v.word}</span>
              <span className="translation">{v.translation}</span>
              {v.part_of_speech && <span className="subtitle" style={{ margin: 0 }}>({v.part_of_speech})</span>}
            </div>
            {v.definition && <div className="meta">{v.definition}</div>}
            {v.examples?.[0] && <div className="meta">&quot;{v.examples[0]}&quot;</div>}
            {v.ielts_level && <span className="badge">{v.ielts_level}</span>}
          </div>
        </div>
      ))}
      {error && <div className="error">{error}</div>}
      <button className="btn" style={{ marginTop: 16 }} onClick={save} disabled={busy || selected.size === 0}>
        {busy ? "Saving..." : `Add ${selected.size} to my vocabulary`}
      </button>
    </div>
  );
}

"use client";

import { useState } from "react";
import { api } from "@/lib/api";
import type { VocabItem } from "@/lib/types";

type Suggestion = VocabItem & { already_saved: boolean };

/**
 * "12 useful IELTS words found" for an imported passage or transcript.
 *
 * Nothing is added automatically: the learner ticks what they want, exactly as
 * the spec asks. Saved words enter the normal spaced-repetition queue.
 */
export default function SectionVocabulary({ sectionId }: { sectionId: number }) {
  const [items, setItems] = useState<Suggestion[] | null>(null);
  const [picked, setPicked] = useState<Set<string>>(new Set());
  const [busy, setBusy] = useState(false);
  const [savedCount, setSavedCount] = useState(0);
  const [error, setError] = useState("");

  async function find() {
    setBusy(true);
    setError("");
    try {
      const res = await api.post(`/api/library/sections/${sectionId}/vocabulary`);
      setItems(res.items);
      setPicked(new Set(res.items.filter((i: Suggestion) => !i.already_saved).map((i: Suggestion) => i.word)));
    } catch (e) {
      setError(e instanceof Error ? e.message : "Could not read this section.");
    } finally {
      setBusy(false);
    }
  }

  async function save() {
    if (!items) return;
    const chosen = items.filter((i) => picked.has(i.word) && !i.already_saved);
    if (!chosen.length) return;
    setBusy(true);
    try {
      const res = await api.post("/api/vocabulary/save", { items: chosen });
      setSavedCount(res.saved_ids.length);
      setItems(items.map((i) => (picked.has(i.word) ? { ...i, already_saved: true } : i)));
    } catch (e) {
      setError(e instanceof Error ? e.message : "Could not save.");
    } finally {
      setBusy(false);
    }
  }

  function toggle(word: string) {
    setPicked((prev) => {
      const next = new Set(prev);
      if (next.has(word)) next.delete(word);
      else next.add(word);
      return next;
    });
  }

  const pending = items?.filter((i) => !i.already_saved).length ?? 0;

  return (
    <div className="card" style={{ marginBottom: 16 }}>
      <div style={{ display: "flex", alignItems: "center", gap: 12, flexWrap: "wrap" }}>
        <h2 style={{ margin: 0, flex: 1 }}>IELTS vocabulary</h2>
        {items && pending > 0 && (
          <button
            className="btn secondary small"
            onClick={() => setPicked(new Set(items.filter((i) => !i.already_saved).map((i) => i.word)))}
          >
            Select all
          </button>
        )}
        {items ? (
          <button className="btn small" onClick={save} disabled={busy || picked.size === 0}>
            {busy ? "Saving…" : `Add ${picked.size} to vocabulary`}
          </button>
        ) : (
          <button className="btn small" onClick={find} disabled={busy}>
            {busy ? "Reading…" : "Find useful words"}
          </button>
        )}
      </div>

      {error && <div className="error">{error}</div>}
      {savedCount > 0 && (
        <p className="subtitle" style={{ margin: "8px 0 0", color: "var(--success)" }}>
          Added. They are in your review queue now.
        </p>
      )}

      {items && (
        <>
          <p className="subtitle" style={{ margin: "10px 0" }}>
            {items.length} useful word{items.length === 1 ? "" : "s"} found
            {pending !== items.length && ` · ${items.length - pending} already in your vocabulary`}
          </p>
          <div className="vocab-suggestions">
            {items.map((item) => (
              <label key={item.word} className={`vocab-suggestion ${item.already_saved ? "saved" : ""}`}>
                <input
                  type="checkbox"
                  checked={item.already_saved || picked.has(item.word)}
                  disabled={item.already_saved}
                  onChange={() => toggle(item.word)}
                />
                <span style={{ flex: 1 }}>
                  <strong>{item.word}</strong>
                  <span className="subtitle" style={{ margin: "0 0 0 8px" }}>{item.translation}</span>
                  {item.definition && (
                    <span className="subtitle" style={{ display: "block", margin: 0 }}>{item.definition}</span>
                  )}
                </span>
                {item.ielts_level && <span className="badge">{item.ielts_level}</span>}
                {item.already_saved && <span className="badge mastered">saved</span>}
              </label>
            ))}
          </div>
        </>
      )}
    </div>
  );
}

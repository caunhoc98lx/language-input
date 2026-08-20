"use client";

import { useState } from "react";
import { api } from "@/lib/api";
import type { VocabItem } from "@/lib/types";

/**
 * Wraps any block of text so selecting a word looks it up and offers to save it.
 *
 * This is the Listening/Reading -> Vocabulary -> spaced repetition bridge: a word
 * met in a real passage goes into the same review queue as everything else.
 */
export default function WordLookup({ children }: { children: React.ReactNode }) {
  const [word, setWord] = useState("");
  const [item, setItem] = useState<VocabItem | null>(null);
  const [savedId, setSavedId] = useState<number | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  async function lookup() {
    const selection = window.getSelection();
    const picked = selection?.toString().trim() ?? "";
    if (!picked || picked.length > 80 || picked.split(/\s+/).length > 4) return;

    // Send the sentence around the word so the meaning matches the context.
    const container = selection?.anchorNode?.textContent ?? "";
    const at = container.indexOf(picked);
    const context = at >= 0 ? container.slice(Math.max(0, at - 150), at + 200) : "";

    setWord(picked);
    setItem(null);
    setSavedId(null);
    setError("");
    setBusy(true);
    try {
      const res = await api.post("/api/vocabulary/lookup", { word: picked, context });
      setItem(res.item);
      setSavedId(res.saved_id);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Lookup failed.");
    } finally {
      setBusy(false);
    }
  }

  async function save() {
    if (!item) return;
    setBusy(true);
    try {
      const res = await api.post("/api/vocabulary/save", { items: [item] });
      setSavedId(res.saved_ids[0]);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Could not save.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <>
      <div onMouseUp={lookup} onTouchEnd={lookup} className="lookup-surface">
        {children}
      </div>

      {(word || error) && (
        <div className="lookup-popover card">
          <div style={{ display: "flex", alignItems: "baseline", gap: 10 }}>
            <strong style={{ flex: 1 }}>{item?.word || word}</strong>
            <button
              className="btn secondary small"
              onClick={() => {
                setWord("");
                setItem(null);
                setError("");
              }}
            >
              Close
            </button>
          </div>

          {busy && <p className="subtitle" style={{ margin: "8px 0 0" }}>Looking up…</p>}
          {error && <div className="error">{error}</div>}

          {item && (
            <>
              <p style={{ margin: "6px 0 0" }}>
                <strong style={{ color: "var(--primary)" }}>{item.translation}</strong>
                {item.pronunciation && (
                  <span className="subtitle" style={{ margin: "0 0 0 8px" }}>{item.pronunciation}</span>
                )}
              </p>
              {item.definition && <p className="subtitle" style={{ margin: "6px 0 0" }}>{item.definition}</p>}
              {item.examples?.[0] && (
                <p className="subtitle" style={{ margin: "6px 0 0", fontStyle: "italic" }}>
                  {item.examples[0]}
                </p>
              )}
              <div style={{ display: "flex", alignItems: "center", gap: 10, marginTop: 12 }}>
                {savedId ? (
                  <span className="badge mastered">In your vocabulary</span>
                ) : (
                  <button className="btn small" onClick={save} disabled={busy}>
                    Save to vocabulary
                  </button>
                )}
                {item.ielts_level && <span className="badge">{item.ielts_level}</span>}
              </div>
            </>
          )}
        </div>
      )}
    </>
  );
}

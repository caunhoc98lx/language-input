"use client";

import { useState } from "react";
import { api } from "@/lib/api";
import type { VocabItem } from "@/lib/types";

export interface Correction {
  original: string;
  improved: string;
  why: string;
  error_type?: string;
  grammar_topic?: string;
}

export interface Feedback {
  band_overall: number;
  summary?: string;
  strengths?: string[];
  weaknesses?: string[];
  corrections?: Correction[];
  suggested_vocabulary?: VocabItem[];
  overused_words?: string[];
  fillers?: string[];
  [key: string]: unknown;
}

/**
 * Examiner report for a writing or speaking submission.
 *
 * Deliberately not a rewrite of the answer: per-criterion bands, then the
 * learner's own sentences with what to change and why, and the vocabulary that
 * would have raised the band - each saveable into spaced repetition.
 */
export default function FeedbackReport({
  feedback,
  criteria,
  band,
}: {
  feedback: Feedback;
  criteria: { key: string; label: string }[];
  band: number | null;
}) {
  const [savedWords, setSavedWords] = useState<Set<string>>(new Set());
  const [busy, setBusy] = useState("");

  async function saveWord(item: VocabItem) {
    setBusy(item.word);
    try {
      await api.post("/api/vocabulary/save", { items: [item] });
      setSavedWords((prev) => new Set(prev).add(item.word));
    } finally {
      setBusy("");
    }
  }

  return (
    <>
      <div className="card result-card">
        <div className="result-stats" style={{ gridTemplateColumns: `repeat(${criteria.length + 1}, 1fr)` }}>
          <div>
            <div className="num">{band !== null ? band.toFixed(1) : "—"}</div>
            <div className="label">Overall</div>
          </div>
          {criteria.map((c) => {
            const value = feedback[c.key];
            return (
              <div key={c.key}>
                <div className="num">{typeof value === "number" ? value.toFixed(1) : "—"}</div>
                <div className="label">{c.label}</div>
              </div>
            );
          })}
        </div>
        {feedback.summary && <p style={{ marginTop: 18, marginBottom: 0 }}>{feedback.summary}</p>}
      </div>

      {(feedback.strengths?.length || feedback.weaknesses?.length) && (
        <div className="grid grid-2" style={{ marginBottom: 16 }}>
          <div className="card">
            <h2>Strengths</h2>
            <ul className="plain-list">
              {(feedback.strengths ?? []).map((s) => (
                <li key={s}>{s}</li>
              ))}
            </ul>
          </div>
          <div className="card">
            <h2>To improve</h2>
            <ul className="plain-list">
              {(feedback.weaknesses ?? []).map((s) => (
                <li key={s}>{s}</li>
              ))}
            </ul>
          </div>
        </div>
      )}

      {(feedback.fillers?.length || feedback.overused_words?.length) && (
        <div className="card" style={{ marginBottom: 16 }}>
          <h2>Speech habits</h2>
          {feedback.fillers?.length ? (
            <p className="subtitle" style={{ margin: 0 }}>
              Fillers you leaned on: <strong>{feedback.fillers.join(", ")}</strong>
            </p>
          ) : null}
          {feedback.overused_words?.length ? (
            <p className="subtitle" style={{ margin: "6px 0 0" }}>
              Overused words: <strong>{feedback.overused_words.join(", ")}</strong>
            </p>
          ) : null}
        </div>
      )}

      {feedback.corrections?.length ? (
        <div className="card" style={{ marginBottom: 16 }}>
          <h2>Your sentences, improved</h2>
          {feedback.corrections.map((c, i) => (
            <div key={i} className="correction">
              <p className="correction-original">{c.original}</p>
              <p className="correction-improved">{c.improved}</p>
              {c.why && <p className="subtitle" style={{ margin: "6px 0 0" }}>{c.why}</p>}
              {(c.error_type || c.grammar_topic) && (
                <div style={{ marginTop: 8, display: "flex", gap: 8, flexWrap: "wrap" }}>
                  {c.error_type && <span className="badge due">{c.error_type}</span>}
                  {c.grammar_topic && <span className="badge">{c.grammar_topic}</span>}
                </div>
              )}
            </div>
          ))}
        </div>
      ) : null}

      {feedback.suggested_vocabulary?.length ? (
        <div className="card">
          <h2>Vocabulary that would have raised your band</h2>
          <div className="vocab-suggestions">
            {feedback.suggested_vocabulary.map((item) => (
              <div key={item.word} className="vocab-suggestion" style={{ cursor: "default" }}>
                <span style={{ flex: 1 }}>
                  <strong>{item.word}</strong>
                  <span className="subtitle" style={{ margin: "0 0 0 8px" }}>{item.translation}</span>
                  {item.examples?.[0] && (
                    <span className="subtitle" style={{ display: "block", margin: 0, fontStyle: "italic" }}>
                      {item.examples[0]}
                    </span>
                  )}
                </span>
                {savedWords.has(item.word) ? (
                  <span className="badge mastered">saved</span>
                ) : (
                  <button
                    className="btn secondary small"
                    disabled={busy === item.word}
                    onClick={() => saveWord(item)}
                  >
                    Save
                  </button>
                )}
              </div>
            ))}
          </div>
        </div>
      ) : null}
    </>
  );
}

"use client";

import { useCallback, useEffect, useState } from "react";
import Link from "next/link";
import { useSearchParams } from "next/navigation";
import Protected from "@/components/Protected";
import Confetti, { makeConfettiPieces, type ConfettiPiece } from "@/components/Confetti";
import StudyModeTabs from "@/components/StudyModeTabs";
import { api, newRequestId } from "@/lib/api";
import { speak } from "@/lib/speech";
import type { Vocab } from "@/lib/types";

const RATINGS = [
  { key: "again", label: "Again", cls: "rating-again", hint: "1" },
  { key: "hard", label: "Hard", cls: "rating-hard", hint: "2" },
  { key: "good", label: "Good", cls: "rating-good", hint: "3" },
  { key: "easy", label: "Easy", cls: "rating-easy", hint: "4" },
] as const;

type RatingKey = (typeof RATINGS)[number]["key"];
type Preview = Record<RatingKey, { interval_days: number; next_review_at: string; state: string }>;

/** Formats a day count from the scheduler into "<10m / 1h / 4d / 3mo / 1.2y" -
 * pure display formatting of a number the backend already computed; no
 * scheduling logic lives here. */
function formatInterval(days: number): string {
  const minutes = days * 24 * 60;
  if (minutes < 1) return "<1m";
  if (minutes < 60) return `${Math.round(minutes)}m`;
  const hours = minutes / 60;
  if (hours < 24) return `${Math.round(hours)}h`;
  if (days < 30) return `${Math.round(days)}d`;
  if (days < 365) return `${Math.round(days / 30)}mo`;
  return `${(days / 365).toFixed(1)}y`;
}

function AnkiContent() {
  const setId = useSearchParams().get("set_id") || "";
  const [queue, setQueue] = useState<Vocab[] | null>(null);
  const [i, setI] = useState(0);
  const [combo, setCombo] = useState(0);
  const [inputValue, setInputValue] = useState("");
  const [wrongOnce, setWrongOnce] = useState(false);
  const [settled, setSettled] = useState(false);
  const [busy, setBusy] = useState(false);
  const [feedback, setFeedback] = useState<{ correct: boolean; text: string } | null>(null);
  const [confettiPieces, setConfettiPieces] = useState<ConfettiPiece[] | null>(null);
  const [preview, setPreview] = useState<Preview | null>(null);

  useEffect(() => {
    const params = setId ? `?set_id=${setId}` : "";
    api.get(`/api/study/flashcards${params}`).then((data) => setQueue(data.queue));
  }, [setId]);

  const card = queue ? queue[i] : undefined;

  const advance = useCallback((requeue: boolean) => {
    setWrongOnce(false);
    setSettled(false);
    setFeedback(null);
    setInputValue("");
    setConfettiPieces(null);
    setPreview(null);
    if (requeue && card) {
      // Not done with this word yet - it resurfaces a few cards later in
      // the same session instead of disappearing after one miss.
      setQueue((prev) => {
        if (!prev) return prev;
        const next = [...prev];
        next.splice(Math.min(next.length, i + 4), 0, card);
        return next;
      });
    }
    setI((prev) => prev + 1);
  }, [card, i]);

  const rate = useCallback(async (rating: RatingKey) => {
    if (!card || busy) return; // client-side guard: ignore a second click while the first is in flight
    setBusy(true);
    try {
      if (rating === "good" || rating === "easy") setConfettiPieces(makeConfettiPieces());
      // request_id: a fresh id per rating click, sent to the idempotent
      // /api/review endpoint - if this exact HTTP request is ever retried
      // (flaky network, not a second click, which the busy guard already
      // blocks) the backend applies it once, not twice.
      await api.post("/api/review", { vocabulary_id: card.id, rating, request_id: newRequestId() });
      advance(rating === "again");
    } finally {
      setBusy(false);
    }
  }, [card, busy, advance]);

  async function check() {
    if (settled || busy || !card || !inputValue.trim()) return;
    const correct = inputValue.trim().toLowerCase() === card.word.trim().toLowerCase();
    if (correct) {
      setSettled(true);
      setFeedback({
        correct: true,
        text: wrongOnce ? `Nice — it's "${card.word}". How well did you know it?` : "🎉 Correct! How well did you know it?",
      });
      setCombo((c) => (wrongOnce ? c : c + 1));
      // Wait for the learner to self-rate below, Anki-style - typing it
      // correctly only proves the spelling, not how easily it came. This
      // applies whether it was right first try or only after a retype.
    } else {
      setInputValue("");
      setCombo(0);
      if (!wrongOnce) {
        setWrongOnce(true);
        setFeedback({ correct: false, text: `Not quite — type "${card.word}" to continue` });
        setBusy(true);
        try {
          await api.post("/api/review", { vocabulary_id: card.id, rating: "again", request_id: newRequestId() });
        } finally {
          setBusy(false);
        }
      } else {
        setFeedback({ correct: false, text: `Type "${card.word}" to continue` });
      }
    }
  }

  const awaitingRating = settled;

  // Fetch what each rating would do, to show on the buttons before the
  // learner picks one (section 7 of the spec) - never computed on the
  // frontend, always the same scheduler the real submit uses.
  useEffect(() => {
    if (!awaitingRating || !card) return;
    let cancelled = false;
    api.get(`/api/review/preview/${card.id}`).then((data) => {
      if (!cancelled) setPreview(data);
    });
    return () => { cancelled = true; };
  }, [awaitingRating, card]);

  useEffect(() => {
    function onKey(e: KeyboardEvent) {
      if (!awaitingRating) return;
      const byHint = RATINGS.find((r) => r.hint === e.key);
      if (byHint) rate(byHint.key);
    }
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [awaitingRating, rate]);

  if (!queue) return null;

  const progressPct = queue.length ? (100 * i) / queue.length : 0;

  return (
    <>
      <div className="toolbar">
        <h1 style={{ margin: 0 }}>Study session</h1>
        <div className="spacer" />
        <StudyModeTabs active="anki" />
      </div>

      {queue.length === 0 ? (
        <div className="card empty-state">
          <h2>No cards to study right now</h2>
          <p>Nothing is due, and you have no new words. Add more vocabulary or check back later.</p>
          <Link href="/vocabulary/new" className="btn" style={{ marginTop: 10, display: "inline-flex" }}>Add vocabulary</Link>
        </div>
      ) : !card ? (
        <div className="card empty-state">
          <h2>Session complete 🎉</h2>
          <p>{queue.length} cards reviewed.</p>
          <Link href="/dashboard" className="btn" style={{ marginTop: 10, display: "inline-flex" }}>Back to dashboard</Link>
        </div>
      ) : (
        <div className="study-wrap">
          <div className="session-row">
            <span className="subtitle" style={{ margin: 0 }}>Card {i + 1} of {queue.length}</span>
            {combo > 1 && <span className="combo-pill">🔥 {combo} in a row</span>}
          </div>
          <div className="progress-bar"><div className="progress-bar-fill" style={{ width: `${progressPct}%` }} /></div>

          <div className={`flashcard${feedback && !feedback.correct ? " shake" : ""}`} style={{ cursor: "default", position: "relative" }}>
            <Confetti pieces={confettiPieces} />
            <span className={`badge ${card.srs_state.toLowerCase()}`} style={{ position: "absolute", top: 18, right: 18 }}>
              {card.srs_state}
            </span>

            {!wrongOnce && !settled ? (
              <>
                <div className="pos">What&apos;s the English word for...</div>
                <div className="word" style={{ fontSize: "1.7rem", margin: "6px 0" }}>{card.translation || "—"}</div>
                {card.definition && <div className="pos">{card.definition}</div>}
                <input
                  type="text"
                  autoComplete="off"
                  placeholder="Type your answer..."
                  value={inputValue}
                  autoFocus
                  onChange={(e) => setInputValue(e.target.value)}
                  onKeyDown={(e) => { if (e.key === "Enter") check(); }}
                  style={{ marginTop: 16, textAlign: "center", fontSize: "1.1rem" }}
                />
                <button className="btn" style={{ marginTop: 12 }} onClick={check} disabled={!inputValue.trim() || busy}>
                  Check
                </button>
              </>
            ) : (
              <>
                <div
                  className={`feedback ${feedback?.correct ? "correct" : "wrong"}`}
                  style={{ fontWeight: 700, fontSize: "1.05rem", color: feedback?.correct ? "var(--success)" : "var(--danger)" }}
                >
                  {feedback?.text}
                </div>
                <div className="word-row" style={{ marginTop: 8 }}>
                  <div className="word">{card.word}</div>
                  <button
                    type="button"
                    className="speak-btn"
                    aria-label="Listen"
                    onClick={() => speak(card.word)}
                  >
                    🔊
                  </button>
                </div>
                {card.pronunciation && (
                  <div className="pos">{card.pronunciation}{card.part_of_speech && ` · ${card.part_of_speech}`}</div>
                )}
                {card.examples.length > 0 && (
                  <div className="examples">{card.examples.map((e, idx) => <div key={idx}>{e}</div>)}</div>
                )}
                {!settled && (
                  <>
                    <input
                      type="text"
                      autoComplete="off"
                      placeholder="Type it to continue..."
                      value={inputValue}
                      autoFocus
                      onChange={(e) => setInputValue(e.target.value)}
                      onKeyDown={(e) => { if (e.key === "Enter") check(); }}
                      style={{ marginTop: 16, textAlign: "center", fontSize: "1.1rem", borderColor: "var(--danger)" }}
                    />
                    <button className="btn" style={{ marginTop: 12 }} onClick={check} disabled={!inputValue.trim() || busy}>
                      Check
                    </button>
                  </>
                )}
              </>
            )}
          </div>

          {awaitingRating && (
            <div style={{ width: "100%", maxWidth: 520 }}>
              <div className="rating-row">
                {RATINGS.map((r) => (
                  <button key={r.key} className={r.cls} onClick={() => rate(r.key)} disabled={busy}>
                    {r.label}
                    <span className="rating-interval">{preview ? formatInterval(preview[r.key].interval_days) : "…"}</span>
                  </button>
                ))}
              </div>
              <div style={{ display: "flex", justifyContent: "space-around", marginTop: 6 }}>
                {RATINGS.map((r) => (
                  <span key={r.key} className="subtitle" style={{ margin: 0, fontSize: "0.78rem" }}>
                    <span className="kbd">{r.hint}</span>
                  </span>
                ))}
              </div>
            </div>
          )}
        </div>
      )}
    </>
  );
}

export default function AnkiPage() {
  return <Protected>{() => <AnkiContent />}</Protected>;
}

"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { useSearchParams } from "next/navigation";
import Protected from "@/components/Protected";
import { api } from "@/lib/api";
import type { Vocab } from "@/lib/types";

function FlashcardsContent() {
  const setId = useSearchParams().get("set_id") || "";
  const [queue, setQueue] = useState<Vocab[] | null>(null);
  const [i, setI] = useState(0);
  const [combo, setCombo] = useState(0);
  const [inputValue, setInputValue] = useState("");
  const [answered, setAnswered] = useState(false);
  const [feedback, setFeedback] = useState<{ correct: boolean; text: string } | null>(null);

  useEffect(() => {
    const params = setId ? `?set_id=${setId}` : "";
    api.get(`/api/study/flashcards${params}`).then((data) => setQueue(data.queue));
  }, [setId]);

  if (!queue) return null;

  const progressPct = queue.length ? (100 * i) / queue.length : 0;
  const card = queue[i];

  async function check() {
    if (answered || !card || !inputValue.trim()) return;
    const correct = inputValue.trim().toLowerCase() === card.word.trim().toLowerCase();
    setAnswered(true);
    setFeedback({ correct, text: correct ? "🎉 Correct!" : `Not quite — it's "${card.word}"` });
    setCombo((c) => (correct ? c + 1 : 0));
    await api.post("/api/review", { vocabulary_id: card.id, rating: correct ? "good" : "again" });
    setTimeout(() => {
      setAnswered(false);
      setFeedback(null);
      setInputValue("");
      setI((prev) => prev + 1);
    }, correct ? 1100 : 1700);
  }

  return (
    <>
      <div className="toolbar">
        <h1 style={{ margin: 0 }}>Study session</h1>
        <div className="spacer" />
        <span className="chip-select active">Flashcards</span>
        <Link href="/study/learn" className="chip-select">Learn</Link>
      </div>

      {queue.length === 0 ? (
        <div className="card empty-state">
          <h2>No cards to study right now</h2>
          <p>Nothing is due, and you have no new words. Add more vocabulary or check back later.</p>
          <Link href="/vocabulary/new" className="btn" style={{ marginTop: 10, display: "inline-flex" }}>Add vocabulary</Link>
        </div>
      ) : i >= queue.length ? (
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

          <div className="flashcard" style={{ cursor: "default", position: "relative" }}>
            <span className={`badge ${card.srs_state.toLowerCase()}`} style={{ position: "absolute", top: 18, right: 18 }}>
              {card.srs_state}
            </span>

            {!answered ? (
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
                <button className="btn" style={{ marginTop: 12 }} onClick={check} disabled={!inputValue.trim()}>
                  Check
                </button>
              </>
            ) : (
              <>
                <div
                  style={{ fontWeight: 700, fontSize: "1.05rem", color: feedback?.correct ? "var(--success)" : "var(--danger)" }}
                >
                  {feedback?.text}
                </div>
                <div className="word" style={{ marginTop: 8 }}>{card.word}</div>
                {card.pronunciation && (
                  <div className="pos">{card.pronunciation}{card.part_of_speech && ` · ${card.part_of_speech}`}</div>
                )}
                {card.examples.length > 0 && (
                  <div className="examples">{card.examples.map((e, idx) => <div key={idx}>{e}</div>)}</div>
                )}
              </>
            )}
          </div>
        </div>
      )}
    </>
  );
}

export default function FlashcardsPage() {
  return <Protected>{() => <FlashcardsContent />}</Protected>;
}

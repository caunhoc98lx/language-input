"use client";

import { useCallback, useEffect, useState } from "react";
import Link from "next/link";
import { useSearchParams } from "next/navigation";
import Protected from "@/components/Protected";
import { api } from "@/lib/api";
import type { Vocab } from "@/lib/types";

type Rating = "again" | "hard" | "good" | "easy";

function FlashcardsContent() {
  const setId = useSearchParams().get("set_id") || "";
  const [queue, setQueue] = useState<Vocab[] | null>(null);
  const [i, setI] = useState(0);
  const [flipped, setFlipped] = useState(false);

  useEffect(() => {
    const params = setId ? `?set_id=${setId}` : "";
    api.get(`/api/study/flashcards${params}`).then((data) => setQueue(data.queue));
  }, [setId]);

  const rate = useCallback(async (rating: Rating) => {
    if (!queue || i >= queue.length) return;
    await api.post("/api/review", { vocabulary_id: queue[i].id, rating });
    setFlipped(false);
    setI((prev) => prev + 1);
  }, [queue, i]);

  useEffect(() => {
    function onKey(e: KeyboardEvent) {
      if (e.code === "Space") {
        e.preventDefault();
        setFlipped((f) => !f);
      } else if (flipped && ["1", "2", "3", "4"].includes(e.key)) {
        rate({ "1": "again", "2": "hard", "3": "good", "4": "easy" }[e.key] as Rating);
      }
    }
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [flipped, rate]);

  if (!queue) return null;

  const progressPct = queue.length ? (100 * i) / queue.length : 0;
  const card = queue[i];

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
          <div className="progress-bar"><div className="progress-bar-fill" style={{ width: `${progressPct}%` }} /></div>

          <div className="flashcard" onClick={() => setFlipped((f) => !f)}>
            {!flipped ? (
              <>
                <div className="word">{card.word}</div>
                {card.pronunciation && (
                  <div className="pos">{card.pronunciation}{card.part_of_speech && ` · ${card.part_of_speech}`}</div>
                )}
              </>
            ) : (
              <>
                <div className="word">{card.translation || "—"}</div>
                <div className="pos">{card.definition}</div>
                {card.examples.length > 0 && (
                  <div className="examples">{card.examples.map((e, idx) => <div key={idx}>{e}</div>)}</div>
                )}
              </>
            )}
          </div>

          {flipped && (
            <div className="rating-row">
              <button className="rating-again" onClick={() => rate("again")}>Again <div className="kbd">1</div></button>
              <button className="rating-hard" onClick={() => rate("hard")}>Hard <div className="kbd">2</div></button>
              <button className="rating-good" onClick={() => rate("good")}>Good <div className="kbd">3</div></button>
              <button className="rating-easy" onClick={() => rate("easy")}>Easy <div className="kbd">4</div></button>
            </div>
          )}

          <p className="subtitle">{flipped ? "How well did you know it?" : "Click the card or press Space to flip."}</p>
        </div>
      )}
    </>
  );
}

export default function FlashcardsPage() {
  return <Protected>{() => <FlashcardsContent />}</Protected>;
}

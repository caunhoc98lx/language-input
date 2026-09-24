"use client";

import { useState } from "react";
import { api, newRequestId } from "@/lib/api";
import { speak } from "@/lib/speech";
import type { LearnCard } from "@/lib/types";
import Confetti, { makeConfettiPieces, type ConfettiPiece } from "@/components/Confetti";

/**
 * A missed card is not "done" on the first miss - the learner has to produce
 * (retype, or pick) the right answer before moving on. `onNext(wasWrong)`
 * tells the caller whether to bring the card back later in this session.
 */
export default function QuestionCard({ card, onNext }: { card: LearnCard; onNext: (wasWrong: boolean) => void }) {
  const [settled, setSettled] = useState(false);
  const [wrongOnce, setWrongOnce] = useState(false);
  const [feedback, setFeedback] = useState<{ correct: boolean; text: string } | null>(null);
  const [picked, setPicked] = useState<string | boolean | null>(null);
  const [inputValue, setInputValue] = useState("");
  const [confettiPieces, setConfettiPieces] = useState<ConfettiPiece[] | null>(null);

  async function grade(rating: "good" | "again") {
    await api.post("/api/review", { vocabulary_id: card.id, rating, request_id: newRequestId() });
  }

  async function settle(correctText: string) {
    setSettled(true);
    setFeedback({ correct: true, text: wrongOnce ? `Nice — it's "${correctText}"` : "Correct!" });
    if (!wrongOnce) setConfettiPieces(makeConfettiPieces());
    if (!wrongOnce) await grade("good");
    setTimeout(() => onNext(wrongOnce), wrongOnce ? 900 : 1100);
  }

  async function miss(retryHint: string) {
    speak(card.word);
    if (!wrongOnce) {
      setWrongOnce(true);
      setFeedback({ correct: false, text: retryHint });
      await grade("again");
    } else {
      setFeedback({ correct: false, text: retryHint });
    }
  }

  const confetti = <Confetti pieces={confettiPieces} />;
  const cardClass = `flashcard${feedback && !feedback.correct ? " shake" : ""}`;

  if (card.question_type === "multiple_choice") {
    async function pick(opt: string) {
      if (settled) return;
      setPicked(opt);
      if (opt === card.translation) await settle(card.translation);
      else await miss("Not quite — try again");
    }
    return (
      <div className={cardClass} style={{ cursor: "default", alignItems: "stretch", textAlign: "left" }}>
        {confetti}
        <div className="pos">What does this word mean?</div>
        <div className="word-row" style={{ marginBottom: 16, justifyContent: "flex-start" }}>
          <div className="word">{card.word}</div>
          <button type="button" className="speak-btn" aria-label="Listen" onClick={() => speak(card.word)}>🔊</button>
        </div>
        <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
          {card.options!.map((opt) => {
            const isPicked = picked === opt;
            const bg = isPicked ? (opt === card.translation ? "#dcfce7" : "#fee2e2") : undefined;
            return (
              <button key={opt} className="btn secondary" style={{ background: bg }} onClick={() => pick(opt)}>
                {opt}
              </button>
            );
          })}
        </div>
        {feedback && <div className={`feedback ${feedback.correct ? "correct" : "wrong"}`} style={{ fontWeight: 600, marginTop: 10, color: feedback.correct ? "var(--success)" : "var(--danger)" }}>{feedback.text}</div>}
      </div>
    );
  }

  if (card.question_type === "true_false") {
    async function pick(val: boolean) {
      if (settled) return;
      setPicked(val);
      if (val === card.tf_answer) await settle(card.tf_answer ? "True" : "False");
      else await miss("Not quite — try again");
    }
    return (
      <div className={cardClass} style={{ cursor: "default", alignItems: "stretch", textAlign: "left" }}>
        {confetti}
        <div className="pos">True or False?</div>
        <div className="word-row" style={{ marginBottom: 6, justifyContent: "flex-start" }}>
          <div className="word" style={{ fontSize: "1.4rem" }}>{card.word}</div>
          <button type="button" className="speak-btn" aria-label="Listen" onClick={() => speak(card.word)}>🔊</button>
        </div>
        <div className="examples" style={{ marginTop: 0 }}>&quot;{card.tf_statement}&quot;</div>
        <div style={{ display: "flex", gap: 10, marginTop: 16 }}>
          {[true, false].map((val) => {
            const isPicked = picked === val;
            const bg = isPicked ? (val === card.tf_answer ? "#dcfce7" : "#fee2e2") : undefined;
            return (
              <button key={String(val)} className="btn secondary" style={{ flex: 1, background: bg }} onClick={() => pick(val)}>
                {val ? "True" : "False"}
              </button>
            );
          })}
        </div>
        {feedback && <div className={`feedback ${feedback.correct ? "correct" : "wrong"}`} style={{ fontWeight: 600, marginTop: 10, color: feedback.correct ? "var(--success)" : "var(--danger)" }}>{feedback.text}</div>}
      </div>
    );
  }

  // type_answer or fill_blank
  async function check() {
    if (settled || !inputValue.trim()) return;
    const correct = inputValue.trim().toLowerCase() === card.word.trim().toLowerCase();
    if (correct) {
      await settle(card.word);
    } else {
      setInputValue("");
      await miss(`Not quite — type "${card.word}" to continue`);
    }
  }

  return (
    <div className={cardClass} style={{ cursor: "default", alignItems: "stretch", textAlign: "left" }}>
      {confetti}
      {card.question_type === "fill_blank" ? (
        <>
          <div className="pos">Fill in the blank</div>
          <div className="examples" style={{ marginTop: 0 }}>{card.blank_sentence}</div>
        </>
      ) : (
        <div className="pos">Type the English word for:</div>
      )}
      <div className="word" style={{ marginBottom: 14 }}>{card.translation}</div>
      <input
        type="text"
        autoComplete="off"
        placeholder="Type your answer..."
        value={inputValue}
        autoFocus
        onChange={(e) => setInputValue(e.target.value)}
        onKeyDown={(e) => { if (e.key === "Enter") check(); }}
        style={{ borderColor: feedback ? (feedback.correct ? "var(--success)" : "var(--danger)") : undefined }}
        disabled={settled}
      />
      <button className="btn" style={{ marginTop: 12 }} onClick={check} disabled={settled || !inputValue.trim()}>Check</button>
      {feedback && (
        <div className="word-row" style={{ marginTop: 10, justifyContent: "flex-start" }}>
          <div className={`feedback ${feedback.correct ? "correct" : "wrong"}`} style={{ fontWeight: 600, color: feedback.correct ? "var(--success)" : "var(--danger)" }}>
            {feedback.text}
          </div>
          {settled && <button type="button" className="speak-btn" aria-label="Listen" onClick={() => speak(card.word)}>🔊</button>}
        </div>
      )}
    </div>
  );
}

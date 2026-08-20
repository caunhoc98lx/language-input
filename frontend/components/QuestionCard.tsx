"use client";

import { useState } from "react";
import { api } from "@/lib/api";
import type { LearnCard } from "@/lib/types";

export default function QuestionCard({ card, onNext }: { card: LearnCard; onNext: () => void }) {
  const [answered, setAnswered] = useState(false);
  const [feedback, setFeedback] = useState<{ correct: boolean; text: string } | null>(null);
  const [picked, setPicked] = useState<string | boolean | null>(null);
  const [inputValue, setInputValue] = useState("");

  async function submit(correct: boolean, correctAnswerText: string) {
    if (answered) return;
    setAnswered(true);
    setFeedback({ correct, text: correct ? "Correct!" : `Not quite. Answer: ${correctAnswerText}` });
    await api.post("/api/review", { vocabulary_id: card.id, rating: correct ? "good" : "again" });
    setTimeout(onNext, correct ? 1100 : 1300);
  }

  if (card.question_type === "multiple_choice") {
    return (
      <div className="flashcard" style={{ cursor: "default", alignItems: "stretch", textAlign: "left" }}>
        <div className="pos">What does this word mean?</div>
        <div className="word" style={{ marginBottom: 16 }}>{card.word}</div>
        <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
          {card.options!.map((opt) => {
            const isPicked = picked === opt;
            const bg = answered && isPicked ? (opt === card.translation ? "#dcfce7" : "#fee2e2") : undefined;
            return (
              <button
                key={opt}
                className="btn secondary"
                style={{ background: bg }}
                onClick={() => { setPicked(opt); submit(opt === card.translation, card.translation); }}
              >
                {opt}
              </button>
            );
          })}
        </div>
        {feedback && <div style={{ fontWeight: 600, marginTop: 10, color: feedback.correct ? "var(--success)" : "var(--danger)" }}>{feedback.text}</div>}
      </div>
    );
  }

  if (card.question_type === "true_false") {
    return (
      <div className="flashcard" style={{ cursor: "default", alignItems: "stretch", textAlign: "left" }}>
        <div className="pos">True or False?</div>
        <div className="word" style={{ fontSize: "1.4rem", marginBottom: 6 }}>{card.word}</div>
        <div className="examples" style={{ marginTop: 0 }}>&quot;{card.tf_statement}&quot;</div>
        <div style={{ display: "flex", gap: 10, marginTop: 16 }}>
          {[true, false].map((val) => {
            const isPicked = picked === val;
            const bg = answered && isPicked ? (val === card.tf_answer ? "#dcfce7" : "#fee2e2") : undefined;
            return (
              <button
                key={String(val)}
                className="btn secondary"
                style={{ flex: 1, background: bg }}
                onClick={() => { setPicked(val); submit(val === card.tf_answer, card.tf_answer ? "True" : "False"); }}
              >
                {val ? "True" : "False"}
              </button>
            );
          })}
        </div>
        {feedback && <div style={{ fontWeight: 600, marginTop: 10, color: feedback.correct ? "var(--success)" : "var(--danger)" }}>{feedback.text}</div>}
      </div>
    );
  }

  // type_answer or fill_blank
  const check = () => {
    const correct = inputValue.trim().toLowerCase() === card.word.trim().toLowerCase();
    submit(correct, card.word);
  };

  return (
    <div className="flashcard" style={{ cursor: "default", alignItems: "stretch", textAlign: "left" }}>
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
        style={{ borderColor: answered ? (feedback?.correct ? "var(--success)" : "var(--danger)") : undefined }}
        disabled={answered}
      />
      <button className="btn" style={{ marginTop: 12 }} onClick={check} disabled={answered}>Check</button>
      {feedback && <div style={{ fontWeight: 600, marginTop: 10, color: feedback.correct ? "var(--success)" : "var(--danger)" }}>{feedback.text}</div>}
    </div>
  );
}

"use client";

import { TRUE_FALSE_OPTIONS } from "@/lib/daily";
import type { PracticeQuestion, QuestionResult } from "@/lib/daily";

/**
 * Renders the question list for a reading/listening task. In review mode it also
 * shows the correct answer and why the learner's answer was wrong.
 */
export default function PracticeQuestions({
  questions,
  answers,
  onChange,
  results,
}: {
  questions: PracticeQuestion[];
  answers: string[];
  onChange?: (index: number, value: string) => void;
  results?: QuestionResult[];
}) {
  const review = !!results;

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 16 }}>
      {questions.map((q, i) => {
        const result = results?.[i];
        const options = q.type === "true_false_notgiven" ? TRUE_FALSE_OPTIONS : q.options;
        const borderColor = result ? (result.correct ? "var(--success)" : "var(--danger)") : "var(--border)";

        return (
          <div className="card" key={i} style={{ borderColor, borderWidth: review ? 2 : 1 }}>
            <div style={{ display: "flex", gap: 10, alignItems: "baseline", marginBottom: 10 }}>
              <span className="badge">{i + 1}</span>
              <strong style={{ flex: 1 }}>{q.question}</strong>
              {result && (
                <span className={`badge ${result.correct ? "mastered" : "due"}`}>
                  {result.correct ? "Correct" : "Wrong"}
                </span>
              )}
            </div>

            {options.length > 0 ? (
              <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
                {options.map((opt) => {
                  const chosen = answers[i] === opt;
                  const isAnswer = review && q.answer === opt;
                  let background: string | undefined;
                  if (isAnswer) background = "#dcfce7";
                  else if (review && chosen) background = "#fee2e2";
                  else if (chosen) background = "#eef2ff";
                  return (
                    <label
                      key={opt}
                      style={{
                        display: "flex", alignItems: "center", gap: 10, margin: 0,
                        padding: "10px 12px", borderRadius: 10, background,
                        border: "1px solid var(--border)", fontWeight: 400,
                        cursor: review ? "default" : "pointer",
                      }}
                    >
                      <input
                        type="radio"
                        name={`q-${i}`}
                        checked={chosen}
                        disabled={review}
                        onChange={() => onChange?.(i, opt)}
                      />
                      {opt}
                      {isAnswer && <span className="badge mastered" style={{ marginLeft: "auto" }}>Answer</span>}
                    </label>
                  );
                })}
              </div>
            ) : (
              <input
                type="text"
                placeholder="Your answer (1-3 words)"
                value={answers[i] || ""}
                disabled={review}
                onChange={(e) => onChange?.(i, e.target.value)}
              />
            )}

            {review && result && (
              <div style={{ marginTop: 12, paddingTop: 12, borderTop: "1px solid var(--border)" }}>
                {!result.correct && (
                  <p style={{ margin: "0 0 6px" }}>
                    <span className="subtitle" style={{ margin: 0 }}>You answered: </span>
                    <strong style={{ color: "var(--danger)" }}>{result.given || "(blank)"}</strong>
                    <span className="subtitle" style={{ margin: "0 0 0 10px" }}>Correct: </span>
                    <strong style={{ color: "var(--success)" }}>{result.answer}</strong>
                  </p>
                )}
                {q.explanation && <p className="subtitle" style={{ margin: 0 }}>{q.explanation}</p>}
              </div>
            )}
          </div>
        );
      })}
    </div>
  );
}

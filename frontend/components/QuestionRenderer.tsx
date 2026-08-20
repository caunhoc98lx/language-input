"use client";

import { CHOICE_TYPES, optionsFor, typeLabel } from "@/lib/practice";
import type { PracticeGroup, PracticeQuestion, QuestionResult } from "@/lib/practice";

/**
 * Renders one question, whatever its type, wherever it came from.
 *
 * Everything the app can practise goes through here: imported PDF questions,
 * hand-edited ones, and anything generated later. Adding a type means adding a
 * branch here, not a new practice screen.
 *
 * ponytail: choice-style types (multiple choice, TFNG, all the matching
 * variants) differ only in where their options come from, so they share one
 * renderer instead of five near-identical components.
 */
export default function QuestionRenderer({
  question,
  group,
  value,
  onChange,
  result,
  disabled,
}: {
  question: PracticeQuestion;
  group?: PracticeGroup;
  value: string;
  onChange: (value: string) => void;
  result?: QuestionResult;
  disabled?: boolean;
}) {
  const options = optionsFor(question, group);
  const isChoice = CHOICE_TYPES.has(question.question_type) && options.length > 0;
  const reviewing = !!result;
  const locked = disabled || reviewing;

  return (
    <div
      className={`practice-question ${reviewing ? (result.correct ? "correct" : "wrong") : ""}`}
      id={`q-${question.question_number}`}
    >
      <div className="practice-question-head">
        <span className="badge">{question.question_number}</span>
        <span style={{ flex: 1, fontWeight: 500 }}>{question.question_text}</span>
        {reviewing && (
          <span className={`badge ${result.correct ? "mastered" : "due"}`}>
            {result.correct ? "Correct" : result.answered ? "Wrong" : "Not answered"}
          </span>
        )}
      </div>

      {question.instruction && <p className="subtitle" style={{ margin: "0 0 8px" }}>{question.instruction}</p>}

      {isChoice ? (
        <div className="choice-list">
          {options.map((option, i) => {
            const chosen = value === option;
            return (
              <label key={option} className={`choice ${chosen ? "chosen" : ""}`}>
                <input
                  type="radio"
                  name={`q-${question.id}`}
                  checked={chosen}
                  disabled={locked}
                  onChange={() => onChange(option)}
                />
                <span className="choice-key">{String.fromCharCode(65 + i)}</span>
                {option}
              </label>
            );
          })}
        </div>
      ) : (
        <input
          className="answer-input"
          value={value}
          disabled={locked}
          placeholder={question.word_limit || "Your answer"}
          onChange={(e) => onChange(e.target.value)}
        />
      )}

      {question.word_limit && !reviewing && (
        <p className="subtitle" style={{ margin: "6px 0 0", fontSize: "0.8rem" }}>
          {question.word_limit}
        </p>
      )}

      {reviewing && (
        <div className="practice-review">
          {!result.correct && (
            <p style={{ margin: "0 0 4px" }}>
              <span className="subtitle" style={{ margin: 0 }}>Your answer: </span>
              <strong style={{ color: "var(--danger)" }}>{result.given || "(blank)"}</strong>
              <span className="subtitle" style={{ margin: "0 0 0 12px" }}>Correct: </span>
              <strong style={{ color: "var(--success)" }}>{result.answer || "—"}</strong>
            </p>
          )}
          {(result.explanation || question.explanation) && (
            <p className="subtitle" style={{ margin: 0 }}>{result.explanation || question.explanation}</p>
          )}
          <p className="subtitle" style={{ margin: "6px 0 0", fontSize: "0.8rem" }}>
            {typeLabel(question.question_type)}
          </p>
        </div>
      )}
    </div>
  );
}

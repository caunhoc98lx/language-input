"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import Link from "next/link";
import { api } from "@/lib/api";
import { formatDuration, timeAllowance, typeLabel } from "@/lib/practice";
import type { PracticePayload, PracticeQuestion, QuestionResult } from "@/lib/practice";
import AudioPlayer from "./AudioPlayer";
import WordLookup from "./WordLookup";
import QuestionRenderer from "./QuestionRenderer";

const AUTOSAVE_MS = 4000;

/**
 * The one practice screen. Reading shows passage-beside-questions, listening
 * shows the audio player above them, writing/speaking show the prompt - but the
 * session, timer, autosave, marking and results are identical, because the
 * server treats every skill the same way.
 */
export default function PracticeEngine({ payload }: { payload: PracticePayload }) {
  const [data, setData] = useState<PracticePayload>(payload);
  const [answers, setAnswers] = useState<Record<string, string>>(payload.answers || {});
  const [elapsed, setElapsed] = useState(0);
  const [submitting, setSubmitting] = useState(false);
  const [confirming, setConfirming] = useState(false);
  const [error, setError] = useState("");
  const [showTranscript, setShowTranscript] = useState(false);
  const [mobileTab, setMobileTab] = useState<"passage" | "questions">("passage");
  const dirty = useRef(false);

  const { session, sections, groups, questions } = data;
  const result = data.result;
  const submitted = session.status === "SUBMITTED";
  const exam = session.mode === "EXAM";
  const reading = session.skill === "READING";
  const passage = sections.map((s) => s.body).filter(Boolean).join("\n\n");
  const allowance = useMemo(
    () => timeAllowance(session.skill, sections.length, questions.length),
    [session.skill, sections.length, questions.length],
  );
  const remaining = Math.max(0, allowance - elapsed);
  const answeredCount = questions.filter((q) => (answers[String(q.id)] || "").trim()).length;

  const resultFor = useCallback(
    (question: PracticeQuestion): QuestionResult | undefined =>
      result?.results.find((r) => r.question_id === question.id),
    [result],
  );

  // Timer. Only runs while the attempt is live, and in exam mode it is what ends
  // the attempt - the submit happens from the tick, not from a render.
  const submitRef = useRef<() => void>(null);
  useEffect(() => {
    if (submitted) return;
    const deadline = Date.now() + allowance * 1000;
    const t = setInterval(() => {
      setElapsed((e) => e + 1);
      if (exam && Date.now() >= deadline) {
        clearInterval(t);
        submitRef.current?.();
      }
    }, 1000);
    return () => clearInterval(t);
  }, [submitted, exam, allowance]);

  const save = useCallback(async () => {
    if (!dirty.current || submitted) return;
    dirty.current = false;
    try {
      await api.patch(`/api/practice/sessions/${session.id}/answers`, { answers });
    } catch {
      dirty.current = true; // keep the flag so the next tick retries
    }
  }, [answers, session.id, submitted]);

  // Autosave, so a closed tab or a refresh never costs the learner their answers.
  useEffect(() => {
    const t = setInterval(save, AUTOSAVE_MS);
    return () => clearInterval(t);
  }, [save]);

  // Warn before leaving mid-test.
  useEffect(() => {
    if (submitted) return;
    const handler = (e: BeforeUnloadEvent) => {
      if (answeredCount > 0) e.preventDefault();
    };
    window.addEventListener("beforeunload", handler);
    return () => window.removeEventListener("beforeunload", handler);
  }, [answeredCount, submitted]);

  function setAnswer(question: PracticeQuestion, value: string) {
    dirty.current = true;
    setAnswers((prev) => ({ ...prev, [String(question.id)]: value }));
  }

  const submit = useCallback(async () => {
    setSubmitting(true);
    setError("");
    try {
      const next: PracticePayload = await api.post(`/api/practice/sessions/${session.id}/submit`, {
        answers,
        duration_sec: elapsed,
      });
      setData(next);
      setConfirming(false);
      window.scrollTo({ top: 0, behavior: "smooth" });
    } catch (e) {
      setError(e instanceof Error ? e.message : "Could not submit.");
    } finally {
      setSubmitting(false);
    }
  }, [answers, elapsed, session.id]);

  useEffect(() => {
    submitRef.current = submit;
  }, [submit]);

  const questionList = (
    <div className="question-column">
      {sections.map((section) => {
        const sectionQuestions = questions.filter((q) => q.section_id === section.id);
        return (
          <div key={section.id}>
            {sections.length > 1 && (
              <h2 style={{ marginTop: 20 }}>
                {section.title}
                {section.first_question && section.last_question
                  ? ` · Questions ${section.first_question}–${section.last_question}`
                  : ""}
              </h2>
            )}
            {section.instructions && <p className="subtitle">{section.instructions}</p>}
            {groups
              .filter((g) => g.section_id === section.id)
              .map((group) => {
                const groupQuestions = sectionQuestions.filter(
                  (q) => q.group_id === group.id,
                );
                if (!groupQuestions.length) return null;
                return (
                  <div key={group.id} className="question-group">
                    <div className="group-head">
                      <strong>{typeLabel(group.question_type)}</strong>
                      {group.word_limit && <span className="badge due">{group.word_limit}</span>}
                    </div>
                    {group.instruction && <p className="subtitle">{group.instruction}</p>}
                    {group.body && <div className="group-body">{group.body}</div>}
                    {group.options.length > 0 && !group.options.some((o) => groupQuestions.some((q) => q.options.includes(o))) && (
                      <ul className="option-list">
                        {group.options.map((o) => (
                          <li key={o}>{o}</li>
                        ))}
                      </ul>
                    )}
                    {groupQuestions.map((q) => (
                      <QuestionRenderer
                        key={q.id}
                        question={q}
                        group={group}
                        value={answers[String(q.id)] || ""}
                        onChange={(v) => setAnswer(q, v)}
                        result={resultFor(q)}
                        disabled={submitted}
                      />
                    ))}
                  </div>
                );
              })}
            {sectionQuestions
              .filter((q) => !q.group_id)
              .map((q) => (
                <QuestionRenderer
                  key={q.id}
                  question={q}
                  value={answers[String(q.id)] || ""}
                  onChange={(v) => setAnswer(q, v)}
                  result={resultFor(q)}
                  disabled={submitted}
                />
              ))}
          </div>
        );
      })}
    </div>
  );

  // Looking a word up mid-exam would be cheating, so click-to-look-up is on in
  // learning mode and after submitting - never during an exam attempt.
  const lookupAllowed = submitted || !exam;
  const passageBody = (
    <>
      {sections.map((s) =>
        s.body ? (
          <div key={s.id}>
            <h2>{s.title}</h2>
            <div className="passage-body">{s.body}</div>
          </div>
        ) : null,
      )}
    </>
  );
  const passagePanel = passage ? (
    <div className="passage-column">
      {lookupAllowed ? <WordLookup>{passageBody}</WordLookup> : passageBody}
      {lookupAllowed && (
        <p className="subtitle" style={{ margin: "10px 0 0", fontSize: "0.8rem" }}>
          Select any word to look it up and save it.
        </p>
      )}
    </div>
  ) : null;

  return (
    <>
      <div className="practice-bar">
        <div>
          <strong>{typeLabel(session.skill)}</strong>
          <span className="subtitle" style={{ margin: "0 0 0 10px" }}>
            {exam ? "Exam mode" : "Learning mode"}
          </span>
        </div>
        <div className="spacer" />
        {!submitted && (
          <>
            <span className={`timer ${exam && remaining < 300 ? "urgent" : ""}`}>
              {exam ? formatDuration(remaining) : formatDuration(elapsed)}
            </span>
            <span className="subtitle" style={{ margin: 0 }}>
              {answeredCount}/{questions.length} answered
            </span>
            <button className="btn" onClick={() => setConfirming(true)} disabled={submitting}>
              Submit
            </button>
          </>
        )}
        {submitted && result && (
          <>
            <span className="badge mastered">
              {result.score}/{result.total}
            </span>
            <span className="badge">Band {result.band.toFixed(1)}</span>
            <Link href="/library" className="btn secondary small">
              Library
            </Link>
          </>
        )}
      </div>

      {!submitted && (
        <nav className="question-nav">
          {questions.map((q) => (
            <a
              key={q.id}
              href={`#q-${q.question_number}`}
              className={(answers[String(q.id)] || "").trim() ? "done" : ""}
            >
              {q.question_number}
            </a>
          ))}
        </nav>
      )}

      {submitted && result && (
        <div className="card result-card">
          <div className="result-stats">
            <div>
              <div className="num">
                {result.score}/{result.total}
              </div>
              <div className="label">Correct</div>
            </div>
            <div>
              <div className="num">{result.band.toFixed(1)}</div>
              <div className="label">Band{result.band_is_estimate ? " (estimated)" : ""}</div>
            </div>
            <div>
              <div className="num">{result.unanswered}</div>
              <div className="label">Unanswered</div>
            </div>
            <div>
              <div className="num">
                {result.duration_sec ? formatDuration(result.duration_sec) : "—"}
              </div>
              <div className="label">Time</div>
            </div>
          </div>
          {result.by_type.length > 0 && (
            <div style={{ marginTop: 18 }}>
              <h2>Accuracy by question type</h2>
              {result.by_type.map((row) => (
                <div key={row.type} className="weak-row">
                  <span className="label">{typeLabel(row.type)}</span>
                  <span
                    className={`meter ${row.accuracy < 0.6 ? "weak" : row.accuracy < 0.75 ? "ok" : "good"}`}
                  >
                    <span style={{ width: `${Math.round(row.accuracy * 100)}%` }} />
                  </span>
                  <span className="pct">
                    {row.correct}/{row.attempts}
                  </span>
                </div>
              ))}
            </div>
          )}
        </div>
      )}

      {sections.some((s) => s.audio) && (
        <AudioPlayer
          sections={sections}
          examMode={exam && !submitted}
        />
      )}

      {submitted && !exam && sections.some((s) => s.transcript) && (
        <div className="card" style={{ marginBottom: 16 }}>
          <div style={{ display: "flex", alignItems: "center", gap: 12 }}>
            <h2 style={{ margin: 0, flex: 1 }}>Transcript</h2>
            <button className="btn secondary small" onClick={() => setShowTranscript((v) => !v)}>
              {showTranscript ? "Hide" : "Show"}
            </button>
          </div>
          {showTranscript && (
            <WordLookup>
              <div className="passage-body" style={{ marginTop: 12 }}>
                {sections.map((s) => s.transcript).filter(Boolean).join("\n\n")}
              </div>
            </WordLookup>
          )}
        </div>
      )}

      {error && <div className="error">{error}</div>}

      {passagePanel ? (
        <>
          <div className="mobile-tabs">
            <button
              className={mobileTab === "passage" ? "active" : ""}
              onClick={() => setMobileTab("passage")}
            >
              {reading ? "Passage" : "Content"}
            </button>
            <button
              className={mobileTab === "questions" ? "active" : ""}
              onClick={() => setMobileTab("questions")}
            >
              Questions
            </button>
          </div>
          <div className={`practice-split tab-${mobileTab}`}>
            {passagePanel}
            {questionList}
          </div>
        </>
      ) : (
        questionList
      )}

      {confirming && (
        <div className="modal-backdrop" onClick={() => setConfirming(false)}>
          <div className="card modal" onClick={(e) => e.stopPropagation()}>
            <h2>Submit this test?</h2>
            <p className="subtitle">
              {answeredCount} of {questions.length} questions answered.
              {answeredCount < questions.length && " Unanswered questions are marked wrong."}
            </p>
            <div style={{ display: "flex", gap: 10 }}>
              <button className="btn" onClick={submit} disabled={submitting}>
                {submitting ? "Marking…" : "Submit and see results"}
              </button>
              <button className="btn secondary" onClick={() => setConfirming(false)}>
                Keep working
              </button>
            </div>
          </div>
        </div>
      )}
    </>
  );
}

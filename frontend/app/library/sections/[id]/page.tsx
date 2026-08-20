"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { useParams } from "next/navigation";
import Protected from "@/components/Protected";
import { api } from "@/lib/api";
import SectionVocabulary from "@/components/SectionVocabulary";
import TranscriptEditor from "@/components/TranscriptEditor";
import { sectionLabel } from "@/lib/library";
import type { Question, Section } from "@/lib/library";

interface Group {
  id: number;
  question_type: string;
  instruction: string;
  body: string;
  options: string[];
  word_limit: string;
  first_question: number | null;
  last_question: number | null;
}

interface Detail {
  section: Section & { test_number: number; material_id: number };
  groups: Group[];
  questions: Question[];
}

const SOURCE_LABEL: Record<Question["answer_source"], string> = {
  DOCUMENT: "from document",
  AI: "AI-read · confirm",
  USER: "confirmed by you",
};

function QuestionRow({ question, onSaved }: { question: Question; onSaved: (q: Question) => void }) {
  const [text, setText] = useState(question.question_text);
  const [answer, setAnswer] = useState(question.answer);
  const [saving, setSaving] = useState(false);
  const dirty = text !== question.question_text || answer !== question.answer;

  async function save(extra: Partial<Question> = {}) {
    setSaving(true);
    try {
      onSaved(
        await api.patch(`/api/library/questions/${question.id}`, {
          question_text: text,
          answer,
          status: "READY",
          ...extra,
        }),
      );
    } finally {
      setSaving(false);
    }
  }

  return (
    <div className={`question-row ${question.status === "NEEDS_REVIEW" ? "flagged" : ""}`}>
      <div className="question-head">
        <span className="badge">{question.question_number}</span>
        <span className="subtitle" style={{ margin: 0 }}>
          {question.question_type.replaceAll("_", " ").toLowerCase()}
        </span>
        {question.parser_confidence !== null && (
          <span className="subtitle" style={{ margin: 0 }}>
            confidence {Math.round(question.parser_confidence * 100)}%
          </span>
        )}
        {question.source_page && (
          <span className="subtitle" style={{ margin: 0 }}>
            p. {question.source_page}
          </span>
        )}
        {question.status === "NEEDS_REVIEW" && <span className="badge due">needs review</span>}
      </div>

      <input value={text} onChange={(e) => setText(e.target.value)} placeholder="Question text" />

      {question.options.length > 0 && (
        <ul className="option-list">
          {question.options.map((o) => (
            <li key={o}>{o}</li>
          ))}
        </ul>
      )}

      <div className="answer-row">
        <input
          value={answer}
          onChange={(e) => setAnswer(e.target.value)}
          placeholder="Correct answer (required for marking)"
        />
        <span className={`badge ${question.answer_source === "USER" ? "mastered" : "due"}`}>
          {SOURCE_LABEL[question.answer_source]}
        </span>
        <button className="btn small" onClick={() => save()} disabled={saving || (!dirty && question.status === "READY")}>
          {saving ? "Saving…" : question.status === "READY" ? "Save" : "Confirm"}
        </button>
      </div>
    </div>
  );
}

function SectionContent({ id }: { id: number }) {
  const [data, setData] = useState<Detail | null>(null);
  const [error, setError] = useState("");

  useEffect(() => {
    api.get(`/api/library/sections/${id}`).then(setData).catch((e) => setError(e.message));
  }, [id]);

  if (error) return <div className="card empty-state"><h2>Not found</h2><p>{error}</p></div>;
  if (!data) return null;
  const { section, groups, questions } = data;

  function replaceQuestion(updated: Question) {
    setData((prev) =>
      prev ? { ...prev, questions: prev.questions.map((q) => (q.id === updated.id ? { ...q, ...updated } : q)) } : prev,
    );
  }

  return (
    <>
      <div className="toolbar">
        <div>
          <h1>
            Test {section.test_number} · {section.skill.charAt(0) + section.skill.slice(1).toLowerCase()} ·{" "}
            {section.title || sectionLabel(section)}
          </h1>
          <p className="subtitle" style={{ margin: 0 }}>
            {questions.length} questions · source pages {section.source_pages}
            {section.confidence !== null && ` · parse confidence ${Math.round(section.confidence * 100)}%`}
          </p>
        </div>
        <div className="spacer" />
        <Link href={`/library/${section.material_id}`} className="btn secondary small">
          Back to material
        </Link>
      </div>

      {section.instructions && (
        <div className="card" style={{ marginBottom: 16 }}>
          <h2>Instructions</h2>
          <p style={{ margin: 0, whiteSpace: "pre-wrap" }}>{section.instructions}</p>
        </div>
      )}

      {section.body && (
        <div className="card" style={{ marginBottom: 16 }}>
          <h2>{section.skill === "READING" ? "Passage" : "Content"}</h2>
          <div className="passage-text">{section.body}</div>
        </div>
      )}

      <SectionVocabulary sectionId={section.id} />

      {section.skill === "LISTENING" && (
        <TranscriptEditor sectionId={section.id} initial={section.transcript} hasAudio={!!section.audio_file_id} />
      )}

      {groups.map((group) => (
        <div key={group.id} className="card" style={{ marginBottom: 16 }}>
          <h2>{group.question_type.replaceAll("_", " ")}</h2>
          {group.instruction && <p className="subtitle">{group.instruction}</p>}
          {group.word_limit && <p className="badge due" style={{ marginBottom: 12 }}>{group.word_limit}</p>}
          {group.options.length > 0 && (
            <ul className="option-list">
              {group.options.map((o) => (
                <li key={o}>{o}</li>
              ))}
            </ul>
          )}
          {questions
            .filter((q) => (group.first_question ?? 0) <= q.question_number && q.question_number <= (group.last_question ?? 0))
            .map((q) => (
              <QuestionRow key={q.id} question={q} onSaved={replaceQuestion} />
            ))}
        </div>
      ))}

      {questions.length === 0 && (
        <div className="card empty-state">
          <h2>No questions extracted</h2>
          <p>
            The pages for this section were read but no questions could be parsed from them. The raw page text is
            kept above so nothing is lost.
          </p>
        </div>
      )}
    </>
  );
}

export default function SectionPage() {
  const params = useParams<{ id: string }>();
  return <Protected>{() => <SectionContent id={Number(params.id)} />}</Protected>;
}

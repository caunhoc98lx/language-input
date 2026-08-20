"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { useParams, useRouter } from "next/navigation";
import Protected from "@/components/Protected";
import { api } from "@/lib/api";
import StartPractice from "@/components/StartPractice";
import { SKILL_ORDER, sectionLabel } from "@/lib/library";
import type { Material, Section, Skill } from "@/lib/library";

interface Test {
  id: number;
  test_number: number;
  title: string;
  sections: Section[];
}

interface Detail {
  material: Material;
  counts: { tests: number; sections: number; questions: number; needs_review: number; missing_answers: number };
  job_id: number | null;
  job_status: string | null;
  tests: Test[];
}

function MaterialContent({ id }: { id: number }) {
  const router = useRouter();
  const [data, setData] = useState<Detail | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => {
    api.get(`/api/library/materials/${id}`).then(setData).catch((e) => setError(e.message));
  }, [id]);

  if (error) return <div className="card empty-state"><h2>Not found</h2><p>{error}</p></div>;
  if (!data) return null;

  const { material, counts, tests } = data;

  async function publish() {
    setBusy(true);
    setError("");
    try {
      await api.post(`/api/library/materials/${id}/publish`);
      setData(await api.get(`/api/library/materials/${id}`));
    } catch (e) {
      setError(e instanceof Error ? e.message : "Could not publish.");
    } finally {
      setBusy(false);
    }
  }

  async function remove() {
    if (!confirm(`Delete “${material.title}” and its uploaded files? This cannot be undone.`)) return;
    setBusy(true);
    try {
      await api.delete(`/api/library/materials/${id}`);
      router.push("/library");
    } catch (e) {
      setError(e instanceof Error ? e.message : "Could not delete.");
      setBusy(false);
    }
  }

  return (
    <>
      <div className="toolbar">
        <div>
          <h1>{material.title}</h1>
          <p className="subtitle" style={{ margin: 0 }}>
            {material.source || "Imported material"} · {counts.tests} tests · {counts.sections} sections ·{" "}
            {counts.questions} questions
          </p>
        </div>
        <div className="spacer" />
        {material.status !== "READY" && (
          <button className="btn" onClick={publish} disabled={busy || !counts.questions}>
            Publish to library
          </button>
        )}
        {tests.some((t) => t.sections.some((s) => s.skill === "LISTENING")) && (
          <Link href={`/library/${id}/audio`} className="btn secondary small">
            Audio
          </Link>
        )}
        <button className="btn secondary small" onClick={remove} disabled={busy}>
          Delete
        </button>
      </div>

      {error && <div className="error" style={{ marginBottom: 16 }}>{error}</div>}

      {(counts.needs_review > 0 || counts.missing_answers > 0) && (
        <div className="card notice" style={{ marginBottom: 20 }}>
          <strong>Needs your attention</strong>
          <ul>
            {counts.needs_review > 0 && <li>{counts.needs_review} question(s) were extracted with low confidence.</li>}
            {counts.missing_answers > 0 && (
              <li>{counts.missing_answers} question(s) have no answer yet and cannot be marked until you add one.</li>
            )}
          </ul>
        </div>
      )}

      {tests.length === 0 ? (
        <div className="card empty-state">
          <h2>No structure detected</h2>
          <p>
            The document was read, but no IELTS tests or sections were recognised in it. Open the import log
            to see what was extracted page by page.
          </p>
        </div>
      ) : (
        tests.map((test) => (
          <div key={test.id} className="card" style={{ marginBottom: 18 }}>
            <h2>{test.title || `Test ${test.test_number}`}</h2>
            {SKILL_ORDER.filter((skill) => test.sections.some((s) => s.skill === skill)).map((skill) => {
              const skillSections = test.sections.filter((s) => s.skill === (skill as Skill));
              const skillQuestions = skillSections.reduce((n, s) => n + s.question_count, 0);
              return (
                <div key={skill} className="skill-block">
                  <div className="skill-heading-row">
                    <span className="skill-heading">{skill.charAt(0) + skill.slice(1).toLowerCase()}</span>
                    {skillQuestions > 0 && (
                      <StartPractice
                        testId={test.id}
                        skill={skill}
                        label={`Full ${skill.toLowerCase()} test`}
                        className="btn secondary"
                        small
                      />
                    )}
                  </div>
                  {skillSections.map((section) => (
                    <div key={section.id} className="section-row">
                      <Link href={`/library/sections/${section.id}`} className="section-name">
                        {section.title || sectionLabel(section)}
                      </Link>
                      <span className="subtitle" style={{ margin: 0 }}>
                        {section.first_question && section.last_question
                          ? `Questions ${section.first_question}–${section.last_question}`
                          : "No question range detected"}
                      </span>
                      <span className="subtitle" style={{ margin: 0 }}>
                        p. {section.source_pages}
                      </span>
                      <span className={`badge ${section.status === "READY" ? "mastered" : "due"}`}>
                        {section.question_count} q
                        {section.status === "NEEDS_REVIEW" ? " · review" : ""}
                      </span>
                      {section.question_count > 0 && (
                        <StartPractice sectionId={section.id} label="Practise" small />
                      )}
                    </div>
                  ))}
                </div>
              );
            })}
          </div>
        ))
      )}
    </>
  );
}

export default function MaterialPage() {
  const params = useParams<{ id: string }>();
  return <Protected>{() => <MaterialContent id={Number(params.id)} />}</Protected>;
}

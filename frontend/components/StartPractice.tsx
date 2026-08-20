"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { api } from "@/lib/api";
import type { PracticeMode } from "@/lib/practice";

/** Starts (or resumes) a session and sends the learner into the practice engine. */
export default function StartPractice({
  sectionId,
  testId,
  skill,
  label = "Start practice",
  className = "btn",
  small,
}: {
  sectionId?: number;
  testId?: number;
  skill?: string;
  label?: string;
  className?: string;
  small?: boolean;
}) {
  const router = useRouter();
  const [open, setOpen] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  async function start(mode: PracticeMode) {
    setBusy(true);
    setError("");
    try {
      const payload = await api.post("/api/practice/sessions", {
        section_id: sectionId ?? null,
        test_id: testId ?? null,
        skill: skill ?? null,
        mode,
      });
      router.push(`/practice/${payload.session.id}`);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Could not start practice.");
      setBusy(false);
    }
  }

  return (
    <>
      <button className={`${className}${small ? " small" : ""}`} onClick={() => setOpen(true)}>
        {label}
      </button>
      {open && (
        <div className="modal-backdrop" onClick={() => setOpen(false)}>
          <div className="card modal" onClick={(e) => e.stopPropagation()}>
            <h2>How do you want to practise?</h2>
            <div className="mode-choice">
              <button className="mode-card" onClick={() => start("EXAM")} disabled={busy}>
                <strong>Exam mode</strong>
                <span className="subtitle">
                  Countdown timer, audio plays once, no answers or explanations until you submit.
                </span>
              </button>
              <button className="mode-card" onClick={() => start("LEARNING")} disabled={busy}>
                <strong>Learning mode</strong>
                <span className="subtitle">
                  No pressure: replay the audio, change speed, and see explanations and the
                  transcript after you answer.
                </span>
              </button>
            </div>
            {error && <div className="error">{error}</div>}
          </div>
        </div>
      )}
    </>
  );
}

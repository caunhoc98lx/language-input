"use client";

import { useState } from "react";
import { api } from "@/lib/api";
import type { User } from "@/lib/types";

const CEFR = [
  { level: "A1", note: "Beginner" },
  { level: "A2", note: "Elementary" },
  { level: "B1", note: "Intermediate" },
  { level: "B2", note: "Upper-intermediate" },
  { level: "C1", note: "Advanced" },
  { level: "C2", note: "Proficient" },
];
const BANDS = [4, 4.5, 5, 5.5, 6, 6.5, 7, 7.5, 8, 8.5, 9];
const MINUTES = [15, 30, 45, 60, 90, 120];

/** IELTS target setup - used for first-run onboarding and later from Settings. */
export default function TargetForm({
  user,
  submitLabel,
  onSaved,
}: {
  user: User;
  submitLabel: string;
  onSaved: (user: User) => void;
}) {
  const [name, setName] = useState(user.name);
  const [cefr, setCefr] = useState(user.cefr_level || "");
  const [current, setCurrent] = useState<number | null>(user.ielts_current);
  const [target, setTarget] = useState<number | null>(user.ielts_target ?? 7);
  const [targetDate, setTargetDate] = useState(user.target_date || "");
  const [minutes, setMinutes] = useState(user.daily_goal_minutes || 30);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");

  const gap = current !== null && target !== null ? target - current : null;

  async function save() {
    setError("");
    if (target === null) return setError("Choose a target band.");
    if (current !== null && target < current) {
      return setError("Your target should be at least your current band.");
    }
    setSaving(true);
    try {
      const updated = await api.patch("/api/profile", {
        name: name.trim(),
        cefr_level: cefr,
        ielts_current: current,
        ielts_target: target,
        target_date: targetDate,
        daily_goal_minutes: minutes,
      });
      onSaved(updated);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Could not save.");
    } finally {
      setSaving(false);
    }
  }

  return (
    <>
      <div className="field">
        <label htmlFor="name">What should I call you?</label>
        <input id="name" value={name} onChange={(e) => setName(e.target.value)} placeholder="Your name" />
      </div>

      <div className="field">
        <label>Current English level</label>
        <p className="hint">CEFR level, if you know it. It tunes the difficulty of generated practice.</p>
        <div className="option-row">
          {CEFR.map((c) => (
            <button
              key={c.level}
              type="button"
              className={`chip-select ${cefr === c.level ? "active" : ""}`}
              onClick={() => setCefr(cefr === c.level ? "" : c.level)}
            >
              {c.level} · {c.note}
            </button>
          ))}
        </div>
      </div>

      <div className="field">
        <label>Current IELTS band</label>
        <p className="hint">Your latest score, or your best guess. Practice results replace it later.</p>
        <div className="option-row">
          {BANDS.map((b) => (
            <button
              key={b}
              type="button"
              className={`chip-select ${current === b ? "active" : ""}`}
              onClick={() => setCurrent(current === b ? null : b)}
            >
              {b.toFixed(1)}
            </button>
          ))}
        </div>
      </div>

      <div className="field">
        <label>Target band</label>
        <div className="option-row">
          {BANDS.map((b) => (
            <button
              key={b}
              type="button"
              className={`chip-select ${target === b ? "active" : ""}`}
              onClick={() => setTarget(b)}
            >
              {b.toFixed(1)}
            </button>
          ))}
        </div>
        {gap !== null && gap > 0 && (
          <div className="gap-badge">🎯 {gap.toFixed(1)} band{gap > 0.5 ? "s" : ""} to go</div>
        )}
      </div>

      <div className="field">
        <label htmlFor="target-date">Test date</label>
        <p className="hint">Optional. Used to pace your plan.</p>
        <input id="target-date" type="date" value={targetDate} onChange={(e) => setTargetDate(e.target.value)} />
      </div>

      <div className="field">
        <label>Study time per day</label>
        <div className="option-row">
          {MINUTES.map((m) => (
            <button
              key={m}
              type="button"
              className={`chip-select ${minutes === m ? "active" : ""}`}
              onClick={() => setMinutes(m)}
            >
              {m} min
            </button>
          ))}
        </div>
      </div>

      <button className="btn" onClick={save} disabled={saving}>
        {saving ? "Saving…" : submitLabel}
      </button>
      {error && <div className="error">{error}</div>}
    </>
  );
}

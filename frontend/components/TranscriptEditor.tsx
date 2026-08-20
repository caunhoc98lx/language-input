"use client";

import { useState } from "react";
import { api } from "@/lib/api";

/** Edit a listening transcript, or generate one from the audio when the book
 *  did not print it. Generation is opt-in: it costs a model call. */
export default function TranscriptEditor({
  sectionId,
  initial,
  hasAudio,
}: {
  sectionId: number;
  initial: string;
  hasAudio: boolean;
}) {
  const [text, setText] = useState(initial || "");
  const [saved, setSaved] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  async function save() {
    setBusy(true);
    setError("");
    try {
      await api.patch(`/api/library/sections/${sectionId}/transcript`, { transcript: text });
      setSaved(true);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Could not save.");
    } finally {
      setBusy(false);
    }
  }

  async function generate() {
    setBusy(true);
    setError("");
    try {
      const res = await api.post(`/api/library/sections/${sectionId}/transcribe`);
      setText(res.transcript);
      setSaved(true);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Could not transcribe the audio.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="card" style={{ marginBottom: 16 }}>
      <div style={{ display: "flex", alignItems: "center", gap: 12, flexWrap: "wrap" }}>
        <h2 style={{ margin: 0, flex: 1 }}>Transcript</h2>
        {hasAudio && !text.trim() && (
          <button className="btn secondary small" onClick={generate} disabled={busy}>
            {busy ? "Transcribing…" : "Generate with AI"}
          </button>
        )}
        <button className="btn small" onClick={save} disabled={busy || text === initial}>
          {busy ? "Saving…" : "Save"}
        </button>
      </div>
      <textarea
        rows={8}
        value={text}
        onChange={(e) => {
          setText(e.target.value);
          setSaved(false);
        }}
        placeholder={
          hasAudio
            ? "Paste the transcript from your book, or generate one from the audio."
            : "Paste the transcript from your book. Link audio to this section to generate one."
        }
        style={{ width: "100%", marginTop: 12 }}
      />
      {saved && <p className="subtitle" style={{ margin: "6px 0 0", color: "var(--success)" }}>Saved.</p>}
      {error && <div className="error">{error}</div>}
    </div>
  );
}

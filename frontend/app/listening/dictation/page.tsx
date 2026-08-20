"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import Protected from "@/components/Protected";
import { api } from "@/lib/api";
import AudioPlayer from "@/components/AudioPlayer";
import type { PracticeSection } from "@/lib/practice";

interface DictationOption {
  id: number;
  title: string;
  test_number: number;
  material_id: number;
  material_title: string;
  words: number;
}

interface DictationTarget {
  id: number;
  title: string;
  test_number: number;
  audio: { file_id: number; start: number | null; end: number | null };
  words: number;
}

interface DictationResult {
  words: { word: string; status: "ok" | "missing" | "wrong"; typed?: string }[];
  extra: string[];
  correct: number;
  total: number;
  missing: number;
  wrong: number;
  accuracy: number;
  transcript: string;
}

function DictationContent() {
  const [options, setOptions] = useState<DictationOption[] | null>(null);
  const [target, setTarget] = useState<DictationTarget | null>(null);
  const [typed, setTyped] = useState("");
  const [result, setResult] = useState<DictationResult | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => {
    api.get("/api/dictation/sections").then((d) => setOptions(d.sections));
  }, []);

  async function choose(id: number) {
    setError("");
    setResult(null);
    setTyped("");
    try {
      setTarget(await api.get(`/api/dictation/sections/${id}`));
    } catch (e) {
      setError(e instanceof Error ? e.message : "Could not load that section.");
    }
  }

  async function check() {
    if (!target) return;
    setBusy(true);
    try {
      setResult(await api.post(`/api/dictation/sections/${target.id}/check`, { typed }));
    } catch (e) {
      setError(e instanceof Error ? e.message : "Could not check your dictation.");
    } finally {
      setBusy(false);
    }
  }

  if (!options) return null;

  if (options.length === 0) {
    return (
      <div className="card empty-state">
        <h2>Nothing to dictate yet</h2>
        <p>
          Dictation needs a listening section that has both audio and a transcript. Import a listening
          test, attach its audio, and add or generate a transcript.
        </p>
        <Link href="/library" className="btn" style={{ marginTop: 10, display: "inline-flex" }}>
          Open library
        </Link>
      </div>
    );
  }

  const playerSections: PracticeSection[] = target
    ? [{
        id: target.id, skill: "LISTENING", section_number: 1, title: target.title,
        instructions: "", body: "", transcript: "", first_question: null, last_question: null,
        audio: target.audio,
      }]
    : [];

  return (
    <>
      <h1>Dictation</h1>
      <p className="subtitle">
        Listen and type exactly what you hear. Every missed or mis-heard word is shown against the
        transcript.
      </p>

      <div className="card" style={{ marginBottom: 16 }}>
        <h2>Choose a section</h2>
        <div className="option-row">
          {options.map((o) => (
            <button
              key={o.id}
              className={`chip-select ${target?.id === o.id ? "active" : ""}`}
              onClick={() => choose(o.id)}
            >
              {o.material_title} · Test {o.test_number} · {o.title}
            </button>
          ))}
        </div>
      </div>

      {error && <div className="error">{error}</div>}

      {target && (
        <>
          <AudioPlayer sections={playerSections} examMode={false} />

          <div className="card">
            <h2>What did you hear?</h2>
            <textarea
              rows={8}
              value={typed}
              onChange={(e) => setTyped(e.target.value)}
              placeholder="Type what you hear. Replay and slow the audio as often as you like."
              style={{ width: "100%" }}
            />
            <div style={{ display: "flex", alignItems: "center", gap: 12, marginTop: 12 }}>
              <button className="btn" onClick={check} disabled={busy || !typed.trim()}>
                {busy ? "Checking…" : "Check my dictation"}
              </button>
              <span className="subtitle" style={{ margin: 0 }}>
                {typed.trim() ? typed.trim().split(/\s+/).length : 0} of about {target.words} words
              </span>
            </div>
          </div>
        </>
      )}

      {result && (
        <div className="card" style={{ marginTop: 16 }}>
          <div className="result-stats">
            <div>
              <div className="num">{Math.round(result.accuracy * 100)}%</div>
              <div className="label">Words caught</div>
            </div>
            <div>
              <div className="num">{result.missing}</div>
              <div className="label">Missed</div>
            </div>
            <div>
              <div className="num">{result.wrong}</div>
              <div className="label">Mis-heard</div>
            </div>
            <div>
              <div className="num">{result.extra.length}</div>
              <div className="label">Extra words</div>
            </div>
          </div>

          <h2 style={{ marginTop: 20 }}>Transcript</h2>
          <p className="dictation-diff">
            {result.words.map((w, i) => (
              <span key={i} className={`dict-${w.status}`} title={w.typed ? `you typed: ${w.typed}` : undefined}>
                {w.word}{" "}
              </span>
            ))}
          </p>
          {result.extra.length > 0 && (
            <p className="subtitle">Words you typed that were not said: {result.extra.join(", ")}</p>
          )}
        </div>
      )}
    </>
  );
}

export default function DictationPage() {
  return <Protected>{() => <DictationContent />}</Protected>;
}

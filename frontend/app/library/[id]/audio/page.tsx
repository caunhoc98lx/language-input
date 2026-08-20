"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import Link from "next/link";
import { useParams } from "next/navigation";
import Protected from "@/components/Protected";
import { api } from "@/lib/api";
import { formatBytes } from "@/lib/library";

interface AudioFile {
  id: number;
  filename: string;
  size_bytes: number;
  duration_sec: number | null;
}

interface AudioSection {
  id: number;
  section_number: number;
  title: string;
  test_number: number;
  audio_file_id: number | null;
  audio_confidence: number | null;
}

interface Suggestion {
  section_id: number;
  file_id: number | null;
  filename: string | null;
  confidence: number;
  reason: string;
}

interface AudioData {
  sections: AudioSection[];
  files: AudioFile[];
  suggestions: Suggestion[];
  summary: { matched: number; auto: number; needs_confirmation: number; unmatched: number; total: number };
  auto_link_threshold: number;
}

const API_URL = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

function AudioContent({ materialId }: { materialId: number }) {
  const [data, setData] = useState<AudioData | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [uploading, setUploading] = useState(false);
  const inputRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    api
      .get(`/api/library/materials/${materialId}/audio`)
      .then(setData)
      .catch((e) => setError(e.message));
  }, [materialId]);

  const load = useCallback(async () => {
    setData(await api.get(`/api/library/materials/${materialId}/audio`));
  }, [materialId]);

  if (error) return <div className="card empty-state"><h2>Not available</h2><p>{error}</p></div>;
  if (!data) return null;

  async function upload(files: FileList | null) {
    if (!files?.length) return;
    setUploading(true);
    setError("");
    const form = new FormData();
    Array.from(files).forEach((f) => form.append("files", f));
    try {
      const res = await fetch(`${API_URL}/api/library/materials/${materialId}/audio`, {
        method: "POST",
        credentials: "include",
        body: form,
      });
      const body = await res.json().catch(() => ({}));
      if (!res.ok) throw new Error(body.detail || "Upload failed.");
      await api.post(`/api/library/materials/${materialId}/audio/match`);
      await load();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Upload failed.");
    } finally {
      setUploading(false);
    }
  }

  async function link(sectionId: number, fileId: number | null) {
    setBusy(true);
    try {
      await api.patch(`/api/library/sections/${sectionId}/audio`, { file_id: fileId });
      await load();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Could not link the audio.");
    } finally {
      setBusy(false);
    }
  }

  async function applyAll() {
    setBusy(true);
    try {
      await api.post(`/api/library/materials/${materialId}/audio/match?apply_all=true`);
      await load();
    } finally {
      setBusy(false);
    }
  }

  const suggestionFor = (sectionId: number) => data.suggestions.find((s) => s.section_id === sectionId);
  const fileName = (id: number | null) => data.files.find((f) => f.id === id)?.filename ?? "";

  return (
    <>
      <div className="toolbar">
        <div>
          <h1>Audio matching</h1>
          <p className="subtitle" style={{ margin: 0 }}>
            {data.summary.matched} of {data.summary.total} listening sections have audio
            {data.summary.needs_confirmation > 0 && ` · ${data.summary.needs_confirmation} to confirm`}
          </p>
        </div>
        <div className="spacer" />
        {data.summary.needs_confirmation > 0 && (
          <button className="btn secondary small" onClick={applyAll} disabled={busy}>
            Accept all suggestions
          </button>
        )}
        <Link href={`/library/${materialId}`} className="btn secondary small">
          Back to material
        </Link>
      </div>

      <div className="card" style={{ marginBottom: 18 }}>
        <div style={{ display: "flex", alignItems: "center", gap: 12, flexWrap: "wrap" }}>
          <div style={{ flex: 1 }}>
            <h2 style={{ margin: 0 }}>Audio files</h2>
            <p className="subtitle" style={{ margin: "4px 0 0" }}>
              {data.files.length} uploaded · MP3, M4A, WAV or a ZIP of them
            </p>
          </div>
          <button className="btn" onClick={() => inputRef.current?.click()} disabled={uploading}>
            {uploading ? "Uploading…" : "Upload audio"}
          </button>
          <input
            ref={inputRef}
            type="file"
            multiple
            hidden
            accept=".mp3,.m4a,.wav,.zip"
            onChange={(e) => upload(e.target.files)}
          />
        </div>
        {data.files.length > 0 && (
          <div className="file-list" style={{ marginTop: 14 }}>
            {data.files.map((f) => (
              <div key={f.id} className="file-row">
                <span className="file-name">{f.filename}</span>
                <span className="subtitle" style={{ margin: 0 }}>{formatBytes(f.size_bytes)}</span>
              </div>
            ))}
          </div>
        )}
      </div>

      {data.sections.length === 0 ? (
        <div className="card empty-state">
          <h2>No listening sections</h2>
          <p>This material has no listening sections to attach audio to.</p>
        </div>
      ) : (
        <div className="card">
          <h2>Sections</h2>
          {data.sections.map((section) => {
            const suggestion = suggestionFor(section.id);
            const linked = section.audio_file_id;
            return (
              <div key={section.id} className="match-row">
                <div className="match-label">
                  <strong>Test {section.test_number}</strong>
                  <span className="subtitle" style={{ margin: 0 }}>{section.title}</span>
                </div>

                <select
                  value={linked ?? suggestion?.file_id ?? ""}
                  disabled={busy}
                  onChange={(e) => link(section.id, e.target.value ? Number(e.target.value) : null)}
                >
                  <option value="">No audio</option>
                  {data.files.map((f) => (
                    <option key={f.id} value={f.id}>
                      {f.filename}
                    </option>
                  ))}
                </select>

                {linked ? (
                  <span className="badge mastered">
                    Linked{section.audio_confidence !== null && section.audio_confidence < 1
                      ? ` · ${Math.round(section.audio_confidence * 100)}%`
                      : ""}
                  </span>
                ) : suggestion?.file_id ? (
                  <>
                    <span className="badge due">
                      {Math.round(suggestion.confidence * 100)}% · {suggestion.reason}
                    </span>
                    <button
                      className="btn small"
                      disabled={busy}
                      onClick={() => link(section.id, suggestion.file_id)}
                    >
                      Confirm
                    </button>
                  </>
                ) : (
                  <span className="subtitle" style={{ margin: 0 }}>
                    Please select the audio for this section.
                  </span>
                )}

                {linked && (
                  <button className="btn secondary small" disabled={busy} onClick={() => link(section.id, null)}>
                    Unlink
                  </button>
                )}
                {linked && <span className="subtitle" style={{ margin: 0 }}>{fileName(linked)}</span>}
              </div>
            );
          })}
        </div>
      )}
    </>
  );
}

export default function AudioMatchingPage() {
  const params = useParams<{ id: string }>();
  return <Protected>{() => <AudioContent materialId={Number(params.id)} />}</Protected>;
}

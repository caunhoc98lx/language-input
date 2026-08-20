"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import Protected from "@/components/Protected";
import { api } from "@/lib/api";
import { formatBytes, uploadImport } from "@/lib/library";
import type { ImportJob } from "@/lib/library";

const STEPS = ["Upload", "Analyse", "Review", "Publish"];
const ACCEPT = ".pdf,.mp3,.m4a,.wav,.zip";
const FINISHED = ["READY", "FAILED", "CANCELLED"];

function StepBar({ current }: { current: number }) {
  return (
    <ol className="wizard-steps">
      {STEPS.map((label, i) => (
        <li key={label} className={i === current ? "active" : i < current ? "done" : ""}>
          <span className="step">{i < current ? "✓" : i + 1}</span>
          {label}
        </li>
      ))}
    </ol>
  );
}

function ImportContent() {
  const router = useRouter();
  const [step, setStep] = useState(0);
  const [files, setFiles] = useState<File[]>([]);
  const [title, setTitle] = useState("");
  const [source, setSource] = useState("");
  const [description, setDescription] = useState("");
  const [dragging, setDragging] = useState(false);
  const [uploadPct, setUploadPct] = useState(0);
  const [uploading, setUploading] = useState(false);
  const [error, setError] = useState("");
  const [duplicates, setDuplicates] = useState<{ filename: string; material: string }[]>([]);
  const [job, setJob] = useState<ImportJob | null>(null);
  const [publishing, setPublishing] = useState(false);
  const cancelUpload = useRef<() => void>(null);
  const inputRef = useRef<HTMLInputElement>(null);

  const addFiles = useCallback((incoming: FileList | null) => {
    if (!incoming) return;
    const list = Array.from(incoming);
    setFiles((prev) => {
      const seen = new Set(prev.map((f) => f.name + f.size));
      return [...prev, ...list.filter((f) => !seen.has(f.name + f.size))];
    });
    setTitle((prev) => prev || (list[0]?.name.replace(/\.[^.]+$/, "") ?? ""));
  }, []);

  // Poll the job while it is running. The server, not this page, owns the work,
  // so closing the tab does not stop the import.
  useEffect(() => {
    if (!job || FINISHED.includes(job.status)) return;
    const timer = setInterval(async () => {
      try {
        const next: ImportJob = await api.get(`/api/library/jobs/${job.id}`);
        setJob(next);
        if (next.status === "READY") setStep(2);
      } catch {
        /* transient network error - the next tick retries */
      }
    }, 1200);
    return () => clearInterval(timer);
  }, [job]);

  async function startUpload() {
    setError("");
    if (!files.some((f) => f.name.toLowerCase().endsWith(".pdf"))) {
      setError("Add the PDF for this material.");
      return;
    }
    if (!title.trim()) {
      setError("Give the material a name.");
      return;
    }
    const form = new FormData();
    form.append("title", title);
    form.append("source", source);
    form.append("description", description);
    files.forEach((f) => form.append("files", f));

    setUploading(true);
    setUploadPct(0);
    const { promise, cancel } = uploadImport(form, setUploadPct);
    cancelUpload.current = cancel;
    try {
      const created = await promise;
      setDuplicates(created.duplicates || []);
      setStep(1);
      setJob(await api.get(`/api/library/jobs/${created.job_id}`));
    } catch (e) {
      setError(e instanceof Error ? e.message : "Upload failed.");
    } finally {
      setUploading(false);
      cancelUpload.current = null;
    }
  }

  async function cancelJob() {
    if (!job) return;
    await api.post(`/api/library/jobs/${job.id}/cancel`);
    setJob(await api.get(`/api/library/jobs/${job.id}`));
  }

  async function retryJob() {
    if (!job) return;
    await api.post(`/api/library/jobs/${job.id}/retry`);
    setJob(await api.get(`/api/library/jobs/${job.id}`));
  }

  async function publish() {
    if (!job) return;
    setPublishing(true);
    setError("");
    try {
      await api.post(`/api/library/materials/${job.material_id}/publish`);
      router.push(`/library/${job.material_id}`);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Could not publish.");
      setPublishing(false);
    }
  }

  return (
    <>
      <div className="toolbar">
        <div>
          <h1>Import IELTS material</h1>
          <p className="subtitle" style={{ margin: 0 }}>
            Upload material you have the right to use. Imports stay private to your account.
          </p>
        </div>
        <div className="spacer" />
        <Link href="/library" className="btn secondary small">
          Back to library
        </Link>
      </div>

      <StepBar current={step} />

      {step === 0 && (
        <div className="card">
          <div
            className={`dropzone ${dragging ? "dragging" : ""}`}
            onDragOver={(e) => {
              e.preventDefault();
              setDragging(true);
            }}
            onDragLeave={() => setDragging(false)}
            onDrop={(e) => {
              e.preventDefault();
              setDragging(false);
              addFiles(e.dataTransfer.files);
            }}
            onClick={() => inputRef.current?.click()}
          >
            <strong>Drop your PDF here</strong>
            <p className="subtitle" style={{ margin: "6px 0 0" }}>
              or click to choose files · PDF, MP3, M4A, WAV, ZIP
            </p>
            <input
              ref={inputRef}
              type="file"
              multiple
              accept={ACCEPT}
              hidden
              onChange={(e) => addFiles(e.target.files)}
            />
          </div>

          {files.length > 0 && (
            <div className="file-list">
              {files.map((f) => (
                <div key={f.name + f.size} className="file-row">
                  <span className="file-name">{f.name}</span>
                  <span className="subtitle" style={{ margin: 0 }}>
                    {formatBytes(f.size)}
                  </span>
                  <button
                    className="btn secondary small"
                    onClick={() => setFiles((prev) => prev.filter((x) => x !== f))}
                    disabled={uploading}
                  >
                    Remove
                  </button>
                </div>
              ))}
            </div>
          )}

          <div className="field" style={{ marginTop: 20 }}>
            <label htmlFor="title">Material name</label>
            <input id="title" value={title} onChange={(e) => setTitle(e.target.value)} placeholder="e.g. My IELTS practice book" />
          </div>
          <div className="field">
            <label htmlFor="source">Book / source</label>
            <input id="source" value={source} onChange={(e) => setSource(e.target.value)} placeholder="Optional" />
          </div>
          <div className="field">
            <label htmlFor="description">Description</label>
            <input id="description" value={description} onChange={(e) => setDescription(e.target.value)} placeholder="Optional" />
          </div>

          {uploading && (
            <div style={{ marginBottom: 16 }}>
              <div className="progress-bar" style={{ maxWidth: "none" }}>
                <div className="progress-bar-fill" style={{ width: `${Math.round(uploadPct * 100)}%` }} />
              </div>
              <p className="subtitle" style={{ margin: "6px 0 0" }}>
                Uploading… {Math.round(uploadPct * 100)}%
              </p>
            </div>
          )}

          <div style={{ display: "flex", gap: 10 }}>
            <button className="btn" onClick={startUpload} disabled={uploading || files.length === 0}>
              {uploading ? "Uploading…" : "Upload and analyse"}
            </button>
            {uploading && (
              <button className="btn secondary" onClick={() => cancelUpload.current?.()}>
                Cancel
              </button>
            )}
          </div>
          {error && <div className="error">{error}</div>}
        </div>
      )}

      {step >= 1 && job && (
        <>
          <div className="card">
            <div style={{ display: "flex", alignItems: "baseline", gap: 12 }}>
              <h2 style={{ margin: 0, flex: 1 }}>
                {job.status === "READY"
                  ? "Analysis complete"
                  : FINISHED.includes(job.status)
                    ? `Import ${job.status.toLowerCase()}`
                    : "Analysing your document…"}
              </h2>
              {!FINISHED.includes(job.status) && (
                <button className="btn secondary small" onClick={cancelJob}>
                  Cancel import
                </button>
              )}
              {(job.status === "FAILED" || job.status === "CANCELLED") && (
                <button className="btn small" onClick={retryJob}>
                  Resume import
                </button>
              )}
            </div>

            {job.total_pages > 0 && (
              <div style={{ margin: "14px 0" }}>
                <div className="progress-bar" style={{ maxWidth: "none" }}>
                  <div className="progress-bar-fill" style={{ width: `${Math.round(job.progress * 100)}%` }} />
                </div>
                <p className="subtitle" style={{ margin: "6px 0 0" }}>
                  {job.processed_pages} of {job.total_pages} pages
                </p>
              </div>
            )}

            <ul className="job-steps">
              {job.steps.map((s) => (
                <li key={s.step} className={s.status}>
                  <span className="mark">{s.status === "done" ? "✓" : s.status === "running" ? "⏳" : "!"}</span>
                  <span style={{ flex: 1 }}>{s.step}</span>
                  <span className="subtitle" style={{ margin: 0 }}>
                    {s.detail}
                  </span>
                </li>
              ))}
            </ul>

            {job.error && <div className="error">{job.error}</div>}
          </div>

          {duplicates.length > 0 && (
            <div className="card notice">
              <strong>Already imported</strong>
              <ul>
                {duplicates.map((d) => (
                  <li key={d.filename}>
                    {d.filename} matches the file in “{d.material}”. This import created a separate copy.
                  </li>
                ))}
              </ul>
            </div>
          )}

          {job.warnings.length > 0 && (
            <div className="card notice">
              <strong>{job.warnings.length} warning{job.warnings.length === 1 ? "" : "s"}</strong>
              <ul>
                {job.warnings.map((w) => (
                  <li key={w}>{w}</li>
                ))}
              </ul>
            </div>
          )}

          {job.status === "READY" && (
            <div className="card" style={{ display: "flex", alignItems: "center", gap: 14 }}>
              <div style={{ flex: 1 }}>
                <h2 style={{ margin: 0 }}>Review before publishing</h2>
                <p className="subtitle" style={{ margin: "4px 0 0" }}>
                  Check the detected tests, sections and questions, then publish to your library.
                </p>
              </div>
              <Link href={`/library/${job.material_id}`} className="btn secondary">
                Review content
              </Link>
              <button className="btn" onClick={publish} disabled={publishing}>
                {publishing ? "Publishing…" : "Publish to library"}
              </button>
            </div>
          )}
        </>
      )}
    </>
  );
}

export default function ImportPage() {
  return <Protected>{() => <ImportContent />}</Protected>;
}

"use client";

import { useEffect, useRef, useState } from "react";
import Link from "next/link";
import { useParams, useRouter } from "next/navigation";
import Protected from "@/components/Protected";
import { api } from "@/lib/api";
import { formatDuration } from "@/lib/practice";

interface Prompt {
  id: number;
  title: string;
  instructions: string;
  body: string;
  test_number: number;
  material_title: string;
}

const DRAFT_KEY = (id: number) => `lexi-writing-draft-${id}`;

function EditorContent({ sectionId }: { sectionId: number }) {
  const router = useRouter();
  const [prompt, setPrompt] = useState<Prompt | null>(null);
  const [essay, setEssay] = useState("");
  const [elapsed, setElapsed] = useState(0);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [savedAt, setSavedAt] = useState("");
  const essayRef = useRef("");

  useEffect(() => {
    api
      .get("/api/writing/prompts")
      .then((d) => {
        const found = d.prompts.find((p: Prompt) => p.id === sectionId);
        if (!found) setError("That writing task was not found.");
        setPrompt(found ?? null);
        const draft = localStorage.getItem(DRAFT_KEY(sectionId));
        if (draft) setEssay(draft);
      })
      .catch((e) => setError(e.message));
  }, [sectionId]);

  // Draft autosave. ponytail: localStorage, not a server draft table - a draft
  // matters only on the machine it is being written on.
  useEffect(() => {
    essayRef.current = essay;
  }, [essay]);

  useEffect(() => {
    const t = setInterval(() => {
      setElapsed((e) => e + 1);
      if (essayRef.current) {
        localStorage.setItem(DRAFT_KEY(sectionId), essayRef.current);
        setSavedAt(new Date().toLocaleTimeString());
      }
    }, 5000);
    return () => clearInterval(t);
  }, [sectionId]);

  // Ctrl/Cmd+S saves the draft rather than the browser's page.
  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      if ((e.metaKey || e.ctrlKey) && e.key === "s") {
        e.preventDefault();
        localStorage.setItem(DRAFT_KEY(sectionId), essayRef.current);
        setSavedAt(new Date().toLocaleTimeString());
      }
    };
    window.addEventListener("keydown", handler);
    return () => window.removeEventListener("keydown", handler);
  }, [sectionId]);

  const words = essay.trim() ? essay.trim().split(/\s+/).length : 0;

  async function submit() {
    setBusy(true);
    setError("");
    try {
      const res = await api.post("/api/writing/submissions", {
        section_id: sectionId,
        response: essay,
        duration_sec: elapsed * 5,
      });
      localStorage.removeItem(DRAFT_KEY(sectionId));
      router.push(`/writing/submissions/${res.id}`);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Could not submit.");
      setBusy(false);
    }
  }

  if (error && !prompt) return <div className="card empty-state"><h2>Not found</h2><p>{error}</p></div>;
  if (!prompt) return null;

  return (
    <>
      <div className="practice-bar">
        <div>
          <strong>{prompt.title}</strong>
          <span className="subtitle" style={{ margin: "0 0 0 10px" }}>
            {prompt.material_title} · Test {prompt.test_number}
          </span>
        </div>
        <div className="spacer" />
        <span className="timer">{formatDuration(elapsed * 5)}</span>
        <span className={`subtitle ${words < 150 ? "" : ""}`} style={{ margin: 0 }}>
          {words} words
        </span>
        <button className="btn" onClick={submit} disabled={busy || words < 40}>
          {busy ? "Marking…" : "Submit for marking"}
        </button>
        <Link href="/writing" className="btn secondary small">
          Back
        </Link>
      </div>

      <div className="card" style={{ marginBottom: 16 }}>
        {prompt.instructions && <p className="subtitle">{prompt.instructions}</p>}
        <div className="passage-body">{prompt.body}</div>
      </div>

      <div className="card">
        <textarea
          rows={20}
          value={essay}
          onChange={(e) => setEssay(e.target.value)}
          placeholder="Write your answer here. Your draft is saved on this device as you go."
          style={{ width: "100%" }}
        />
        <div style={{ display: "flex", gap: 12, marginTop: 10, alignItems: "center" }}>
          <span className="subtitle" style={{ margin: 0 }}>
            {savedAt ? `Draft saved ${savedAt}` : "Draft saves automatically"}
          </span>
          <span className="subtitle" style={{ margin: 0 }}>
            {words < 150 ? "Task 1 needs 150+ words, Task 2 needs 250+." : ""}
          </span>
        </div>
        {error && <div className="error">{error}</div>}
      </div>
    </>
  );
}

export default function WritingEditorPage() {
  const params = useParams<{ id: string }>();
  return <Protected>{() => <EditorContent sectionId={Number(params.id)} />}</Protected>;
}

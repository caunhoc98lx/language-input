"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { useParams } from "next/navigation";
import FeedbackReport from "@/components/FeedbackReport";
import Protected from "@/components/Protected";
import WordLookup from "@/components/WordLookup";
import { api } from "@/lib/api";
import type { Feedback } from "@/components/FeedbackReport";

interface Submission {
  id: number;
  kind: "WRITING" | "SPEAKING";
  task_label: string;
  prompt: string;
  response: string;
  band: number | null;
  criteria: Record<string, number | null>;
  feedback: Feedback;
  word_count: number;
  duration_sec: number | null;
  has_audio: boolean;
  created_at: string;
}

const API_URL = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

const CRITERIA = {
  WRITING: [
    { key: "task_response", label: "Task Response" },
    { key: "coherence_cohesion", label: "Coherence" },
    { key: "lexical_resource", label: "Lexical" },
    { key: "grammatical_range", label: "Grammar" },
  ],
  SPEAKING: [
    { key: "fluency_coherence", label: "Fluency" },
    { key: "lexical_resource", label: "Lexical" },
    { key: "grammatical_range", label: "Grammar" },
    { key: "pronunciation", label: "Pronunciation" },
  ],
};

function SubmissionContent({ id }: { id: number }) {
  const [data, setData] = useState<Submission | null>(null);
  const [error, setError] = useState("");

  useEffect(() => {
    api.get(`/api/submissions/${id}`).then(setData).catch((e) => setError(e.message));
  }, [id]);

  if (error) return <div className="card empty-state"><h2>Not found</h2><p>{error}</p></div>;
  if (!data) return null;

  const speaking = data.kind === "SPEAKING";

  return (
    <>
      <div className="toolbar">
        <div>
          <h1>{data.task_label}</h1>
          <p className="subtitle" style={{ margin: 0 }}>
            {speaking ? "Speaking" : "Writing"} · {data.word_count} words ·{" "}
            {data.created_at.slice(0, 16).replace("T", " ")}
          </p>
        </div>
        <div className="spacer" />
        <Link href={speaking ? "/speaking" : "/writing"} className="btn secondary small">
          Back
        </Link>
      </div>

      <FeedbackReport feedback={data.feedback} criteria={CRITERIA[data.kind]} band={data.band} />

      <div className="card" style={{ marginTop: 16 }}>
        <h2>{speaking ? "What you said" : "Your answer"}</h2>
        {data.has_audio && (
          <audio
            controls
            src={`${API_URL}/api/submissions/${data.id}/audio`}
            crossOrigin="use-credentials"
            style={{ width: "100%", margin: "10px 0" }}
          />
        )}
        <WordLookup>
          <div className="passage-body">{data.response}</div>
        </WordLookup>
      </div>

      <div className="card" style={{ marginTop: 16 }}>
        <h2>The task</h2>
        <div className="passage-body">{data.prompt}</div>
      </div>
    </>
  );
}

export default function SubmissionPage() {
  const params = useParams<{ id: string }>();
  return <Protected>{() => <SubmissionContent id={Number(params.id)} />}</Protected>;
}

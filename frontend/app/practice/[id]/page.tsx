"use client";

import { useEffect, useState } from "react";
import { useParams } from "next/navigation";
import PracticeEngine from "@/components/PracticeEngine";
import Protected from "@/components/Protected";
import { api } from "@/lib/api";
import type { PracticePayload } from "@/lib/practice";

function PracticeContent({ id }: { id: number }) {
  const [payload, setPayload] = useState<PracticePayload | null>(null);
  const [error, setError] = useState("");

  useEffect(() => {
    api.get(`/api/practice/sessions/${id}`).then(setPayload).catch((e) => setError(e.message));
  }, [id]);

  if (error) return <div className="card empty-state"><h2>Session not found</h2><p>{error}</p></div>;
  if (!payload) return null;
  return <PracticeEngine payload={payload} />;
}

export default function PracticeSessionPage() {
  const params = useParams<{ id: string }>();
  return <Protected>{() => <PracticeContent id={Number(params.id)} />}</Protected>;
}

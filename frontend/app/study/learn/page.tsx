"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { useSearchParams } from "next/navigation";
import Protected from "@/components/Protected";
import QuestionCard from "@/components/QuestionCard";
import StudyModeTabs from "@/components/StudyModeTabs";
import { api } from "@/lib/api";
import type { LearnCard } from "@/lib/types";

function LearnContent() {
  const setId = useSearchParams().get("set_id") || "";
  const [queue, setQueue] = useState<LearnCard[] | null>(null);
  const [i, setI] = useState(0);

  useEffect(() => {
    const params = setId ? `?set_id=${setId}` : "";
    api.get(`/api/study/learn${params}`).then((data) => setQueue(data.queue));
  }, [setId]);

  if (!queue) return null;

  function next(wasWrong: boolean) {
    if (wasWrong) {
      // Missed cards aren't done after one miss - they resurface a few
      // cards later in the same session, same as Anki mode.
      setQueue((prev) => {
        if (!prev) return prev;
        const q = [...prev];
        q.splice(Math.min(q.length, i + 4), 0, q[i]);
        return q;
      });
    }
    setI((prev) => prev + 1);
  }

  return (
    <>
      <div className="toolbar">
        <h1 style={{ margin: 0 }}>Study session</h1>
        <div className="spacer" />
        <StudyModeTabs active="learn" />
      </div>

      {queue.length === 0 ? (
        <div className="card empty-state">
          <h2>No cards to study right now</h2>
          <p>Nothing is due, and you have no new words. Add more vocabulary or check back later.</p>
          <Link href="/vocabulary/new" className="btn" style={{ marginTop: 10, display: "inline-flex" }}>Add vocabulary</Link>
        </div>
      ) : i >= queue.length ? (
        <div className="card empty-state">
          <h2>Session complete 🎉</h2>
          <p>{queue.length} cards reviewed.</p>
          <Link href="/dashboard" className="btn" style={{ marginTop: 10, display: "inline-flex" }}>Back to dashboard</Link>
        </div>
      ) : (
        <div className="study-wrap">
          <div className="progress-bar"><div className="progress-bar-fill" style={{ width: `${(100 * i) / queue.length}%` }} /></div>
          <QuestionCard key={i} card={queue[i]} onNext={next} />
        </div>
      )}
    </>
  );
}

export default function LearnPage() {
  return <Protected>{() => <LearnContent />}</Protected>;
}

"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import Protected from "@/components/Protected";
import { api } from "@/lib/api";
import type { Material } from "@/lib/library";

const STATUS_LABEL: Record<Material["status"], { text: string; className: string }> = {
  IMPORTING: { text: "Importing", className: "badge due" },
  NEEDS_REVIEW: { text: "Needs review", className: "badge due" },
  READY: { text: "Ready", className: "badge mastered" },
  FAILED: { text: "Import failed", className: "badge" },
};

function LibraryContent() {
  const [materials, setMaterials] = useState<Material[] | null>(null);

  useEffect(() => {
    api.get("/api/library/materials").then((d) => setMaterials(d.materials));
  }, []);

  if (!materials) return null;

  return (
    <>
      <div className="toolbar">
        <div>
          <h1>IELTS Library</h1>
          <p className="subtitle" style={{ margin: 0 }}>
            Your imported IELTS materials. Private to your account.
          </p>
        </div>
        <div className="spacer" />
        <Link href="/library/import" className="btn">
          + Import material
        </Link>
      </div>

      {materials.length === 0 ? (
        <div className="card empty-state">
          <h2>No materials yet</h2>
          <p>
            Import an IELTS PDF you own and the system will detect its tests, sections and questions,
            then turn them into practice.
          </p>
          <Link href="/library/import" className="btn" style={{ marginTop: 10, display: "inline-flex" }}>
            Import your first material
          </Link>
        </div>
      ) : (
        <div className="grid grid-2">
          {materials.map((m) => {
            const status = STATUS_LABEL[m.status];
            return (
              <Link key={m.id} href={`/library/${m.id}`} className="card material-card">
                <div style={{ display: "flex", alignItems: "baseline", gap: 10 }}>
                  <h2 style={{ margin: 0, flex: 1 }}>{m.title}</h2>
                  <span className={status.className}>{status.text}</span>
                </div>
                {m.source && (
                  <p className="subtitle" style={{ margin: "4px 0 0" }}>
                    {m.source}
                  </p>
                )}
                <div className="material-stats">
                  <span>
                    <strong>{m.tests}</strong> tests
                  </span>
                  <span>
                    <strong>{m.sections}</strong> sections
                  </span>
                  <span>
                    <strong>{m.questions}</strong> questions
                  </span>
                </div>
                {m.needs_review > 0 && (
                  <p className="subtitle" style={{ margin: "10px 0 0", color: "var(--warning)" }}>
                    {m.needs_review} question{m.needs_review === 1 ? "" : "s"} need review
                  </p>
                )}
              </Link>
            );
          })}
        </div>
      )}
    </>
  );
}

export default function LibraryPage() {
  return <Protected>{() => <LibraryContent />}</Protected>;
}

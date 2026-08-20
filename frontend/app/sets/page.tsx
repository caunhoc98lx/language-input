"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import Protected from "@/components/Protected";
import { api } from "@/lib/api";
import type { VocabSet } from "@/lib/types";

function SetsContent() {
  const [sets, setSets] = useState<VocabSet[]>([]);
  const [title, setTitle] = useState("");
  const [description, setDescription] = useState("");
  const [busy, setBusy] = useState(false);
  const router = useRouter();

  useEffect(() => {
    api.get("/api/sets").then((data) => setSets(data.sets));
  }, []);

  async function create(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true);
    const data = await api.post("/api/sets", { title, description });
    router.push(`/sets/${data.set.id}`);
  }

  return (
    <>
      <h1>Vocabulary sets</h1>
      <p className="subtitle">Group words into sets like &quot;IELTS Environment&quot; or &quot;Business English&quot;.</p>

      <div className="card" style={{ marginBottom: 24 }}>
        <form onSubmit={create} style={{ display: "flex", gap: 10, alignItems: "flex-end" }}>
          <div style={{ flex: 1 }}>
            <label style={{ marginTop: 0 }}>New set title</label>
            <input type="text" placeholder="e.g. IELTS Environment" value={title} onChange={(e) => setTitle(e.target.value)} required />
          </div>
          <div style={{ flex: 1 }}>
            <label style={{ marginTop: 0 }}>Description (optional)</label>
            <input type="text" value={description} onChange={(e) => setDescription(e.target.value)} />
          </div>
          <button className="btn" disabled={busy}>Create</button>
        </form>
      </div>

      {sets.length > 0 ? (
        <div className="card" style={{ padding: 0 }}>
          {sets.map((s) => (
            <Link key={s.id} href={`/sets/${s.id}`} className="list-row" style={{ display: "flex" }}>
              <div>
                <div style={{ fontWeight: 600 }}>{s.title}</div>
                <div className="subtitle" style={{ margin: 0 }}>{s.description}</div>
              </div>
              <div className="badge">{s.word_count} words</div>
            </Link>
          ))}
        </div>
      ) : (
        <div className="card empty-state">
          <h2>No sets yet</h2>
          <p>Create your first set above to start organizing your vocabulary.</p>
        </div>
      )}
    </>
  );
}

export default function SetsPage() {
  return <Protected>{() => <SetsContent />}</Protected>;
}

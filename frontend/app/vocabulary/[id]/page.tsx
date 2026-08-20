"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { useParams, useRouter } from "next/navigation";
import Protected from "@/components/Protected";
import { api } from "@/lib/api";
import type { Vocab, Review } from "@/lib/types";

function speak(word: string, lang: string) {
  const u = new SpeechSynthesisUtterance(word);
  u.lang = lang;
  speechSynthesis.cancel();
  speechSynthesis.speak(u);
}

function VocabularyDetailContent() {
  const { id } = useParams<{ id: string }>();
  const router = useRouter();
  const [item, setItem] = useState<Vocab | null>(null);
  const [history, setHistory] = useState<Review[]>([]);
  const [form, setForm] = useState({ translation: "", definition: "", memory_tip: "", notes: "" });
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    api.get(`/api/vocabulary/${id}`).then((data) => {
      setItem(data.item);
      setHistory(data.history);
      setForm({
        translation: data.item.translation,
        definition: data.item.definition,
        memory_tip: data.item.memory_tip,
        notes: data.item.notes,
      });
    });
  }, [id]);

  async function saveEdit(e: React.FormEvent) {
    e.preventDefault();
    setSaving(true);
    const data = await api.patch(`/api/vocabulary/${id}`, form);
    setItem(data.item);
    setSaving(false);
  }

  async function toggleStar() {
    const data = await api.post(`/api/vocabulary/${id}/star`);
    setItem(data.item);
  }

  async function del() {
    if (!confirm("Delete this word?")) return;
    await api.delete(`/api/vocabulary/${id}`);
    router.push("/vocabulary");
  }

  if (!item) return null;

  return (
    <>
      <div className="toolbar">
        <Link href="/vocabulary" className="subtitle">&larr; Back to vocabulary</Link>
      </div>

      <div className="grid grid-2" style={{ alignItems: "start" }}>
        <div className="card">
          <div className="toolbar" style={{ marginBottom: 8 }}>
            <h1 style={{ margin: 0 }}>{item.word}</h1>
            <div className="spacer" />
            <span className={`badge ${item.srs_state.toLowerCase()}`}>{item.srs_state}</span>
          </div>
          {item.pronunciation && (
            <p className="subtitle">{item.pronunciation} {item.part_of_speech && `· ${item.part_of_speech}`}</p>
          )}
          <div style={{ display: "flex", gap: 8, marginBottom: 8 }}>
            <button type="button" className="btn secondary small" onClick={() => speak(item.word, "en-US")}>🔊 US</button>
            <button type="button" className="btn secondary small" onClick={() => speak(item.word, "en-GB")}>🔊 UK</button>
          </div>
          <p style={{ fontSize: "1.2rem", color: "var(--primary)", fontWeight: 600 }}>{item.translation}</p>
          <p>{item.definition}</p>

          {item.examples.length > 0 && (
            <>
              <h2>Examples</h2>
              <ul>{item.examples.map((e, i) => <li key={i}>{e}</li>)}</ul>
            </>
          )}

          {item.synonyms.length > 0 && <p><strong>Synonyms:</strong> {item.synonyms.join(", ")}</p>}
          {item.antonyms.length > 0 && <p><strong>Antonyms:</strong> {item.antonyms.join(", ")}</p>}
          {item.collocations.length > 0 && <p><strong>Collocations:</strong> {item.collocations.join(", ")}</p>}
          {item.ielts_level && (
            <p><span className="badge">IELTS {item.ielts_level}</span> {item.topic && <span className="badge">{item.topic}</span>}</p>
          )}
          {item.memory_tip && <p><strong>Memory tip:</strong> {item.memory_tip}</p>}

          <div style={{ display: "flex", gap: 10, marginTop: 20 }}>
            <button className="btn secondary small" onClick={toggleStar}>{item.starred ? "★ Starred" : "☆ Star"}</button>
            <button className="btn danger small" onClick={del}>Delete</button>
          </div>
        </div>

        <div className="card">
          <h2>Notes</h2>
          <form onSubmit={saveEdit}>
            <label>Translation</label>
            <input type="text" value={form.translation} onChange={(e) => setForm({ ...form, translation: e.target.value })} />
            <label>Definition</label>
            <textarea rows={2} value={form.definition} onChange={(e) => setForm({ ...form, definition: e.target.value })} />
            <label>Memory tip</label>
            <textarea rows={2} value={form.memory_tip} onChange={(e) => setForm({ ...form, memory_tip: e.target.value })} />
            <label>Personal notes</label>
            <textarea rows={3} value={form.notes} onChange={(e) => setForm({ ...form, notes: e.target.value })} />
            <button className="btn" style={{ marginTop: 12 }} disabled={saving}>{saving ? "Saving..." : "Save"}</button>
          </form>

          <h2 style={{ marginTop: 24 }}>Review history</h2>
          {history.length > 0 ? (
            history.map((h) => (
              <div className="list-row" key={h.id}>
                <span>{h.rating}</span>
                <span className="subtitle" style={{ margin: 0 }}>{h.reviewed_at}</span>
              </div>
            ))
          ) : (
            <p className="subtitle">No reviews yet.</p>
          )}
        </div>
      </div>
    </>
  );
}

export default function VocabularyDetailPage() {
  return <Protected>{() => <VocabularyDetailContent />}</Protected>;
}

"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { useParams, useRouter } from "next/navigation";
import Protected from "@/components/Protected";
import { api } from "@/lib/api";
import type { Vocab, VocabSet } from "@/lib/types";

function SetDetailContent() {
  const { id } = useParams<{ id: string }>();
  const router = useRouter();
  const [set, setSet] = useState<VocabSet | null>(null);
  const [words, setWords] = useState<Vocab[]>([]);
  const [otherWords, setOtherWords] = useState<{ id: number; word: string }[]>([]);
  const [checked, setChecked] = useState<Set<number>>(new Set());

  function load() {
    api.get(`/api/sets/${id}`).then((data) => {
      setSet(data.set);
      setWords(data.words);
      setOtherWords(data.other_words);
    });
  }

  useEffect(load, [id]);

  async function addSelected() {
    if (checked.size === 0) return;
    await api.post(`/api/sets/${id}/words`, { word_ids: Array.from(checked) });
    setChecked(new Set());
    load();
  }

  async function removeWord(vocabId: number) {
    await api.delete(`/api/sets/${id}/words/${vocabId}`);
    load();
  }

  async function deleteSet() {
    if (!confirm("Delete this set? Words stay in your vocabulary.")) return;
    await api.delete(`/api/sets/${id}`);
    router.push("/sets");
  }

  if (!set) return null;

  return (
    <>
      <div className="toolbar">
        <div>
          <h1 style={{ margin: 0 }}>{set.title}</h1>
          <p className="subtitle">{set.description}</p>
        </div>
        <div className="spacer" />
        {words.length > 0 && <Link href={`/study/flashcards?set_id=${set.id}`} className="btn">Study this set</Link>}
        <button className="btn secondary" onClick={deleteSet}>Delete set</button>
      </div>

      <div className="card" style={{ padding: 0, marginBottom: 24 }}>
        {words.length > 0 ? (
          words.map((v) => (
            <div className="list-row" key={v.id}>
              <Link href={`/vocabulary/${v.id}`} style={{ fontWeight: 600 }}>
                {v.word} <span className="subtitle" style={{ margin: 0, fontWeight: 400 }}>— {v.translation}</span>
              </Link>
              <div style={{ display: "flex", gap: 10, alignItems: "center" }}>
                <span className={`badge ${v.srs_state.toLowerCase()}`}>{v.srs_state}</span>
                <button className="btn secondary small" onClick={() => removeWord(v.id)}>Remove</button>
              </div>
            </div>
          ))
        ) : (
          <div className="empty-state">
            <p>No words in this set yet. Add some below, or <Link href="/vocabulary/new" style={{ color: "var(--primary)" }}>create new vocabulary</Link>.</p>
          </div>
        )}
      </div>

      {otherWords.length > 0 && (
        <>
          <h2>Add existing words to this set</h2>
          <div className="card" style={{ maxHeight: 300, overflowY: "auto", padding: "4px 20px" }}>
            {otherWords.map((w) => (
              <label key={w.id} style={{ display: "flex", alignItems: "center", gap: 10, fontWeight: 400, margin: "10px 0" }}>
                <input
                  type="checkbox"
                  checked={checked.has(w.id)}
                  onChange={() => {
                    setChecked((prev) => {
                      const next = new Set(prev);
                      if (next.has(w.id)) next.delete(w.id);
                      else next.add(w.id);
                      return next;
                    });
                  }}
                />
                {w.word}
              </label>
            ))}
          </div>
          <button className="btn" style={{ marginTop: 12 }} onClick={addSelected}>Add selected</button>
        </>
      )}
    </>
  );
}

export default function SetDetailPage() {
  return <Protected>{() => <SetDetailContent />}</Protected>;
}

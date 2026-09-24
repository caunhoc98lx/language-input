"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import Protected from "@/components/Protected";
import { api, ApiError } from "@/lib/api";
import type { VocabSet } from "@/lib/types";

interface ExtractedItem {
  word: string;
  translation: string;
  part_of_speech: string;
  pronunciation: string;
  phonetic: string;
  definition: string;
  examples: string[];
  synonyms: string[];
  antonyms: string[];
  collocations: string[];
  ielts_level: string;
  topic: string;
  memory_tip: string;
}

function VocabularyNewContent() {
  const [text, setText] = useState("");
  const [items, setItems] = useState<ExtractedItem[] | null>(null);
  const [selected, setSelected] = useState<Set<number>>(new Set());
  const [sets, setSets] = useState<VocabSet[]>([]);
  const [setId, setSetId] = useState("auto");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const router = useRouter();

  useEffect(() => {
    api.get("/api/sets").then((data) => setSets(data.sets));
  }, []);

  async function analyze(e: React.FormEvent) {
    e.preventDefault();
    setError(null);
    setBusy(true);
    try {
      const data = await api.post("/api/vocabulary/extract", { text });
      if (data.items.length === 0) {
        setError("No vocabulary detected in that input. Try a word, list, or sentence.");
      } else {
        setItems(data.items);
        setSelected(new Set(data.items.map((_: unknown, i: number) => i)));
      }
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Something went wrong.");
    } finally {
      setBusy(false);
    }
  }

  function toggle(i: number) {
    setSelected((prev) => {
      const next = new Set(prev);
      if (next.has(i)) next.delete(i);
      else next.add(i);
      return next;
    });
  }

  async function save() {
    if (!items) return;
    setBusy(true);
    try {
      const toSave = items.filter((_, i) => selected.has(i));
      await api.post("/api/vocabulary/save", {
        items: toSave,
        set_id: setId !== "auto" && setId ? Number(setId) : null,
        group_by_topic: setId === "auto",
      });
      router.push("/vocabulary");
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Something went wrong.");
      setBusy(false);
    }
  }

  if (items) {
    return (
      <>
        <h1>Detected vocabulary</h1>
        <p className="subtitle">Uncheck anything you don&apos;t want to save.</p>

        <div className="card" style={{ padding: "4px 20px" }}>
          {items.map((item, i) => (
            <div className="preview-item" key={i}>
              <input
                type="checkbox"
                checked={selected.has(i)}
                onChange={() => toggle(i)}
                style={{ marginTop: 6 }}
              />
              <div className="fields">
                <div className="top">
                  <span className="word">{item.word}</span>
                  <span className="translation">{item.translation}</span>
                  {item.part_of_speech && <span className="subtitle" style={{ margin: 0 }}>({item.part_of_speech})</span>}
                </div>
                <div className="meta">{item.definition}</div>
                {item.examples[0] && <div className="meta">&quot;{item.examples[0]}&quot;</div>}
                {item.synonyms.length > 0 && (
                  <div className="meta"><strong>Synonyms:</strong> {item.synonyms.join(", ")}</div>
                )}
                {item.ielts_level && <span className="badge">{item.ielts_level}</span>}
                {setId === "auto" && item.topic && (
                  <span className="badge" style={{ marginLeft: 6 }}>→ {item.topic}</span>
                )}
              </div>
            </div>
          ))}
        </div>

        <label>Add to set</label>
        <select value={setId} onChange={(e) => setSetId(e.target.value)}>
          <option value="auto">Auto-group by topic (creates/reuses sets like &quot;Travel&quot;, &quot;Education&quot;)</option>
          <option value="">No set</option>
          {sets.map((s) => <option key={s.id} value={s.id}>{s.title}</option>)}
        </select>
        {setId === "auto" && (
          <p className="subtitle" style={{ margin: "6px 0 0" }}>
            Each word&apos;s topic (shown above) decides its set — a matching set is reused if you already have one.
          </p>
        )}

        {error && <div className="error">{error}</div>}

        <div style={{ marginTop: 20, display: "flex", gap: 10 }}>
          <button className="btn" onClick={save} disabled={busy || selected.size === 0}>
            {busy ? "Saving..." : "Save selected"}
          </button>
          <button className="btn secondary" onClick={() => setItems(null)}>Cancel</button>
        </div>
      </>
    );
  }

  return (
    <>
      <h1>Add vocabulary</h1>
      <p className="subtitle">Enter a word, a list of words, or a whole sentence/paragraph. AI will detect and translate the useful vocabulary.</p>
      <div className="card">
        <form onSubmit={analyze}>
          <textarea
            rows={8}
            placeholder={"e.g. abundant\nor: The government should implement measures to mitigate climate change."}
            value={text}
            onChange={(e) => setText(e.target.value)}
            required
            autoFocus
          />
          {error && <div className="error">{error}</div>}
          <button className="btn" style={{ marginTop: 16 }} disabled={busy}>
            {busy ? "Analyzing..." : "Analyze with AI"}
          </button>
        </form>
      </div>
    </>
  );
}

export default function VocabularyNewPage() {
  return <Protected>{() => <VocabularyNewContent />}</Protected>;
}

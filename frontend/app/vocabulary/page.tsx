"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import Protected from "@/components/Protected";
import { api } from "@/lib/api";
import type { Vocab, VocabSet } from "@/lib/types";

const FILTERS: [string, string][] = [
  ["", "All"],
  ["due", "Due"],
  ["NEW", "New"],
  ["LEARNING", "Learning"],
  ["REVIEW", "Review"],
  ["MASTERED", "Mastered"],
];

// Decorative only - identity is already carried by the title, so a fixed
// cycling order (not a validated categorical palette) is enough here.
const COVERS = [
  { bg: "#eef2ff", fg: "#4f46e5" },
  { bg: "#ecfdf5", fg: "#16a34a" },
  { bg: "#fff7ed", fg: "#d97706" },
  { bg: "#eff6ff", fg: "#2563eb" },
  { bg: "#f5f3ff", fg: "#7c3aed" },
  { bg: "#fdf2f8", fg: "#db2777" },
  { bg: "#ecfeff", fg: "#0891b2" },
];

const TOPIC_EMOJI: [RegExp, string][] = [
  [/travel|tourism|holiday|vacation/i, "✈️"],
  [/work|business|career|job/i, "💼"],
  [/tech/i, "💻"],
  [/health|fitness|medic/i, "🏋️"],
  [/environment|nature|climate/i, "🌱"],
  [/education|school|study|academ/i, "🎓"],
  [/food|cook|cuisine/i, "🍽️"],
  [/daily|routine/i, "⏰"],
  [/social|society|community/i, "🏛️"],
  [/famil/i, "👪"],
  [/financ|money|econom/i, "💰"],
  [/crime|law|legal/i, "⚖️"],
  [/media|news|journal/i, "📰"],
  [/sport/i, "⚽"],
  [/art|culture|music/i, "🎨"],
  [/science/i, "🔬"],
];

function topicEmoji(title: string): string {
  const match = TOPIC_EMOJI.find(([re]) => re.test(title));
  return match ? match[1] : "📚";
}

function SetCard({
  href, cover, emoji, title, description, wordCount, mastered,
}: {
  href: string; cover: { bg: string; fg: string }; emoji: string; title: string;
  description: string; wordCount: number; mastered: number;
}) {
  const pct = wordCount > 0 ? Math.round((100 * mastered) / wordCount) : 0;
  return (
    <Link href={href} className="set-card">
      <div className="set-cover" style={{ background: cover.bg }}>
        <span className="set-emoji">{emoji}</span>
        <span className="set-count-badge" style={{ color: cover.fg }}>{wordCount} words</span>
      </div>
      <div className="set-body">
        <div className="set-title">{title}</div>
        <div className="set-desc">{description}</div>
        <div className="set-progress-row">
          <span className="set-progress-label">Mastered</span>
          <span className="meter"><span style={{ width: `${pct}%` }} /></span>
          <span className="set-progress-frac">{mastered}/{wordCount}</span>
        </div>
      </div>
    </Link>
  );
}

function SetsOverview() {
  const [sets, setSets] = useState<VocabSet[]>([]);
  const [unsortedCount, setUnsortedCount] = useState(0);
  const [unsortedMastered, setUnsortedMastered] = useState(0);
  const [loaded, setLoaded] = useState(false);

  useEffect(() => {
    api.get("/api/sets").then((data) => {
      setSets(data.sets);
      setUnsortedCount(data.unsorted_count);
      setUnsortedMastered(data.unsorted_mastered);
      setLoaded(true);
    });
  }, []);

  if (!loaded) return null;

  if (sets.length === 0 && unsortedCount === 0) {
    return (
      <div className="card empty-state">
        <h2>No vocabulary yet</h2>
        <p>Add your first English word and we&apos;ll automatically translate it, explain it, and schedule it for review.</p>
        <Link href="/vocabulary/new" className="btn" style={{ marginTop: 10, display: "inline-flex" }}>Add vocabulary</Link>
      </div>
    );
  }

  return (
    <div className="set-grid">
      {sets.map((s, i) => (
        <SetCard
          key={s.id}
          href={`/study/anki?set_id=${s.id}`}
          cover={COVERS[i % COVERS.length]}
          emoji={topicEmoji(s.title)}
          title={s.title}
          description={s.description || `Words you've saved under "${s.title}."`}
          wordCount={s.word_count ?? 0}
          mastered={s.mastered_count ?? 0}
        />
      ))}
      {unsortedCount > 0 && (
        <SetCard
          href="/study/anki?set_id=none"
          cover={{ bg: "#f4f4f5", fg: "#52525b" }}
          emoji="📦"
          title="Unsorted"
          description="Words not in any set yet."
          wordCount={unsortedCount}
          mastered={unsortedMastered}
        />
      )}
    </div>
  );
}

function WordList({ state, q }: { state: string; q: string }) {
  const [items, setItems] = useState<Vocab[]>([]);

  useEffect(() => {
    const params = new URLSearchParams();
    if (state) params.set("state", state);
    if (q) params.set("q", q);
    api.get(`/api/vocabulary?${params}`).then((data) => setItems(data.items));
  }, [state, q]);

  if (items.length === 0) {
    return (
      <div className="card empty-state">
        <h2>No matching words</h2>
        <p>Try a different search or filter.</p>
      </div>
    );
  }

  return (
    <div className="card" style={{ padding: 0 }}>
      {items.map((v) => (
        <Link key={v.id} href={`/vocabulary/${v.id}`} className="list-row" style={{ display: "flex" }}>
          <div>
            <div style={{ fontWeight: 600 }}>
              {v.word} {v.part_of_speech && <span className="subtitle" style={{ margin: 0 }}>({v.part_of_speech})</span>} {v.starred ? "★" : ""}
            </div>
            <div className="subtitle" style={{ margin: 0 }}>{v.translation}</div>
          </div>
          <div className={`badge ${v.srs_state.toLowerCase()}`}>{v.srs_state}</div>
        </Link>
      ))}
    </div>
  );
}

function VocabularyContent() {
  const [state, setState] = useState("");
  const [q, setQ] = useState("");
  const browsing = state !== "" || q !== "";

  return (
    <>
      <div className="toolbar">
        <h1 style={{ margin: 0 }}>Vocabulary</h1>
        <div className="spacer" />
        <Link href="/vocabulary/new" className="btn">+ Add vocabulary</Link>
      </div>

      <input
        type="text"
        placeholder="Search word or translation..."
        defaultValue={q}
        onChange={(e) => setQ(e.target.value)}
        style={{ marginBottom: 16 }}
      />

      <div className="toolbar">
        {FILTERS.map(([key, label]) => (
          <button
            key={key}
            className={`chip-select ${state === key ? "active" : ""}`}
            onClick={() => setState(key)}
          >
            {label}
          </button>
        ))}
      </div>

      {browsing ? <WordList state={state} q={q} /> : <SetsOverview />}
    </>
  );
}

export default function VocabularyPage() {
  return <Protected>{() => <VocabularyContent />}</Protected>;
}

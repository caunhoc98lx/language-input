"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import Protected from "@/components/Protected";
import { api } from "@/lib/api";
import { typeLabel } from "@/lib/practice";
import type { QuestionTypeAccuracy, Skill } from "@/lib/types";

interface ProgressData {
  bands: {
    skills: Partial<Record<Skill, number>>;
    overall: number | null;
    estimated_from: string;
    target: number | null;
    target_date: string | null;
  };
  question_type_accuracy: QuestionTypeAccuracy[];
  weak_areas: QuestionTypeAccuracy[];
  history: { skill: string; band: number; at: string }[];
  vocabulary: {
    total: number;
    mastered: number;
    learning: number;
    new_words: number;
    lapsed: number;
    avg_interval: number;
    retention: number | null;
    reviews_in_window: number;
  };
  activity: { day: string; items: number }[];
  daily_tasks_completed: number;
  streak: number;
  days: number;
}

const SKILLS: Skill[] = ["listening", "reading", "writing", "speaking"];

/** Band history as a small inline SVG. ponytail: ~20 lines of SVG instead of a
 *  charting library — one line per skill is all this page needs. */
function BandChart({ history }: { history: ProgressData["history"] }) {
  if (history.length < 2) return null;
  const width = 640;
  const height = 180;
  const pad = 28;
  const times = history.map((h) => new Date(h.at).getTime());
  const minT = Math.min(...times);
  const maxT = Math.max(...times);
  const span = maxT - minT || 1;
  const x = (t: number) => pad + ((t - minT) / span) * (width - pad * 2);
  const y = (band: number) => height - pad - ((band - 3) / 6) * (height - pad * 2);
  const colors: Record<string, string> = {
    listening: "#4f46e5",
    reading: "#16a34a",
    writing: "#d97706",
    speaking: "#dc2626",
  };

  return (
    <div style={{ overflowX: "auto" }}>
      <svg viewBox={`0 0 ${width} ${height}`} className="band-chart" role="img" aria-label="Band history">
        {[4, 5, 6, 7, 8, 9].map((band) => (
          <g key={band}>
            <line x1={pad} x2={width - pad} y1={y(band)} y2={y(band)} stroke="var(--border)" />
            <text x={4} y={y(band) + 4} fontSize="10" fill="var(--muted)">
              {band}
            </text>
          </g>
        ))}
        {SKILLS.map((skill) => {
          const points = history.filter((h) => h.skill === skill);
          if (points.length < 2) return null;
          const d = points
            .map((p, i) => `${i === 0 ? "M" : "L"}${x(new Date(p.at).getTime())},${y(p.band)}`)
            .join(" ");
          return (
            <g key={skill}>
              <path d={d} fill="none" stroke={colors[skill]} strokeWidth="2" />
              {points.map((p, i) => (
                <circle key={i} cx={x(new Date(p.at).getTime())} cy={y(p.band)} r="3" fill={colors[skill]} />
              ))}
            </g>
          );
        })}
      </svg>
      <div className="chart-legend">
        {SKILLS.filter((s) => history.some((h) => h.skill === s)).map((s) => (
          <span key={s}>
            <i style={{ background: colors[s] }} /> {s}
          </span>
        ))}
      </div>
    </div>
  );
}

function ProgressContent() {
  const [data, setData] = useState<ProgressData | null>(null);

  useEffect(() => {
    api.get("/api/progress").then(setData);
  }, []);

  if (!data) return null;
  const { bands, vocabulary, activity } = data;
  const activeDays = activity.length;
  const totalItems = activity.reduce((n, a) => n + Number(a.items), 0);

  return (
    <>
      <h1>Progress</h1>
      <p className="subtitle">Last {data.days} days of practice, from every source.</p>

      <div className="card skill-bands" style={{ marginBottom: 20 }}>
        {SKILLS.map((skill) => (
          <div key={skill} className="skill-band">
            <div className={bands.skills[skill] === undefined ? "num unknown" : "num"}>
              {bands.skills[skill]?.toFixed(1) ?? "—"}
            </div>
            <div className="label">{skill}</div>
          </div>
        ))}
      </div>

      <div className="grid grid-4" style={{ marginBottom: 20 }}>
        <div className="card stat">
          <div className="num">{bands.overall?.toFixed(1) ?? "—"}</div>
          <div className="label">Estimated overall{bands.target ? ` · target ${bands.target}` : ""}</div>
        </div>
        <div className="card stat">
          <div className="num">{data.daily_tasks_completed}</div>
          <div className="label">Daily tasks completed</div>
        </div>
        <div className="card stat">
          <div className="num">{activeDays}</div>
          <div className="label">Days studied · {totalItems} items</div>
        </div>
        <div className="card stat">
          <div className="num">{data.streak}</div>
          <div className="label">Day streak</div>
        </div>
      </div>

      {data.history.length >= 2 ? (
        <div className="card" style={{ marginBottom: 20 }}>
          <h2>Band over time</h2>
          <BandChart history={data.history} />
        </div>
      ) : (
        <div className="card empty-state" style={{ marginBottom: 20 }}>
          <p>Complete a few more practice sessions and your band history is charted here.</p>
        </div>
      )}

      <div className="grid grid-2" style={{ marginBottom: 20 }}>
        <div className="card">
          <h2>Question type accuracy</h2>
          {data.question_type_accuracy.length === 0 ? (
            <p className="subtitle" style={{ margin: 0 }}>No answered questions yet.</p>
          ) : (
            data.question_type_accuracy.map((row) => (
              <div key={row.type} className="weak-row">
                <span className="label">{typeLabel(row.type)}</span>
                <span className={`meter ${row.accuracy < 0.6 ? "weak" : row.accuracy < 0.75 ? "ok" : "good"}`}>
                  <span style={{ width: `${Math.round(row.accuracy * 100)}%` }} />
                </span>
                <span className="pct">
                  {Math.round(row.accuracy * 100)}% · {row.attempts}q
                </span>
              </div>
            ))
          )}
          {data.weak_areas.length > 0 && (
            <Link href="/daily" className="btn small" style={{ marginTop: 12, display: "inline-flex" }}>
              Practise the weakest
            </Link>
          )}
        </div>

        <div className="card">
          <h2>Vocabulary retention</h2>
          <div className="result-stats">
            <div>
              <div className="num">{vocabulary.total}</div>
              <div className="label">Words</div>
            </div>
            <div>
              <div className="num">{vocabulary.mastered}</div>
              <div className="label">Mastered</div>
            </div>
            <div>
              <div className="num">
                {vocabulary.retention !== null ? `${Math.round(vocabulary.retention * 100)}%` : "—"}
              </div>
              <div className="label">Retention</div>
            </div>
            <div>
              <div className="num">{vocabulary.avg_interval}</div>
              <div className="label">Avg interval (days)</div>
            </div>
          </div>
          <p className="subtitle" style={{ margin: "14px 0 0" }}>
            {vocabulary.learning} learning · {vocabulary.new_words} new · {vocabulary.lapsed} forgotten at
            least once · {vocabulary.reviews_in_window} reviews in this window
          </p>
        </div>
      </div>
    </>
  );
}

export default function ProgressPage() {
  return <Protected>{() => <ProgressContent />}</Protected>;
}

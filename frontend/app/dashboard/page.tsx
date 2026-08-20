"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import Protected from "@/components/Protected";
import { api } from "@/lib/api";
import type { Coaching, QuestionTypeAccuracy, Skill, User } from "@/lib/types";

interface DashboardData extends Coaching {
  user: User;
  due: number;
  new_count: number;
  mastered: number;
  learning: number;
  total: number;
  sets_progress: { id: number; title: string; total_words: number; pct: number }[];
}

const SKILLS: Skill[] = ["listening", "reading", "writing", "speaking"];

function greeting(): string {
  const h = new Date().getHours();
  if (h < 12) return "Good morning";
  if (h < 18) return "Good afternoon";
  return "Good evening";
}

function meterClass(accuracy: number): string {
  if (accuracy < 0.6) return "meter weak";
  if (accuracy < 0.75) return "meter ok";
  return "meter good";
}

function daysUntil(iso: string): number {
  return Math.ceil((new Date(iso + "T00:00:00").getTime() - Date.now()) / 86_400_000);
}

function AccuracyRow({ row }: { row: QuestionTypeAccuracy }) {
  return (
    <div className="weak-row">
      <span className="label">{row.label}</span>
      <span className={meterClass(row.accuracy)}>
        <span style={{ width: `${Math.round(row.accuracy * 100)}%` }} />
      </span>
      <span className="pct">
        {Math.round(row.accuracy * 100)}% · {row.attempts}q
      </span>
    </div>
  );
}

function DashboardContent({ user }: { user: User }) {
  const [data, setData] = useState<DashboardData | null>(null);

  useEffect(() => {
    api.get("/api/dashboard").then(setData);
  }, []);

  if (!data) return null;

  const { bands, plan, weak_areas, question_type_accuracy, activity } = data;
  const planMinutes = plan.reduce((sum, t) => sum + t.minutes, 0);
  const firstUndone = plan.find((t) => !t.done) ?? plan[0];
  const daysLeft = bands.target_date ? daysUntil(bands.target_date) : null;

  return (
    <>
      <div className="hero">
        <div>
          <h1>
            {greeting()}, {user.name || user.email.split("@")[0]}
          </h1>
          <p className="subtitle" style={{ margin: 0 }}>
            {daysLeft !== null && daysLeft >= 0
              ? `${daysLeft} days until your test on ${bands.target_date}.`
              : "What should you study right now? Start at the top."}
          </p>
        </div>
        <div>
          <div className="band-track">
            <div>
              <div className="band-value">{bands.overall !== null ? bands.overall.toFixed(1) : "—"}</div>
              <div className="band-caption">
                {bands.estimated_from === "practice" ? "estimated" : "self-reported"}
              </div>
            </div>
            <span className="band-arrow">→</span>
            <div>
              <div className="band-value target">{bands.target ? bands.target.toFixed(1) : "—"}</div>
              <div className="band-caption">target</div>
            </div>
          </div>
        </div>
      </div>

      <div className="card skill-bands" style={{ marginBottom: 24 }}>
        {SKILLS.map((skill) => {
          const band = bands.skills[skill];
          return (
            <div key={skill} className="skill-band">
              <div className={band === undefined ? "num unknown" : "num"}>
                {band === undefined ? "—" : band.toFixed(1)}
              </div>
              <div className="label">{skill}</div>
            </div>
          );
        })}
      </div>

      <div style={{ display: "flex", alignItems: "baseline", gap: 12, marginBottom: 12 }}>
        <h2 style={{ margin: 0 }}>Today&apos;s plan</h2>
        <span className="subtitle" style={{ margin: 0 }}>
          about {planMinutes} min
        </span>
        {firstUndone && (
          <Link href={firstUndone.href} className="btn small" style={{ marginLeft: "auto" }}>
            Start today&apos;s plan
          </Link>
        )}
      </div>
      <div className="card plan-list" style={{ marginBottom: 24 }}>
        {plan.map((task, i) => (
          <Link key={task.kind} href={task.href} className={`plan-item ${task.done ? "done" : ""}`}>
            <span className="step">{task.done ? "✓" : i + 1}</span>
            <span>
              <span className="plan-title">{task.title}</span>
              <span className="plan-detail" style={{ display: "block" }}>
                {task.detail}
              </span>
            </span>
            <span className="plan-mins">{task.minutes} min</span>
          </Link>
        ))}
      </div>

      <div className="grid grid-4" style={{ marginBottom: 24 }}>
        <div className="card stat">
          <div className="num">{data.due}</div>
          <div className="label">Cards due</div>
        </div>
        <div className="card stat">
          <div className="num">{data.mastered}</div>
          <div className="label">Words mastered</div>
        </div>
        <div className="card stat">
          <div className="num">{activity.questions_answered}</div>
          <div className="label">
            Questions answered{activity.accuracy !== null && ` · ${Math.round(activity.accuracy * 100)}%`}
          </div>
        </div>
        <div className="card stat">
          <div className="num">{user.streak}</div>
          <div className="label">Day streak · {activity.reviews_this_week} reviews this week</div>
        </div>
      </div>

      <div className="grid grid-2">
        <div className="card">
          <h2>Your weak areas</h2>
          {weak_areas.length > 0 ? (
            <>
              {weak_areas.map((row) => (
                <AccuracyRow key={row.type} row={row} />
              ))}
              <Link href="/daily/reading" className="btn small" style={{ marginTop: 14, display: "inline-flex" }}>
                Practice weak areas
              </Link>
            </>
          ) : (
            <p className="subtitle" style={{ margin: 0 }}>
              Not enough data yet. Finish a few practice tasks and the weakest question types show up here.
            </p>
          )}
        </div>

        <div className="card">
          <h2>Accuracy by question type</h2>
          {question_type_accuracy.length > 0 ? (
            question_type_accuracy.slice(0, 6).map((row) => <AccuracyRow key={row.type} row={row} />)
          ) : (
            <p className="subtitle" style={{ margin: 0 }}>
              No answered questions yet.
            </p>
          )}
        </div>
      </div>
    </>
  );
}

export default function DashboardPage() {
  return <Protected>{(user) => <DashboardContent user={user} />}</Protected>;
}

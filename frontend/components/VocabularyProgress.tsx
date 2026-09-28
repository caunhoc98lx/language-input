"use client";

import { useState } from "react";
import Link from "next/link";
import styles from "./VocabularyProgress.module.css";

export interface WordActivity {
  timezone: string;
  days: { date: string; words: number; reviews: number }[];
}

function dateLabel(date: string, full = false) {
  return new Date(`${date}T12:00:00`).toLocaleDateString("en-US", full
    ? { weekday: "long", month: "short", day: "numeric" }
    : { month: "short", day: "numeric" });
}

export default function VocabularyProgress({ activity, mastered, total, learning, due }: {
  activity: WordActivity; mastered: number; total: number; learning: number; due: number;
}) {
  const [range, setRange] = useState<7 | 30>(7);
  const [selected, setSelected] = useState<string | null>(null);
  const days = activity.days.slice(-range);
  const today = activity.days.at(-1);
  const current = days.find(day => day.date === selected) ?? today;
  const activeDays = days.filter(day => day.words > 0).length;
  const wordTotal = days.reduce((sum, day) => sum + day.words, 0);
  const maximum = Math.max(5, ...days.map(day => day.words));
  const yesterday = activity.days.at(-2)?.words ?? 0;
  const delta = (today?.words ?? 0) - yesterday;
  const pct = total ? Math.round(mastered / total * 100) : 0;

  return <section className={styles.section} aria-label="Vocabulary progress">
    <div className={styles.overview}>
      <div className={styles.today}>
        <span className={styles.eyebrow}>YOUR DAILY PRACTICE</span>
        <div className={styles.bigNumber}>{today?.words ?? 0}<span>words today</span></div>
        <p>{delta > 0 ? `${delta} more than yesterday. Keep it going.` : delta < 0 ? `${Math.abs(delta)} fewer than yesterday. There’s still time.` : today?.words ? "Matching yesterday’s pace. Keep it going." : "A few words today. A stronger vocabulary tomorrow."}</p>
        <Link href="/study/anki" className={styles.cta}>{today?.words ? "Continue practicing" : "Start practicing"}<span aria-hidden="true">→</span></Link>
        <span className={styles.due}>{due} words due for review</span>
      </div>
      <div className={styles.collection}>
        <div className={styles.sectionHeading}><h2>Your vocabulary</h2><Link href="/vocabulary">View all →</Link></div>
        <div className={styles.mastered}><strong>{mastered}</strong><span>words mastered<br /><small>of {total} in your collection</small></span></div>
        <div className={styles.track} role="progressbar" aria-label="Vocabulary mastered" aria-valuenow={pct} aria-valuemin={0} aria-valuemax={100}><span style={{ width: `${pct}%` }} /></div>
        <div className={styles.collectionFoot}><span>{learning} learning</span><strong>{pct}% mastered</strong></div>
        <p>{total ? "Build lasting recall, one practice session at a time." : "Add your first words to start building your collection."}</p>
      </div>
    </div>
    <div className={styles.history}>
      <div className={styles.sectionHeading}>
        <div><h2>A little practice, every day</h2><p>See how your vocabulary practice adds up.</p></div>
        <div className={styles.toggle} aria-label="Chart period">{([7, 30] as const).map(value => <button key={value} aria-pressed={range === value} onClick={() => { setRange(value); setSelected(null); }}>{value} days</button>)}</div>
      </div>
      <div className={styles.summary}>
        <div><strong>{wordTotal}</strong><span>daily words combined</span></div>
        <div><strong>{activeDays}<small> / {range}</small></strong><span>days practiced</span></div>
        <div><strong>{(wordTotal / range).toFixed(1)}</strong><span>words per day</span></div>
      </div>
      <div className={styles.chartScroll}>
        <div className={`${styles.chart} ${range === 30 ? styles.month : ""}`}>
          <div className={styles.axis} aria-hidden="true"><span>{maximum}</span><span>{Math.round(maximum / 2)}</span><span>0</span></div>
          <div className={styles.bars} style={{ gridTemplateColumns: `repeat(${days.length}, minmax(0, 1fr))` }}>
            {days.map((day, index) => <button key={day.date} className={`${styles.day} ${current?.date === day.date ? styles.selected : ""}`} onClick={() => setSelected(day.date)} aria-pressed={current?.date === day.date} aria-label={`${dateLabel(day.date, true)}: ${day.words} words, ${day.reviews} reviews`}>
              <span className={styles.barArea}><span className={styles.bar} style={{ height: day.words ? `${day.words / maximum * 100}%` : "3px" }}><span className={styles.barValue}>{day.words}</span></span></span>
              <span className={styles.dayLabel}>{day.date === today?.date ? "Today" : range === 7 ? new Date(`${day.date}T12:00:00`).toLocaleDateString("en-US", { weekday: "short" }) : index % 5 === 0 ? dateLabel(day.date) : ""}</span>
            </button>)}
          </div>
        </div>
      </div>
      <div className={styles.chartDetail} aria-live="polite"><span>{current ? dateLabel(current.date, true) : "No practice yet"}</span><strong>{current?.words ?? 0} words <span>·</span> {current?.reviews ?? 0} reviews</strong></div>
      {wordTotal === 0 && <p className={styles.empty}>Your first practice will appear here. Select “Start practicing” to begin.</p>}
      <p className={styles.note}>Each word counts once per day, even when reviewed again. Dates use {activity.timezone}.</p>
    </div>
  </section>;
}

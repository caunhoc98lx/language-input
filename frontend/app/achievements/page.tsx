"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import Protected from "@/components/Protected";
import { api } from "@/lib/api";
import type { Achievement, GameStats } from "@/lib/types";

function AchievementsContent() {
  const [data, setData] = useState<{ stats: GameStats; achievements: Achievement[] } | null>(null);

  useEffect(() => {
    api.get("/api/game/achievements").then(setData);
  }, []);

  if (!data) return null;
  const { stats, achievements } = data;
  const unlocked = achievements.filter((a) => a.unlocked).length;

  return (
    <>
      <div className="toolbar">
        <h1 style={{ margin: 0 }}>Achievements</h1>
        <div className="spacer" />
        <Link href="/study/anki" className="btn">Start a session</Link>
      </div>
      <p className="subtitle">{unlocked} of {achievements.length} badges unlocked</p>

      <div className="reward-grid wide">
        <div><b>Level {stats.level}</b><span>{stats.xp.toLocaleString()} XP total</span></div>
        <div><b>🪙 {stats.coins.toLocaleString()}</b><span>Coins</span></div>
        <div><b>🔥 {stats.streak}</b><span>Day streak</span></div>
        <div><b>x{stats.best_combo}</b><span>Best combo</span></div>
        <div><b>{stats.boss_wins}</b><span>Bosses defeated</span></div>
        <div><b>{stats.words_mastered}</b><span>Words mastered</span></div>
      </div>

      <div className="badge-grid">
        {achievements.map((a) => (
          <div key={a.key} className={`badge-card${a.unlocked ? " unlocked" : ""}`}>
            <span aria-hidden="true">{a.icon}</span>
            <div>
              <b>{a.title}</b>
              <small>{a.unlocked ? a.description : `Locked · ${a.description}`}</small>
            </div>
          </div>
        ))}
      </div>
    </>
  );
}

export default function AchievementsPage() {
  return <Protected>{() => <AchievementsContent />}</Protected>;
}

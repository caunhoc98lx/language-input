"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { api } from "@/lib/api";
import type { GameStats, User } from "@/lib/types";
import DueBanner from "./DueBanner";

/**
 * Desktop: sidebar + a slim top bar with level/XP/streak/coins.
 * Mobile: bottom navigation (5 destinations).
 *
 * ponytail: only routes that exist are listed - a nav item that leads to an
 * empty page is worse than no nav item.
 */
const NAV: { href: string; label: string; icon: string }[] = [
  { href: "/dashboard", label: "Dashboard", icon: "◈" },
  { href: "/daily", label: "Daily Quest", icon: "◎" },
  { href: "/study/anki", label: "Review", icon: "↻" },
  { href: "/vocabulary", label: "Vocabulary", icon: "☰" },
  { href: "/writing", label: "Writing", icon: "✎" },
  { href: "/daily/listening", label: "Listening", icon: "♪" },
  { href: "/progress", label: "Progress", icon: "▲" },
  { href: "/achievements", label: "Achievements", icon: "★" },
  { href: "/tutor", label: "AI Coach", icon: "✦" },
  { href: "/settings", label: "Settings", icon: "⚙" },
];

const MOBILE_NAV = [
  { href: "/dashboard", label: "Home", icon: "◈" },
  { href: "/daily", label: "Quest", icon: "◎" },
  { href: "/study/anki", label: "Review", icon: "↻" },
  { href: "/achievements", label: "Awards", icon: "★" },
  { href: "/settings", label: "More", icon: "⋯" },
];

type Bar = Pick<GameStats, "level" | "xp" | "xp_into_level" | "xp_for_next" | "coins" | "streak">;

export default function AppShell({ user, children }: { user: User; children: React.ReactNode }) {
  const pathname = usePathname();
  const router = useRouter();
  const [bar, setBar] = useState<Bar>({
    level: user.level ?? 1, xp: user.xp ?? 0, xp_into_level: user.xp_into_level ?? 0,
    xp_for_next: user.xp_for_next ?? 100, coins: user.coins ?? 0, streak: user.streak ?? 0,
  });

  // The study screen announces fresh totals when a session is credited.
  useEffect(() => {
    const onStats = (e: Event) => setBar((e as CustomEvent<GameStats>).detail);
    window.addEventListener("game-stats", onStats);
    return () => window.removeEventListener("game-stats", onStats);
  }, []);

  async function logout() {
    await api.post("/api/auth/logout");
    router.push("/login");
  }

  // Most specific match wins, so /daily/listening doesn't also light up /daily.
  const matches = (href: string) => pathname === href || pathname.startsWith(href + "/");
  const activeHref = [...NAV, ...MOBILE_NAV].map((n) => n.href).filter(matches).sort((a, b) => b.length - a.length)[0];

  return (
    <div className="shell">
      <nav className="sidebar">
        <div className="brand">Lexi</div>
        {user.ielts_target && (
          <div className="sidebar-target">
            <span>Target</span>
            <strong>{user.ielts_target.toFixed(1)}</strong>
          </div>
        )}
        <div className="nav-group">
          {NAV.map((item) => (
            <Link key={item.href} href={item.href} className={item.href === activeHref ? "active" : ""}>
              <span className="nav-icon" aria-hidden="true">{item.icon}</span>{item.label}
            </Link>
          ))}
        </div>
        <div className="sidebar-spacer" />
        <a href="#" onClick={(e) => { e.preventDefault(); logout(); }}>Log out</a>
      </nav>

      <main className="content">
        <header className="topbar">
          <div className="topbar-level">
            <span className="level-chip">LEVEL {bar.level}</span>
            <div className="xp-track" title={`${bar.xp_into_level} / ${bar.xp_for_next} XP to level ${bar.level + 1}`}>
              <div style={{ width: `${(100 * bar.xp_into_level) / bar.xp_for_next}%` }} />
            </div>
            <span className="topbar-xp">⭐ {bar.xp.toLocaleString()} XP</span>
          </div>
          <span className="topbar-pill">🔥 {bar.streak} day streak</span>
          <span className="topbar-pill">🪙 {bar.coins.toLocaleString()}</span>
        </header>
        <DueBanner />
        {children}
      </main>

      <nav className="bottom-nav">
        {MOBILE_NAV.map((item) => (
          <Link key={item.href} href={item.href} className={item.href === activeHref ? "active" : ""}>
            <span aria-hidden="true">{item.icon}</span>
            {item.label}
          </Link>
        ))}
      </nav>
    </div>
  );
}

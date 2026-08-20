"use client";

import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { api } from "@/lib/api";
import type { User } from "@/lib/types";

/**
 * Desktop: grouped sidebar. Mobile: bottom navigation (5 destinations).
 *
 * ponytail: only routes that exist are listed. Practice / IELTS Tests /
 * Grammar / Speaking / Progress arrive with their phases - a nav item that
 * leads to an empty page is worse than no nav item.
 */
const NAV: { group: string; items: { href: string; label: string }[] }[] = [
  {
    group: "Study",
    items: [
      { href: "/dashboard", label: "Dashboard" },
      { href: "/practice", label: "Practice" },
      { href: "/daily", label: "Daily Practice" },
      { href: "/study/flashcards", label: "Review" },
      { href: "/listening/dictation", label: "Dictation" },
      { href: "/writing", label: "Writing" },
      { href: "/speaking", label: "Speaking" },
    ],
  },
  {
    group: "Library",
    items: [
      { href: "/library", label: "IELTS Library" },
      { href: "/vocabulary", label: "Vocabulary" },
      { href: "/sets", label: "Sets" },
    ],
  },
  {
    group: "Support",
    items: [
      { href: "/progress", label: "Progress" },
      { href: "/tutor", label: "AI Coach" },
      { href: "/settings", label: "Settings" },
    ],
  },
];

const MOBILE_NAV = [
  { href: "/dashboard", label: "Home", icon: "◈" },
  { href: "/practice", label: "Practice", icon: "◐" },
  { href: "/study/flashcards", label: "Review", icon: "↻" },
  { href: "/library", label: "Library", icon: "☰" },
  { href: "/settings", label: "More", icon: "⋯" },
];

export default function AppShell({ user, children }: { user: User; children: React.ReactNode }) {
  const pathname = usePathname();
  const router = useRouter();

  async function logout() {
    await api.post("/api/auth/logout");
    router.push("/login");
  }

  const active = (href: string) => pathname === href || pathname.startsWith(href + "/");

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
        {NAV.map((section) => (
          <div key={section.group} className="nav-group">
            <div className="nav-group-label">{section.group}</div>
            {section.items.map((item) => (
              <Link key={item.href} href={item.href} className={active(item.href) ? "active" : ""}>
                {item.label}
              </Link>
            ))}
          </div>
        ))}
        <div className="sidebar-spacer" />
        <div className="streak">🔥 {user.streak}-day streak</div>
        <a href="#" onClick={(e) => { e.preventDefault(); logout(); }}>Log out</a>
      </nav>

      <main className="content">{children}</main>

      <nav className="bottom-nav">
        {MOBILE_NAV.map((item) => (
          <Link key={item.href} href={item.href} className={active(item.href) ? "active" : ""}>
            <span aria-hidden="true">{item.icon}</span>
            {item.label}
          </Link>
        ))}
      </nav>
    </div>
  );
}

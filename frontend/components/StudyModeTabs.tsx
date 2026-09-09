"use client";

import Link from "next/link";

const MODES = [
  { href: "/study/anki", key: "anki", label: "Anki" },
  { href: "/study/learn", key: "learn", label: "Learn" },
] as const;

export default function StudyModeTabs({ active }: { active: (typeof MODES)[number]["key"] }) {
  return (
    <>
      {MODES.map((m) =>
        m.key === active ? (
          <span key={m.key} className="chip-select active">{m.label}</span>
        ) : (
          <Link key={m.key} href={m.href} className="chip-select">{m.label}</Link>
        )
      )}
    </>
  );
}

"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { api } from "@/lib/api";

/** Surfaces spaced-repetition due cards on every page - the reminder that
 * closes the loop on "studied today, needs review tomorrow" without the
 * learner having to remember to check the dashboard. Hidden on the review
 * pages themselves since it would just be pointing at the page you're on. */
export default function DueBanner() {
  const pathname = usePathname();
  const [due, setDue] = useState(0);

  useEffect(() => {
    let cancelled = false;
    api.get("/api/study/due").then((data) => {
      if (!cancelled) setDue(data.due);
    }).catch(() => {
      /* a missed reminder is not worth surfacing an error for */
    });
    return () => { cancelled = true; };
  }, [pathname]);

  if (due <= 0 || pathname.startsWith("/study")) return null;

  return (
    <div className="due-banner">
      <span className="due-banner-icon" aria-hidden="true">🔔</span>
      <span>
        <strong>{due}</strong> {due === 1 ? "word is" : "words are"} due for review today.
      </span>
      <Link href="/study/anki" className="btn small" style={{ marginLeft: "auto" }}>
        Review now
      </Link>
    </div>
  );
}

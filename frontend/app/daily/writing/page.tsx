"use client";

import Link from "next/link";
import Protected from "@/components/Protected";
import DailyWritingTask from "@/components/DailyWritingTask";

function Header() {
  return (
    <div className="toolbar">
      <Link href="/daily" className="subtitle">&larr; Today&apos;s practice</Link>
      <div className="spacer" />
      <h1 style={{ margin: 0 }}>✍️ Writing</h1>
    </div>
  );
}

export default function DailyWritingPage() {
  return (
    <Protected>
      {() => (
        <>
          <Header />
          <DailyWritingTask />
        </>
      )}
    </Protected>
  );
}

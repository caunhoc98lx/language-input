"use client";

import { useState } from "react";
import Protected from "@/components/Protected";
import TargetForm from "@/components/TargetForm";
import type { User } from "@/lib/types";

function SettingsContent({ user }: { user: User }) {
  const [saved, setSaved] = useState(false);

  return (
    <>
      <h1>Settings</h1>
      <p className="subtitle">Signed in as {user.email}</p>
      <div className="card" style={{ maxWidth: 620 }}>
        <h2>IELTS target</h2>
        <TargetForm user={user} submitLabel="Save changes" onSaved={() => setSaved(true)} />
        {saved && <p style={{ color: "var(--success)", marginTop: 12 }}>Saved.</p>}
      </div>
    </>
  );
}

export default function SettingsPage() {
  return <Protected>{(user) => <SettingsContent user={user} />}</Protected>;
}

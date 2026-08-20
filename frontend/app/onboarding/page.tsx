"use client";

import { useRouter } from "next/navigation";
import TargetForm from "@/components/TargetForm";
import { useUser } from "@/lib/useUser";

/** First-run setup. Deliberately outside AppShell: no navigation until there
 *  is a target to navigate towards. */
export default function OnboardingPage() {
  const { user, loading } = useUser();
  const router = useRouter();

  if (loading || !user) return null;

  return (
    <div className="onboard-page">
      <div className="onboard-card">
        <h1>🎯 Let&apos;s set your IELTS target</h1>
        <p className="subtitle">
          Everything else — your daily plan, your practice, your review queue — is built from these answers.
          You can change them any time in Settings.
        </p>
        <TargetForm user={user} submitLabel="Create my study plan" onSaved={() => router.push("/dashboard")} />
      </div>
    </div>
  );
}

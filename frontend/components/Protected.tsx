"use client";

import { useEffect } from "react";
import { usePathname, useRouter } from "next/navigation";
import { useUser } from "@/lib/useUser";
import type { User } from "@/lib/types";
import AppShell from "./AppShell";

export default function Protected({ children }: { children: (user: User) => React.ReactNode }) {
  const { user, loading } = useUser();
  const router = useRouter();
  const pathname = usePathname();

  // No target set yet -> finish setup first; the whole app is built around it.
  const needsOnboarding = !!user && !user.onboarded;
  useEffect(() => {
    if (needsOnboarding && pathname !== "/onboarding") router.replace("/onboarding");
  }, [needsOnboarding, pathname, router]);

  if (loading) return null;
  if (!user) return null; // useUser already redirects to /login
  if (needsOnboarding) return null;

  return <AppShell user={user}>{children(user)}</AppShell>;
}

"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { api, ApiError } from "./api";
import type { User } from "./types";

export function useUser() {
  const [user, setUser] = useState<User | null>(null);
  const [loading, setLoading] = useState(true);
  const router = useRouter();

  useEffect(() => {
    api
      .get("/api/auth/me")
      .then((data) => setUser(data))
      .catch((e) => {
        if (e instanceof ApiError && e.status === 401) router.push("/login");
      })
      .finally(() => setLoading(false));
  }, [router]);

  return { user, loading, setUser };
}

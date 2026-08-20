"use client";

import { useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { api, ApiError } from "@/lib/api";

export default function SignupPage() {
  const [name, setName] = useState("");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const router = useRouter();

  async function onSubmit(e: React.FormEvent) {
    e.preventDefault();
    setError(null);
    setBusy(true);
    try {
      await api.post("/api/auth/signup", { email, password, name });
      router.push("/dashboard");
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Something went wrong.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="auth-page">
      <div className="card auth-card">
        <h1>Create your account</h1>
        <p className="subtitle">Start learning English vocabulary with AI.</p>
        <form onSubmit={onSubmit}>
          <label>Name</label>
          <input type="text" value={name} onChange={(e) => setName(e.target.value)} />
          <label>Email</label>
          <input type="email" value={email} onChange={(e) => setEmail(e.target.value)} required autoFocus />
          <label>Password</label>
          <input type="password" value={password} onChange={(e) => setPassword(e.target.value)} required minLength={8} />
          {error && <div className="error">{error}</div>}
          <button className="btn" style={{ width: "100%", marginTop: 20 }} disabled={busy}>
            {busy ? "Signing up..." : "Sign up"}
          </button>
        </form>
        <p className="subtitle" style={{ marginTop: 16 }}>
          Already have an account? <Link href="/login" style={{ color: "var(--primary)", fontWeight: 600 }}>Log in</Link>
        </p>
      </div>
    </div>
  );
}

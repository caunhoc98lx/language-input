"use client";

/** Whole-app error boundary: something threw during render. Show what happened
 *  and a way out - never a blank page. */
export default function Error({ error, reset }: { error: Error; reset: () => void }) {
  return (
    <div className="auth-page">
      <div className="card auth-card">
        <h1>Something went wrong</h1>
        <p className="subtitle">{error.message || "An unexpected error occurred."}</p>
        <div style={{ display: "flex", gap: 10 }}>
          <button className="btn" onClick={reset}>
            Try again
          </button>
          <a className="btn secondary" href="/dashboard">
            Back to dashboard
          </a>
        </div>
      </div>
    </div>
  );
}

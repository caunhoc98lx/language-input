import Link from "next/link";

export default function NotFound() {
  return (
    <div className="auth-page">
      <div className="card auth-card">
        <h1>Page not found</h1>
        <p className="subtitle">That page does not exist.</p>
        <Link className="btn" href="/dashboard">
          Back to dashboard
        </Link>
      </div>
    </div>
  );
}

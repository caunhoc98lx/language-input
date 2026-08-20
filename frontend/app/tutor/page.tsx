"use client";

import { useEffect, useRef, useState } from "react";
import Protected from "@/components/Protected";
import { api } from "@/lib/api";

interface Message {
  role: "user" | "assistant";
  content: string;
  error?: boolean;
}

function TutorContent() {
  const [messages, setMessages] = useState<Message[]>([
    { role: "assistant", content: "Hi! I'm your English tutor. Ask me anything about vocabulary, grammar, or IELTS." },
  ]);
  const [input, setInput] = useState("");
  const [busy, setBusy] = useState(false);
  const scrollRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    scrollRef.current?.scrollTo({ top: scrollRef.current.scrollHeight });
  }, [messages]);

  async function send(e: React.FormEvent) {
    e.preventDefault();
    const text = input.trim();
    if (!text || busy) return;
    setInput("");
    const history = [...messages, { role: "user" as const, content: text }];
    setMessages(history);
    setBusy(true);
    try {
      const data = await api.post("/api/tutor", { history: history.map(({ role, content }) => ({ role, content })) });
      setMessages([...history, { role: "assistant", content: data.reply }]);
    } catch (err) {
      setMessages([...history, { role: "assistant", content: `Sorry, something went wrong: ${err instanceof Error ? err.message : "unknown error"}`, error: true }]);
    } finally {
      setBusy(false);
    }
  }

  return (
    <>
      <h1>AI Tutor</h1>
      <p className="subtitle">Ask about vocabulary, grammar, or IELTS usage. The tutor knows the words you&apos;ve been struggling with.</p>

      <div className="card" style={{ display: "flex", flexDirection: "column", height: "60vh", padding: 16 }}>
        <div ref={scrollRef} style={{ flex: 1, overflowY: "auto", display: "flex", flexDirection: "column", gap: 12, padding: 4 }}>
          {messages.map((m, i) => (
            <div
              key={i}
              style={{
                maxWidth: "75%",
                padding: "10px 14px",
                borderRadius: 14,
                whiteSpace: "pre-wrap",
                alignSelf: m.role === "user" ? "flex-end" : "flex-start",
                background: m.role === "user" ? "var(--primary)" : "var(--bg)",
                color: m.role === "user" ? "#fff" : m.error ? "var(--danger)" : "var(--text)",
                border: m.role === "assistant" ? "1px solid var(--border)" : undefined,
              }}
            >
              {m.content}
            </div>
          ))}
          {busy && (
            <div style={{ alignSelf: "flex-start", padding: "10px 14px", borderRadius: 14, background: "var(--bg)", border: "1px solid var(--border)" }}>
              ...
            </div>
          )}
        </div>
        <form onSubmit={send} style={{ display: "flex", gap: 10, marginTop: 12 }}>
          <input
            type="text"
            placeholder="e.g. What's the difference between affect and effect?"
            autoComplete="off"
            value={input}
            onChange={(e) => setInput(e.target.value)}
            required
          />
          <button className="btn" type="submit" disabled={busy}>Send</button>
        </form>
      </div>
    </>
  );
}

export default function TutorPage() {
  return <Protected>{() => <TutorContent />}</Protected>;
}

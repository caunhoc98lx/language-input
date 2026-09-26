"use client";

import { useEffect, useMemo, useState } from "react";
import { speak } from "@/lib/speech";
import { baseXp, checkTyped, type Question, type Round } from "@/lib/game";
import type { Vocab } from "@/lib/types";

/** One answer, reported to the session. `rate: false` = practice only, never
 * sent to the scheduler (learn cards, match rounds). */
export type Answer = { vocab?: Vocab; correct: boolean; base: number; typo?: boolean; rate?: boolean; keepCombo?: boolean };
export type Award = { xp: number; combo: number };
export type AwardFn = (a: Answer) => Award;

type RoundProps<R> = { round: R; award: AwardFn; onDone: (correct: boolean) => void };

// ---------- shared bits ----------

export function AudioButton({ word, large }: { word: string; large?: boolean }) {
  return (
    <button type="button" className={`speak-btn${large ? " speak-lg" : ""}`} aria-label={`Play pronunciation of ${word}`} onClick={() => speak(word)}>
      🔊
    </button>
  );
}

export function MemoryMeter({ value, compact }: { value: number; compact?: boolean }) {
  const tone = value >= 70 ? "strong" : value >= 40 ? "mid" : "weak";
  return (
    <div className={`memory-meter ${tone}${compact ? " compact" : ""}`} title="Memory strength: estimated chance you recall it right now">
      {!compact && <span>Memory</span>}
      <div className="memory-track"><div style={{ width: `${value}%` }} /></div>
      <b>{value}%</b>
    </div>
  );
}

function reminder(v: Vocab): string | null {
  return v.collocations[0] || v.memory_tip || v.examples[0] || null;
}

/** Correct / not-quite panel with a Continue button. Wrong answers show the
 * right one plus something to hold on to - never just a red X. */
function Feedback({ vocab, correct, typo, award, answer, onContinue, label = "Continue", title }: {
  vocab: Vocab; correct: boolean; typo?: boolean; award: Award; answer?: string; onContinue: () => void; label?: string; title?: string;
}) {
  const hint = reminder(vocab);
  return (
    <div className={`game-feedback ${correct ? "ok" : "miss"}`} role="status">
      {correct ? (
        <div className="fb-head">
          <strong>{title ?? (typo ? "✅ Accepted" : "🎉 Correct!")}</strong>
          {award.xp > 0 && <span className="fb-xp">+{award.xp} XP</span>}
          {award.combo > 1 && <span className="fb-combo">🔥 Combo x{award.combo}</span>}
        </div>
      ) : (
        <div className="fb-head"><strong>Not quite.</strong></div>
      )}
      {(!correct || typo) && (
        <div className="fb-body">
          <div>{typo ? "Watch the spelling:" : "Correct answer:"} <b className="fb-answer">{answer ?? vocab.word}</b> <AudioButton word={vocab.word} /></div>
          {hint && <div className="fb-hint">Remember: “{hint}”</div>}
        </div>
      )}
      <button className="btn" autoFocus onClick={onContinue}>{label}</button>
    </div>
  );
}

/** Keys 1-4 pick an option - handy on desktop, harmless on touch. */
function useNumberKeys(count: number, onPick: (i: number) => void, enabled: boolean) {
  useEffect(() => {
    if (!enabled) return;
    function onKey(e: KeyboardEvent) {
      if ((e.target as HTMLElement)?.tagName === "INPUT") return;
      const n = Number(e.key);
      if (n >= 1 && n <= count) onPick(n - 1);
    }
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [count, onPick, enabled]);
}

type Result = { correct: boolean; typo?: boolean; award: Award };

// ---------- 1. learn ----------

export function LearnRound({ round, award, onDone }: RoundProps<Extract<Round, { kind: "learn" }>>) {
  const v = round.vocab;
  useEffect(() => { speak(v.word); }, [v.word]);
  const example = v.examples[0];
  return (
    <div className="game-card learn-card">
      <div className="round-label">New word</div>
      <div className="word-row">
        <div className="game-word">{v.word}</div>
        <AudioButton word={v.word} large />
      </div>
      <div className="word-meta">
        {[v.pronunciation, v.part_of_speech].filter(Boolean).join(" · ")}
        {v.topic && <span className="topic-chip">{v.topic}</span>}
        {v.ielts_level && <span className="topic-chip muted">{v.ielts_level}</span>}
      </div>
      <div className="learn-translation">{v.translation}</div>
      {v.definition && <p className="learn-definition">{v.definition}</p>}
      {example && <blockquote className="learn-example">{example}</blockquote>}
      <div className="learn-grid">
        {v.collocations.length > 0 && <div><h4>Collocations</h4><div className="chip-list">{v.collocations.map((c) => <span key={c}>{c}</span>)}</div></div>}
        {v.word_family.length > 0 && <div><h4>Word family</h4><div className="chip-list">{v.word_family.map((c) => <span key={c}>{c}</span>)}</div></div>}
        {v.synonyms.length > 0 && <div><h4>Synonyms</h4><div className="chip-list">{v.synonyms.map((c) => <span key={c}>{c}</span>)}</div></div>}
      </div>
      {v.memory_tip && <div className="fb-hint">💡 {v.memory_tip}</div>}
      <button
        className="btn game-cta"
        autoFocus
        onClick={() => { award({ vocab: v, correct: true, base: baseXp(round), rate: false, keepCombo: true }); onDone(true); }}
      >
        Got it · +{baseXp(round)} XP
      </button>
    </div>
  );
}

// ---------- 2 / 4 / 7. choice (multiple choice, listening, context) ----------

export function ChoiceRound({ round, award, onDone }: RoundProps<Extract<Question, { kind: "choice" }>>) {
  const v = round.vocab;
  const [picked, setPicked] = useState<string | null>(null);
  const [result, setResult] = useState<Result | null>(null);
  const listening = round.mode === "listening";

  useEffect(() => { if (listening) speak(v.word); }, [listening, v.word]);

  function pick(opt: string) {
    if (result) return;
    const correct = opt === round.answer;
    setPicked(opt);
    setResult({ correct, award: award({ vocab: v, correct, base: baseXp(round) }) });
    if (!listening) speak(v.word);
  }
  useNumberKeys(round.options.length, (i) => pick(round.options[i]), !result);

  const long = round.options.some((o) => o.length > 28);
  return (
    <div className="game-card">
      <div className="round-label">{listening ? "Listening challenge" : round.mode === "context" ? "Context challenge" : "Multiple choice"}</div>
      {listening ? (
        <button type="button" className="listen-orb" onClick={() => speak(v.word)} aria-label="Play the word again">🔊<small>Play again</small></button>
      ) : round.mode === "context" ? (
        <>
          {v.topic && <span className="topic-chip">IELTS · {v.topic}</span>}
          <p className="context-sentence">{round.stem}</p>
        </>
      ) : (
        <div className="word-row"><div className="game-word">{v.word}</div><AudioButton word={v.word} /></div>
      )}
      <div className="round-prompt">{round.prompt}</div>
      <div className={`options${long ? " stacked" : ""}`}>
        {round.options.map((opt, i) => {
          const state = !result ? "" : opt === round.answer ? " right" : opt === picked ? " wrong" : " dim";
          return (
            <button key={opt} className={`option${state}`} onClick={() => pick(opt)} disabled={!!result}>
              <span className="kbd">{i + 1}</span>{opt}
            </button>
          );
        })}
      </div>
      {result && <Feedback vocab={v} correct={result.correct} award={result.award} answer={round.answer} onContinue={() => onDone(result.correct)} />}
    </div>
  );
}

// ---------- 3. type the word ----------

export function TypeRound({ round, award, onDone }: RoundProps<Extract<Question, { kind: "type" }>>) {
  const v = round.vocab;
  const [value, setValue] = useState("");
  const [result, setResult] = useState<Result | null>(null);
  const [missed, setMissed] = useState(false); // red border until they get it
  const [toast, setToast] = useState(0); // >0 = the answer is briefly on screen

  useEffect(() => {
    if (!toast) return;
    const t = setTimeout(() => setToast(0), 2500);
    return () => clearTimeout(t);
  }, [toast]);

  function check() {
    if (result || !value.trim()) return;
    const verdict = checkTyped(value, v.word);
    speak(v.word);
    if (verdict === "wrong") {
      // First miss is what the scheduler hears ("again"); after that the
      // answer flashes up briefly and they type it again from memory.
      if (!missed) award({ vocab: v, correct: false, base: baseXp(round) });
      setMissed(true);
      setValue("");
      setToast(Date.now());
      return;
    }
    const typo = verdict === "typo";
    // Retyped after a miss: a little XP for producing it, full XP only first try.
    const base = missed ? Math.round(baseXp(round) * 0.4) : baseXp(round);
    setResult({ correct: true, typo, award: award({ vocab: v, correct: true, typo, base }) });
  }

  return (
    <div className="game-card">
      <div className="round-label">Type the word</div>
      <div className="learn-translation">{v.translation || "—"}</div>
      {v.definition && <p className="learn-definition">{v.definition}{v.part_of_speech && <em> ({v.part_of_speech})</em>}</p>}
      <div className="type-row">
        {toast > 0 && (
          <div key={toast} className="type-toast" role="status">
            <span>Correct answer</span><b>{v.word}</b>
          </div>
        )}
        <input
          key={toast /* remount replays the shake and re-focuses via autoFocus */}
          type="text"
          autoComplete="off"
          autoCapitalize="off"
          spellCheck={false}
          placeholder={`${v.word[0]}${"_".repeat(Math.max(v.word.length - 1, 0))}`}
          value={value}
          autoFocus
          disabled={!!result}
          onChange={(e) => setValue(e.target.value)}
          onKeyDown={(e) => { if (e.key === "Enter") check(); }}
          className={result ? "input-ok" : missed ? "input-miss" : ""}
          aria-label="Your answer"
        />
        {!result && <button className="btn" onClick={check} disabled={!value.trim()}>Check</button>}
      </div>
      {missed && !result && !toast && <div className="fb-hint">Type it again from memory.</div>}
      {result && (
        <Feedback vocab={v} correct typo={result.typo} award={result.award} title={missed ? "✅ Got it this time" : undefined}
          onContinue={() => onDone(true)} />
      )}
    </div>
  );
}

// ---------- 6. sentence builder ----------

export function SentenceRound({ round, award, onDone }: RoundProps<Extract<Question, { kind: "sentence" }>>) {
  const v = round.vocab;
  const [built, setBuilt] = useState<number[]>([]); // indexes into round.tokens
  const [result, setResult] = useState<Result | null>(null);
  const complete = built.length === round.tokens.length;

  function check() {
    if (result || !complete) return;
    const correct = built.map((i) => round.tokens[i]).join(" ").toLowerCase() === round.sentence.trim().replace(/\s+/g, " ").toLowerCase();
    setResult({ correct, award: award({ vocab: v, correct, base: baseXp(round) }) });
    speak(round.sentence);
  }

  return (
    <div className="game-card">
      <div className="round-label">Sentence builder</div>
      <div className="round-prompt">Rebuild the sentence using <b>{v.word}</b> <AudioButton word={v.word} /></div>
      <div className={`sentence-line${result ? (result.correct ? " ok" : " miss") : ""}`}>
        {built.length === 0 && <span className="placeholder">Tap the words below in order</span>}
        {built.map((ti, pos) => (
          <button key={ti} className="token" disabled={!!result} onClick={() => setBuilt(built.filter((_, p) => p !== pos))}>{round.tokens[ti]}</button>
        ))}
      </div>
      <div className="token-bank">
        {round.tokens.map((t, ti) => (
          <button key={ti} className="token" disabled={built.includes(ti) || !!result} onClick={() => setBuilt([...built, ti])}>{t}</button>
        ))}
      </div>
      {!result && (
        <div className="round-actions">
          <button className="btn secondary" onClick={() => setBuilt([])} disabled={!built.length}>Clear</button>
          <button className="btn" onClick={check} disabled={!complete}>Check</button>
        </div>
      )}
      {result && <Feedback vocab={v} correct={result.correct} award={result.award} answer={round.sentence} onContinue={() => onDone(result.correct)} />}
    </div>
  );
}

// ---------- 5. word match ----------

const MATCH_SECONDS = 60;

export function MatchRound({ round, award, onDone }: RoundProps<Extract<Round, { kind: "match" }>>) {
  // Two stages on one timer: word <-> Vietnamese, then word <-> definition.
  const [stage, setStage] = useState<0 | 1>(0);
  const [done, setDone] = useState<number[]>([]);
  const [sel, setSel] = useState<number | null>(null);
  const [flash, setFlash] = useState<number | null>(null);
  const [mistakes, setMistakes] = useState(0);
  const [left, setLeft] = useState(MATCH_SECONDS);
  const [result, setResult] = useState<(Result & { timeout: boolean }) | null>(null);

  const field = stage === 0 ? "translation" : "definition";
  // Right column in a stable order that differs from the left - sorting by
  // the text is enough to break the visual alignment without randomness.
  const right = useMemo(() => [...round.words].sort((a, b) => a[field].localeCompare(b[field])), [round.words, field]);

  const timeUp = left <= 0;

  function finish(timeout: boolean) {
    const correct = !timeout;
    // Finishing with slips still earns something - only the perfect run gets the full 30.
    const base = mistakes === 0 ? baseXp(round) : Math.round(baseXp(round) * 0.6);
    setResult({ correct, timeout, award: award({ correct, base, rate: false }) });
  }

  useEffect(() => {
    if (result || timeUp) return;
    const t = setInterval(() => setLeft((s) => s - 1), 1000);
    return () => clearInterval(t);
  }, [result, timeUp]);

  function pickRight(id: number) {
    if (sel === null || result || timeUp) return;
    if (id === sel) {
      const next = [...done, id];
      setSel(null);
      speak(round.words.find((w) => w.id === id)!.word);
      if (next.length < round.words.length) setDone(next);
      else if (stage === 0) { setStage(1); setDone([]); }
      else { setDone(next); finish(false); }
    } else {
      setMistakes((m) => m + 1);
      setFlash(id);
      setTimeout(() => setFlash(null), 450);
    }
  }

  return (
    <div className="game-card">
      <div className="round-label">Word match · {stage === 0 ? "Vietnamese meaning" : "English definition"}</div>
      <div className="timer-track" aria-label={`${left} seconds left`}><div style={{ width: `${(100 * Math.max(left, 0)) / MATCH_SECONDS}%` }} /></div>
      <div className="match-grid">
        <div className="match-col">
          {round.words.map((w) => (
            <button key={w.id} className={`match-item${done.includes(w.id) ? " matched" : ""}${sel === w.id ? " selected" : ""}`}
              disabled={done.includes(w.id) || !!result} onClick={() => setSel(w.id)}>{w.word}</button>
          ))}
        </div>
        <div className="match-col">
          {right.map((w) => (
            <button key={w.id} className={`match-item small${done.includes(w.id) ? " matched" : ""}${flash === w.id ? " miss" : ""}`}
              disabled={done.includes(w.id) || !!result} onClick={() => pickRight(w.id)}>{w[field]}</button>
          ))}
        </div>
      </div>
      {timeUp && !result && (
        <div className="game-feedback miss" role="status">
          <div className="fb-head"><strong>⏱ Time&apos;s up</strong></div>
          <button className="btn" autoFocus onClick={() => finish(true)}>See the answers</button>
        </div>
      )}
      {result && (
        <div className={`game-feedback ${result.correct ? "ok" : "miss"}`} role="status">
          <div className="fb-head">
            <strong>{result.timeout ? "⏱ Time's up — good effort!" : mistakes === 0 ? "🎉 Perfect match!" : "✅ All matched!"}</strong>
            {result.award.xp > 0 && <span className="fb-xp">+{result.award.xp} XP</span>}
            {result.award.combo > 1 && <span className="fb-combo">🔥 Combo x{result.award.combo}</span>}
          </div>
          <div className="fb-body match-review">
            {round.words.map((w) => <div key={w.id}><b>{w.word}</b> — {w.translation}</div>)}
          </div>
          <button className="btn" autoFocus onClick={() => onDone(result.correct)}>Continue</button>
        </div>
      )}
    </div>
  );
}

// ---------- 8 / 9. word battle & final boss ----------

export function QuestionView({ q, award, onDone }: { q: Question; award: AwardFn; onDone: (correct: boolean) => void }) {
  if (q.kind === "choice") return <ChoiceRound round={q} award={award} onDone={onDone} />;
  if (q.kind === "type") return <TypeRound round={q} award={award} onDone={onDone} />;
  return <SentenceRound round={q} award={award} onDone={onDone} />;
}

/**
 * A monster with 100 HP; each correct answer hits it. In a Word Battle a
 * miss just means "try that one again" (no damage taken, no HP lost). In
 * the Final Boss every question is asked once and 4 hits out of 5 win.
 */
export function ArenaRound({ round, award, onDone }: RoundProps<Extract<Round, { kind: "battle" | "boss" }>>) {
  const boss = round.kind === "boss";
  const damage = boss ? 25 : Math.ceil(100 / round.questions.length);
  const [qi, setQi] = useState(0);
  const [attempt, setAttempt] = useState(0);
  const [hp, setHp] = useState(100);
  const [hitKey, setHitKey] = useState(0);

  const arenaAward: AwardFn = (a) => {
    if (a.correct) { setHp((h) => Math.max(0, h - damage)); setHitKey((k) => k + 1); }
    return award({ ...a, base: baseXp(round) });
  };

  function next(correct: boolean) {
    if (!boss && !correct) { setAttempt((n) => n + 1); return; } // retry the same question
    if (qi + 1 < round.questions.length) { setQi(qi + 1); setAttempt(0); }
    else onDone(boss ? hp <= 0 : true);
  }

  return (
    <div className={`arena${boss ? " boss" : ""}`}>
      <div className="arena-head">
        <div key={hitKey} className={`monster${hitKey ? " hit" : ""}`} aria-hidden="true">{hp <= 0 ? "💥" : boss ? "🐉" : "👾"}</div>
        <div className="arena-info">
          <div className="arena-title">{boss ? "Final Boss · Lexicon Dragon" : "Word Battle"}</div>
          <div className="hp-track" aria-label={`Monster HP ${hp} of 100`}><div style={{ width: `${hp}%` }} /></div>
          <div className="arena-sub">{hp} / 100 HP · Question {qi + 1} of {round.questions.length}</div>
        </div>
      </div>
      <QuestionView key={`${qi}-${attempt}`} q={round.questions[qi]} award={arenaAward} onDone={next} />
    </div>
  );
}

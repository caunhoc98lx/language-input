"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import Link from "next/link";
import { useSearchParams } from "next/navigation";
import Protected from "@/components/Protected";
import Confetti, { makeConfettiPieces, type ConfettiPiece } from "@/components/Confetti";
import StudyModeTabs from "@/components/StudyModeTabs";
import Cheer3DLayout, { type CheerMood } from "@/components/Cheer3DLayout";
import {
  ArenaRound, ChoiceRound, LearnRound, MatchRound, MemoryMeter, SentenceRound, TypeRound,
  type AwardFn,
} from "@/components/GameRounds";
import { api, newRequestId } from "@/lib/api";
import { buildSession, coinsFor, pickWords, retryFor, xpWithCombo, type Round } from "@/lib/game";
import type { Achievement, GameStats, PoolWord, Vocab } from "@/lib/types";

/**
 * Gamified study session. The FSRS queue from /api/study/flashcards still
 * decides which words are due; this screen only changes how they're
 * practised. Each word's first graded answer in the session is sent to
 * /api/review as its rating (correct -> good, correct with a typo -> hard,
 * miss -> again); later rounds on the same word are practice and never
 * touch the schedule.
 */

type Tally = { xp: number; combo: number; best: number; correct: number; total: number };
const ZERO: Tally = { xp: 0, combo: 0, best: 0, correct: 0, total: 0 };

type Session = { rounds: Round[]; words: Vocab[]; pool: PoolWord[]; more: boolean; requestId: string };

const isQuestion = (r: Round) => r.kind === "choice" || r.kind === "type" || r.kind === "sentence";

function RoundView({ round, award, onDone }: { round: Round; award: AwardFn; onDone: (correct: boolean) => void }) {
  switch (round.kind) {
    case "learn": return <LearnRound round={round} award={award} onDone={onDone} />;
    case "choice": return <ChoiceRound round={round} award={award} onDone={onDone} />;
    case "type": return <TypeRound round={round} award={award} onDone={onDone} />;
    case "sentence": return <SentenceRound round={round} award={award} onDone={onDone} />;
    case "match": return <MatchRound round={round} award={award} onDone={onDone} />;
    case "battle":
    case "boss": return <ArenaRound round={round} award={award} onDone={onDone} />;
  }
}

function GameContent() {
  const setId = useSearchParams().get("set_id") || "";
  const [session, setSession] = useState<Session | null>(null);
  const [empty, setEmpty] = useState(false);
  const [loadKey, setLoadKey] = useState(0);
  const [idx, setIdx] = useState(0);
  const [tally, setTally] = useState<Tally>(ZERO);
  const tallyRef = useRef<Tally>(ZERO); // award() must return the new combo synchronously
  const rated = useRef(new Set<number>());
  const [memory, setMemory] = useState<Record<number, number>>({});
  const [gain, setGain] = useState<{ xp: number; key: number } | null>(null);
  const [confetti, setConfetti] = useState<ConfettiPiece[] | null>(null);
  const [bossWon, setBossWon] = useState(false);
  const [chest, setChest] = useState(0);
  const [mood, setMood] = useState<CheerMood>("idle");
  const moodTimer = useRef<ReturnType<typeof setTimeout> | null>(null);

  /** Cheerleaders react to an answer, then settle back to idle. */
  const react = useCallback((m: CheerMood) => {
    if (moodTimer.current) clearTimeout(moodTimer.current);
    setMood(m);
    moodTimer.current = m === "idle" ? null : setTimeout(() => setMood("idle"), 1800);
  }, []);
  useEffect(() => () => { if (moodTimer.current) clearTimeout(moodTimer.current); }, []);

  useEffect(() => {
    let cancelled = false;
    const params = setId ? `?set_id=${setId}` : "";
    api.get(`/api/study/flashcards${params}`).then((data: { queue: Vocab[]; pool: PoolWord[] }) => {
      if (cancelled) return;
      const words = pickWords(data.queue);
      tallyRef.current = ZERO;
      rated.current = new Set();
      setTally(ZERO);
      setIdx(0);
      setBossWon(false);
      setConfetti(null);
      setMemory(Object.fromEntries(words.map((w) => [w.id, w.memory_strength])));
      setEmpty(words.length === 0);
      setSession({
        rounds: buildSession(words, data.pool), words, pool: data.pool,
        more: data.queue.length > words.length, requestId: newRequestId(),
      });
    });
    return () => { cancelled = true; };
  }, [setId, loadKey]);

  const rate = useCallback(async (v: Vocab, rating: "again" | "hard" | "good") => {
    rated.current.add(v.id);
    try {
      const res = await api.post("/api/review", { vocabulary_id: v.id, rating, request_id: newRequestId() });
      if (typeof res.memory_strength === "number") setMemory((m) => ({ ...m, [v.id]: res.memory_strength }));
    } catch {
      rated.current.delete(v.id); // let a later answer this session carry the rating instead
    }
  }, []);

  const award: AwardFn = useCallback((a) => {
    const t = tallyRef.current;
    let combo = t.combo;
    let xp = 0;
    if (a.correct) {
      if (!a.keepCombo) combo += 1;
      xp = a.keepCombo ? a.base : xpWithCombo(a.base, combo);
    } else {
      combo = 0; // the only "penalty": the streak of answers restarts, nothing is taken away
    }
    const counts = !a.keepCombo;
    const next: Tally = {
      xp: t.xp + xp, combo, best: Math.max(t.best, combo),
      correct: t.correct + (counts && a.correct ? 1 : 0), total: t.total + (counts ? 1 : 0),
    };
    tallyRef.current = next;
    setTally(next);
    if (xp) setGain({ xp, key: Date.now() });
    if (a.correct && !a.keepCombo && combo % 5 === 0) setConfetti(makeConfettiPieces(40));
    // Learn cards (keepCombo) aren't answers, so they don't move the cheerleaders.
    if (!a.keepCombo) react(!a.correct ? "wrong" : t.combo >= 5 ? "streak" : "correct");
    if (a.vocab && a.rate !== false && !rated.current.has(a.vocab.id)) {
      rate(a.vocab, a.correct ? (a.typo ? "hard" : "good") : "again");
    }
    return { xp, combo };
  }, [rate, react]);

  if (!session) return null;

  const { rounds } = session;
  const round = rounds[idx];

  function next(correct: boolean) {
    if (!session) return;
    let updated = session.rounds;
    if (!correct && round && isQuestion(round) && updated.length < 22) {
      // A miss comes back a few rounds later as a different question type.
      const retry = retryFor((round as Extract<Round, { vocab: Vocab }>).vocab, [...session.words, ...session.pool]);
      if (retry) {
        const bossAt = updated[updated.length - 1]?.kind === "boss" ? updated.length - 1 : updated.length;
        updated = [...updated];
        updated.splice(Math.min(idx + 3, bossAt), 0, retry);
      }
    }
    if (round?.kind === "boss") setBossWon(correct);
    if (idx + 1 >= updated.length) {
      setChest(10 + Math.floor(Math.random() * 21) + (round?.kind === "boss" && correct ? 25 : 0));
      setConfetti(makeConfettiPieces());
    }
    setSession({ ...session, rounds: updated });
    setIdx(idx + 1);
    react("idle");
  }

  const current = round && round.kind !== "match" && round.kind !== "battle" && round.kind !== "boss" ? round.vocab : null;

  return (
    <>
      <div className="toolbar">
        <h1 style={{ margin: 0 }}>Vocabulary quest</h1>
        <div className="spacer" />
        <StudyModeTabs active="game" />
      </div>
      <Confetti key={confetti ? tally.xp : 0} pieces={confetti} />

      {empty ? (
        <div className="card empty-state">
          <h2>All caught up 🎉</h2>
          <p>Nothing is due and there are no new words for today. Add vocabulary or come back later.</p>
          <Link href="/vocabulary/new" className="btn" style={{ marginTop: 10, display: "inline-flex" }}>Add vocabulary</Link>
        </div>
      ) : !round ? (
        <SessionComplete
          tally={tally} bossWon={bossWon} chest={chest} words={session.words} memory={memory}
          requestId={session.requestId} more={session.more} onNext={() => setLoadKey((k) => k + 1)}
        />
      ) : (
        <Cheer3DLayout mood={mood} left="luna" right="mira">
          <div className="game-stage">
            <div className="game-hud">
              <div className="hud-progress">
                <span>{round.kind === "boss" ? "Final Boss" : `Round ${idx + 1} of ${rounds.length}`}</span>
                <div className="progress-bar"><div className="progress-bar-fill" style={{ width: `${(100 * idx) / rounds.length}%` }} /></div>
              </div>
              <div className="hud-stat">
                ⭐ <b>{tally.xp}</b> XP
                {gain && <span key={gain.key} className="xp-float">+{gain.xp}</span>}
              </div>
              <div key={tally.combo} className={`combo-pill${tally.combo > 1 ? " live" : ""}`}>🔥 x{Math.max(tally.combo, 1)}</div>
            </div>
            {current && current.srs_state !== "NEW" && <MemoryMeter value={memory[current.id] ?? current.memory_strength} />}
            <RoundView key={idx} round={round} award={award} onDone={next} />
          </div>
        </Cheer3DLayout>
      )}
    </>
  );
}

function SessionComplete({ tally, bossWon, chest, words, memory, requestId, more, onNext }: {
  tally: Tally; bossWon: boolean; chest: number; words: Vocab[]; memory: Record<number, number>;
  requestId: string; more: boolean; onNext: () => void;
}) {
  const [opened, setOpened] = useState(false);
  const [result, setResult] = useState<{ stats: GameStats; new_achievements: Achievement[] } | null>(null);
  const [error, setError] = useState("");
  const sent = useRef(false);
  const coins = coinsFor(tally.xp) + chest;
  const accuracy = tally.total ? Math.round((100 * tally.correct) / tally.total) : 0;

  useEffect(() => {
    if (sent.current) return;
    sent.current = true;
    api.post("/api/game/session", {
      request_id: requestId, xp: tally.xp, coins, best_combo: tally.best,
      correct: tally.correct, total: tally.total, boss_won: bossWon,
    }).then((res) => {
      setResult(res);
      window.dispatchEvent(new CustomEvent("game-stats", { detail: res.stats }));
    }).catch((e) => setError(e.message || "Couldn't save your rewards."));
  }, [requestId, tally, coins, bossWon]);

  const s = result?.stats;
  return (
    <div className="game-stage">
      <div className="game-card complete-card">
        <div className="round-label">Session complete</div>
        <h2>{bossWon ? "⚔️ Boss defeated!" : "🏁 Quest finished"}</h2>
        <p className="subtitle" style={{ margin: 0 }}>
          {bossWon ? "The Lexicon Dragon is down. Your words are stronger for it." : "The boss got away this time, and every word still got practice."}
        </p>

        <div className="reward-grid">
          <div><b>+{tally.xp}</b><span>XP</span></div>
          <div><b>🪙 {coinsFor(tally.xp) + (opened ? chest : 0)}</b><span>Coins</span></div>
          <div><b>🔥 x{tally.best}</b><span>Best combo</span></div>
          <div><b>{accuracy}%</b><span>Accuracy</span></div>
        </div>

        <button className={`chest${opened ? " open" : ""}`} onClick={() => setOpened(true)} disabled={opened}>
          <span aria-hidden="true">{opened ? "🪙" : "🎁"}</span>
          {opened ? `Chest opened: +${chest} bonus coins` : "Open your reward chest"}
        </button>

        {s && (
          <div className="level-block">
            <div className="level-row"><b>Level {s.level}</b><span>{s.xp_into_level} / {s.xp_for_next} XP</span></div>
            <div className="xp-track"><div style={{ width: `${(100 * s.xp_into_level) / s.xp_for_next}%` }} /></div>
          </div>
        )}
        {error && <p className="error">{error}</p>}

        {result && result.new_achievements.length > 0 && (
          <div className="new-badges">
            {result.new_achievements.map((a) => (
              <div key={a.key} className="badge-card unlocked pop"><span>{a.icon}</span><div><b>{a.title}</b><small>{a.description}</small></div></div>
            ))}
          </div>
        )}

        <h3 className="memory-title">Memory progress</h3>
        <div className="memory-list">
          {words.map((w) => {
            const after = memory[w.id] ?? w.memory_strength;
            const delta = after - w.memory_strength;
            return (
              <div key={w.id} className="memory-item">
                <span className="memory-word">{w.word}</span>
                <MemoryMeter value={after} compact />
                {delta !== 0 && <span className={`delta ${delta > 0 ? "up" : "down"}`}>{delta > 0 ? "+" : ""}{delta}</span>}
              </div>
            );
          })}
        </div>
        <p className="subtitle memory-note">The scheduler brings each word back right before you&apos;re likely to forget it.</p>

        <div className="round-actions">
          <Link href="/dashboard" className="btn secondary">Dashboard</Link>
          {more ? <button className="btn" onClick={onNext}>Next session</button> : <Link href="/achievements" className="btn">View achievements</Link>}
        </div>
      </div>
    </div>
  );
}

export default function GamePage() {
  return <Protected>{() => <GameContent />}</Protected>;
}

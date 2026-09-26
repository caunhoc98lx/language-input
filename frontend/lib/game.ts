/**
 * Game layer for the study screen: turns the scheduler's queue into a
 * session of mixed mini-game rounds. Pure functions only - no React, no
 * fetches - so the rules are checkable on their own (see game.check.ts).
 *
 * The scheduler stays in charge: which words appear, and when they come
 * back, is decided by the backend FSRS queue. This file only decides *how*
 * each word is practised in this session.
 */
import type { PoolWord, Vocab } from "@/lib/types";

export const IELTS_TOPICS = [
  "Education", "Environment", "Technology", "Health", "Work", "Business", "Society",
  "Crime", "Government", "Culture", "Travel", "Science", "Media",
] as const;

export type ChoiceMode = "translation" | "meaning" | "usage" | "synonym" | "antonym" | "listening" | "context";

/** A single-word question - these are the rounds that can rate a word. */
export type Question =
  | { kind: "choice"; mode: ChoiceMode; vocab: Vocab; prompt: string; stem?: string; options: string[]; answer: string }
  | { kind: "type"; vocab: Vocab }
  | { kind: "sentence"; vocab: Vocab; sentence: string; tokens: string[] };

export type Round =
  | { kind: "learn"; vocab: Vocab }
  | Question
  | { kind: "match"; words: Vocab[] }
  | { kind: "battle"; questions: Question[] }
  | { kind: "boss"; questions: Question[] };

export const SESSION_LENGTH = 15;

/** Base XP per interaction type, before the combo bonus. */
export function baseXp(round: Round): number {
  switch (round.kind) {
    case "learn": return 10;
    case "type": return 25;
    case "sentence": return 30;
    case "match": return 30;
    case "battle": return 25;
    case "boss": return 25;
    case "choice": return round.mode === "listening" ? 20 : round.mode === "context" ? 25 : 15;
  }
}

/** Combo adds 10% per consecutive correct answer, capped at +100% (x11). */
export function xpWithCombo(base: number, combo: number): number {
  return Math.round(base * (1 + 0.1 * Math.min(Math.max(combo - 1, 0), 10)));
}

export function coinsFor(xp: number): number {
  return Math.floor(xp / 10);
}

// ---------- typed answers ----------

function levenshtein(a: string, b: string): number {
  const row = Array.from({ length: b.length + 1 }, (_, j) => j);
  for (let i = 1; i <= a.length; i++) {
    let prev = row[0];
    row[0] = i;
    for (let j = 1; j <= b.length; j++) {
      const tmp = row[j];
      row[j] = Math.min(row[j] + 1, row[j - 1] + 1, prev + (a[i - 1] === b[j - 1] ? 0 : 1));
      prev = tmp;
    }
  }
  return row[b.length];
}

const norm = (s: string) => s.trim().toLowerCase().replace(/\s+/g, " ");

/** "typo" = accepted but not perfect: 1 edit allowed from 5 letters, 2 from 9. */
export function checkTyped(input: string, answer: string): "exact" | "typo" | "wrong" {
  const a = norm(input), b = norm(answer);
  if (!a) return "wrong";
  if (a === b) return "exact";
  const allowed = b.length >= 9 ? 2 : b.length >= 5 ? 1 : 0;
  return levenshtein(a, b) <= allowed ? "typo" : "wrong";
}

// ---------- helpers ----------

export function shuffle<T>(arr: T[]): T[] {
  const a = [...arr];
  for (let i = a.length - 1; i > 0; i--) {
    const j = Math.floor(Math.random() * (i + 1));
    [a[i], a[j]] = [a[j], a[i]];
  }
  return a;
}

const escapeRe = (s: string) => s.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
const wordRe = (word: string) => new RegExp(`\\b${escapeRe(word.trim())}\\b`, "i");

/** First example sentence that actually contains the word. */
export function sentenceWith(v: { word: string; examples: string[] }): string | undefined {
  return v.examples.find((e) => wordRe(v.word).test(e));
}

export function blankOut(sentence: string, word: string): string {
  return sentence.replace(wordRe(word), "_____");
}

/** 3 distinct wrong options plus the answer, shuffled - or null if the
 * learner doesn't have enough other words yet to make a fair question. */
function optionsFrom(answer: string, candidates: string[]): string[] | null {
  const seen = new Set([norm(answer)]);
  const wrong: string[] = [];
  for (const c of shuffle(candidates)) {
    if (!c || seen.has(norm(c))) continue;
    seen.add(norm(c));
    wrong.push(c);
    if (wrong.length === 3) return shuffle([answer, ...wrong]);
  }
  return null;
}

// ---------- round generation ----------

export type QuestionType = ChoiceMode | "type" | "sentence";

export function makeQuestion(v: Vocab, type: QuestionType, others: PoolWord[]): Question | null {
  const choice = (mode: ChoiceMode, prompt: string, answer: string, candidates: string[], stem?: string): Question | null => {
    const options = optionsFrom(answer, candidates);
    return options ? { kind: "choice", mode, vocab: v, prompt, stem, options, answer } : null;
  };
  const sentence = sentenceWith(v);

  switch (type) {
    case "translation":
      return v.translation ? choice("translation", `What does “${v.word}” mean in Vietnamese?`, v.translation, others.map((o) => o.translation)) : null;
    case "meaning":
      return v.definition ? choice("meaning", `Which definition matches “${v.word}”?`, v.definition, others.map((o) => o.definition)) : null;
    case "synonym":
      return v.synonyms[0] ? choice("synonym", `Which word is closest in meaning to “${v.word}”?`, v.synonyms[0], others.map((o) => o.word).filter((w) => !v.synonyms.includes(w))) : null;
    case "antonym":
      return v.antonyms[0] ? choice("antonym", `Which word is the opposite of “${v.word}”?`, v.antonyms[0], others.map((o) => o.word).filter((w) => !v.antonyms.includes(w))) : null;
    case "listening":
      return choice("listening", "Listen and choose the word you hear", v.word, others.map((o) => o.word));
    case "context":
      return sentence ? choice("context", "Complete the sentence", v.word, others.map((o) => o.word), blankOut(sentence, v.word)) : null;
    case "usage": {
      if (!sentence) return null;
      // Wrong options: another word's real sentence with this word swapped in.
      const misuses = others.flatMap((o) => {
        const s = sentenceWith(o);
        return s ? [s.replace(wordRe(o.word), v.word)] : [];
      });
      return choice("usage", `Which sentence uses “${v.word}” correctly?`, sentence, misuses);
    }
    case "type":
      return v.translation || v.definition ? { kind: "type", vocab: v } : null;
    case "sentence": {
      const tokens = sentence?.split(/\s+/) ?? [];
      return sentence && tokens.length >= 4 && tokens.length <= 14
        ? { kind: "sentence", vocab: v, sentence, tokens: shuffle(tokens) }
        : null;
    }
  }
}

/** A bag that hands out question types evenly: whichever type was used
 * least recently and fits the word goes next. */
function typeBag(types: QuestionType[]) {
  let order = shuffle(types);
  return (v: Vocab, others: PoolWord[]): Question | null => {
    for (const t of order) {
      const q = makeQuestion(v, t, others);
      if (q) {
        order = [...order.filter((x) => x !== t), t];
        return q;
      }
    }
    return null;
  };
}

const GRADED_TYPES: QuestionType[] = ["translation", "meaning", "type", "listening", "context", "sentence", "type", "synonym", "usage"];
const QUICK_TYPES: QuestionType[] = ["translation", "meaning", "context", "listening", "synonym", "antonym"];
const BOSS_TYPES: QuestionType[] = ["type", "context", "listening", "meaning", "sentence", "translation", "usage"];

/** Pick this session's words from the front of the scheduler queue (the
 * queue is already in priority order). New words cost two rounds (learn +
 * question), known words one. */
export function pickWords(queue: Vocab[], budget = 10, maxWords = 8): Vocab[] {
  const words: Vocab[] = [];
  let cost = 0;
  for (const v of queue) {
    const c = v.srs_state === "NEW" ? 2 : 1;
    if (words.length >= maxWords || cost + c > budget) break;
    words.push(v);
    cost += c;
  }
  return words;
}

export function othersFor(v: { id: number; word: string }, pool: PoolWord[]): PoolWord[] {
  return pool.filter((o) => o.id !== v.id && norm(o.word) !== norm(v.word));
}

/**
 * Build one session: every word gets a Learn card (if new) and exactly one
 * graded question, then practice rounds (match, battle, extra questions)
 * fill up to SESSION_LENGTH - 1, and a Final Boss closes it.
 */
export function buildSession(words: Vocab[], pool: PoolWord[], length = SESSION_LENGTH): Round[] {
  if (words.length === 0) return [];
  const all: PoolWord[] = [...words, ...pool.filter((p) => !words.some((w) => w.id === p.id))];
  const graded = typeBag(GRADED_TYPES);
  const quick = typeBag(QUICK_TYPES);

  // Core: learn(w_i) is followed by the question for w_(i-1), so there is
  // always one round between meeting a new word and being tested on it.
  const core: Round[] = [];
  const questions = words.map((w) => graded(w, othersFor(w, all)) ?? ({ kind: "learn", vocab: w } as Round));
  words.forEach((w, i) => {
    if (w.srs_state === "NEW") core.push({ kind: "learn", vocab: w });
    if (i > 0) core.push(questions[i - 1]);
  });
  core.push(questions[questions.length - 1]);

  // Practice: never rates a word the first time (core already did), so it
  // can go anywhere after the opening rounds.
  const practice: Round[] = [];
  const room = () => length - 1 - core.length - practice.length;
  const withTranslation = words.filter((w) => w.translation && w.definition);
  if (room() > 0 && words.length >= 2) {
    const qs = shuffle(words).slice(0, 3).map((w) => quick(w, othersFor(w, all))).filter((q): q is Question => !!q);
    if (qs.length >= 2) practice.push({ kind: "battle", questions: qs });
  }
  if (room() > 0 && withTranslation.length >= 3) practice.push({ kind: "match", words: shuffle(withTranslation).slice(0, 4) });
  for (let guard = 0; room() > 0 && guard < 30; guard++) {
    const w = words[guard % words.length];
    const q = graded(w, othersFor(w, all));
    if (q) practice.push(q);
  }

  const rounds = [...core];
  for (const p of shuffle(practice)) {
    const min = Math.min(3, rounds.length);
    rounds.splice(min + Math.floor(Math.random() * (rounds.length - min + 1)), 0, p);
  }

  const boss = typeBag(BOSS_TYPES);
  const bossQs: Question[] = [];
  for (let i = 0; bossQs.length < 5 && i < 15; i++) {
    const w = words[i % words.length];
    const q = boss(w, othersFor(w, all));
    if (q) bossQs.push(q);
  }
  if (bossQs.length) rounds.push({ kind: "boss", questions: bossQs });
  return rounds;
}

/** A follow-up for a missed word, inserted a few rounds later so the
 * mistake becomes another attempt instead of a dead end. */
export function retryFor(v: Vocab, pool: PoolWord[]): Question | null {
  const others = othersFor(v, pool);
  for (const t of shuffle<QuestionType>(["type", "context", "translation", "meaning"])) {
    const q = makeQuestion(v, t, others);
    if (q) return q;
  }
  return null;
}

/** Vocab ids a round touches - used for the per-word memory list. */
export function roundWords(r: Round): Vocab[] {
  if (r.kind === "match") return r.words;
  if (r.kind === "battle" || r.kind === "boss") return r.questions.map((q) => q.vocab);
  return [r.vocab];
}

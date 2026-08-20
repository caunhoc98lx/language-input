import type { VocabItem } from "./types";

export type DailyKind = "reading" | "listening" | "writing";

export interface PracticeQuestion {
  type: "multiple_choice" | "true_false_notgiven" | "short_answer";
  question: string;
  options: string[];
  answer?: string;
  explanation?: string;
  /** Words this question hinges on; full entries live in DailyContent.vocabulary. */
  vocab_words?: string[];
}

export interface DailyContent {
  title?: string;
  topic?: string;
  passage?: string;
  transcript?: string;
  prompt?: string;
  guidance?: string;
  task_type?: string;
  min_words?: number;
  questions?: PracticeQuestion[];
  /** Key words from the passage/script overall, beyond the per-question ones. */
  vocabulary?: VocabItem[];
}

export interface DailyTask {
  id: number;
  kind: DailyKind;
  date: string;
  content: DailyContent;
}

export interface QuestionResult {
  index: number;
  given: string;
  answer: string;
  correct: boolean;
}

export interface Correction {
  original: string;
  improved: string;
  why: string;
}

export interface WritingFeedback {
  band_overall: number;
  task_response: number;
  coherence_cohesion: number;
  lexical_resource: number;
  grammatical_range: number;
  summary: string;
  strengths: string[];
  weaknesses: string[];
  corrections: Correction[];
  suggested_vocabulary: VocabItem[];
}

export interface DailyAttempt {
  id: number;
  answers: string[];
  score: number | null;
  total: number | null;
  band: number | null;
  feedback: { results?: QuestionResult[] } & Partial<WritingFeedback>;
  submitted_at?: string;
}

export interface DailyOverviewItem {
  generated: boolean;
  attempted: boolean;
  title?: string;
  topic?: string;
  score: number | null;
  total: number | null;
  band: number | null;
}

export const TRUE_FALSE_OPTIONS = ["TRUE", "FALSE", "NOT GIVEN"];

/**
 * Split a task's vocabulary into the words tied to questions the learner got wrong,
 * and everything else worth learning. Falls back to showing all words when a task
 * carries no per-question references.
 */
export function splitVocabByMistakes(
  content: DailyContent,
  results?: QuestionResult[],
): { missed: VocabItem[]; extra: VocabItem[] } {
  const all = content.vocabulary || [];
  if (!results || all.length === 0) return { missed: [], extra: all };

  const wanted = new Set(
    (content.questions || []).flatMap((q, i) =>
      results[i]?.correct ? [] : (q.vocab_words || []).map((w) => w.trim().toLowerCase()),
    ),
  );
  const missed = all.filter((v) => wanted.has(v.word.trim().toLowerCase()));
  const extra = all.filter((v) => !wanted.has(v.word.trim().toLowerCase()));
  return { missed, extra };
}

export function bandColor(band: number | null): string {
  if (band === null) return "var(--muted)";
  if (band >= 7) return "var(--success)";
  if (band >= 5.5) return "var(--warning)";
  return "var(--danger)";
}

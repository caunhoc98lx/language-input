export type PracticeMode = "EXAM" | "LEARNING";

export interface PracticeQuestion {
  id: number;
  section_id: number;
  group_id: number | null;
  question_number: number;
  question_type: string;
  question_text: string;
  instruction: string;
  options: string[];
  word_limit: string;
  skill: string;
  /** Only present after submitting. */
  answer?: string;
  explanation?: string;
}

export interface PracticeGroup {
  id: number;
  section_id: number;
  question_type: string;
  instruction: string;
  body: string;
  word_limit: string;
  options: string[];
  first_question: number | null;
  last_question: number | null;
}

export interface PracticeSection {
  id: number;
  skill: string;
  section_number: number;
  title: string;
  instructions: string;
  body: string;
  transcript: string;
  first_question: number | null;
  last_question: number | null;
  audio: { file_id: number; start: number | null; end: number | null } | null;
}

export interface QuestionResult {
  question_id: number;
  question_number: number;
  given: string;
  answer: string;
  correct: boolean;
  answered: boolean;
  question_type: string;
  explanation?: string;
}

export interface PracticeResult {
  score: number;
  total: number;
  band: number;
  band_is_estimate: boolean;
  unanswered: number;
  duration_sec: number | null;
  results: QuestionResult[];
  by_type: { type: string; attempts: number; correct: number; accuracy: number }[];
}

export interface PracticePayload {
  session: {
    id: number;
    mode: PracticeMode;
    skill: string;
    status: "IN_PROGRESS" | "SUBMITTED" | "ABANDONED";
    started_at: string;
    material_id: number | null;
    test_id: number | null;
    section_id: number | null;
  };
  sections: PracticeSection[];
  groups: PracticeGroup[];
  questions: PracticeQuestion[];
  answers: Record<string, string>;
  result?: PracticeResult;
}

/** Choice-style types render as a radio list; everything else takes typed input. */
export const CHOICE_TYPES = new Set([
  "MULTIPLE_CHOICE",
  "TRUE_FALSE_NOT_GIVEN",
  "YES_NO_NOT_GIVEN",
  "MATCHING_HEADINGS",
  "MATCHING_INFORMATION",
  "MATCHING_FEATURES",
  "MATCHING_SENTENCE_ENDINGS",
]);

export const TRUE_FALSE = ["TRUE", "FALSE", "NOT GIVEN"];
export const YES_NO = ["YES", "NO", "NOT GIVEN"];

export function typeLabel(questionType: string): string {
  return questionType
    .replaceAll("_", " ")
    .toLowerCase()
    .replace(/\b\w/g, (c) => c.toUpperCase());
}

/** Options to show for a question: its own, its group's, or the fixed sets. */
export function optionsFor(question: PracticeQuestion, group?: PracticeGroup): string[] {
  if (question.question_type === "TRUE_FALSE_NOT_GIVEN") return TRUE_FALSE;
  if (question.question_type === "YES_NO_NOT_GIVEN") return YES_NO;
  if (question.options.length) return question.options;
  return group?.options ?? [];
}

export function formatDuration(seconds: number): string {
  const m = Math.floor(seconds / 60);
  const s = seconds % 60;
  return `${m}:${String(s).padStart(2, "0")}`;
}

/** Default time allowance, in seconds, for a practice target. */
export function timeAllowance(skill: string, sectionCount: number, questionCount: number): number {
  if (skill === "READING") return sectionCount >= 3 ? 60 * 60 : Math.max(20, questionCount * 1.5) * 60;
  if (skill === "LISTENING") return sectionCount >= 4 ? 40 * 60 : Math.max(10, questionCount) * 60;
  return Math.max(10, questionCount * 2) * 60;
}

export interface User {
  id: number;
  email: string;
  name: string;
  native_language: string;
  ielts_target: number | null;
  ielts_current: number | null;
  cefr_level: string;
  target_date: string | null;
  onboarded: boolean;
  daily_goal_minutes: number;
  streak: number;
  last_active_date: string | null;
  created_at: string;
  xp: number;
  coins: number;
  level: number;
  xp_into_level: number;
  xp_for_next: number;
}

/** Totals from the game layer - POST /api/game/session, GET /api/game/achievements. */
export interface GameStats {
  xp: number;
  coins: number;
  streak: number;
  best_combo: number;
  boss_wins: number;
  sessions_completed: number;
  level: number;
  xp_into_level: number;
  xp_for_next: number;
  words_learned: number;
  words_mastered: number;
}

export interface Achievement {
  key: string;
  title: string;
  description: string;
  icon: string;
  unlocked: boolean;
}

/** Another of the learner's words, used only as a wrong option in game rounds. */
export interface PoolWord {
  id: number;
  word: string;
  translation: string;
  definition: string;
  part_of_speech: string;
  examples: string[];
}

export type Skill = "listening" | "reading" | "writing" | "speaking";

/** Coaching payload from GET /api/dashboard - see coach.py. */
export interface PlanTask {
  kind: string;
  title: string;
  detail: string;
  minutes: number;
  href: string;
  done: boolean;
}

export interface QuestionTypeAccuracy {
  type: string;
  label: string;
  attempts: number;
  correct: number;
  accuracy: number;
}

export interface Coaching {
  bands: {
    skills: Partial<Record<Skill, number>>;
    overall: number | null;
    estimated_from: "practice" | "self-reported";
    target: number | null;
    target_date: string | null;
  };
  plan: PlanTask[];
  weak_areas: QuestionTypeAccuracy[];
  question_type_accuracy: QuestionTypeAccuracy[];
  activity: {
    reviews_this_week: number;
    practice_minutes_this_week: number;
    questions_answered: number;
    accuracy: number | null;
    today_by_skill: { skill: Skill; minutes: number }[];
  };
}

export interface Vocab {
  id: number;
  word: string;
  translation: string;
  definition: string;
  part_of_speech: string;
  pronunciation: string;
  phonetic: string;
  examples: string[];
  synonyms: string[];
  antonyms: string[];
  collocations: string[];
  word_family: string[];
  ielts_level: string;
  topic: string;
  memory_tip: string;
  notes: string;
  /** 0-100, FSRS's estimated chance of recalling it right now. Display only. */
  memory_strength: number;
  srs_state: "NEW" | "LEARNING" | "REVIEW" | "RELEARNING" | "MASTERED";
  ease: number;
  interval_days: number;
  repetitions: number;
  lapses: number;
  next_review_at: string;
  last_reviewed_at: string | null;
  starred: number;
  created_at: string;
  updated_at: string;
}

/** A vocabulary entry as produced by AI, before it is saved to the database. */
export interface VocabItem {
  word: string;
  translation: string;
  part_of_speech: string;
  pronunciation: string;
  phonetic: string;
  definition: string;
  examples: string[];
  synonyms: string[];
  antonyms: string[];
  collocations: string[];
  ielts_level: string;
  topic: string;
  memory_tip: string;
}

export interface VocabSet {
  id: number;
  title: string;
  description: string;
  created_at: string;
  word_count?: number;
  mastered_count?: number;
}

export interface Review {
  id: number;
  vocabulary_id: number;
  rating: string;
  interval_before: number;
  interval_after: number;
  reviewed_at: string;
}

export type QuestionType = "multiple_choice" | "true_false" | "fill_blank" | "type_answer";

export interface LearnCard extends Vocab {
  question_type: QuestionType;
  options?: string[];
  tf_statement?: string;
  tf_answer?: boolean;
  blank_sentence?: string;
}

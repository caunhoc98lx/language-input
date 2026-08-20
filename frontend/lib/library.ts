import { ApiError } from "./api";

const API_URL = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

export type Skill = "LISTENING" | "READING" | "WRITING" | "SPEAKING";

export interface Material {
  id: number;
  title: string;
  source: string;
  description: string;
  doc_type: string;
  status: "IMPORTING" | "NEEDS_REVIEW" | "READY" | "FAILED";
  created_at: string;
  tests: number;
  sections: number;
  questions: number;
  needs_review: number;
  missing_answers: number;
  job_id: number | null;
  job_status: string | null;
}

export interface ImportStep {
  step: string;
  status: "running" | "done" | "warning" | "error";
  detail: string;
  at: string;
}

export interface ImportJob {
  id: number;
  material_id: number;
  status: string;
  current_step: string;
  steps: ImportStep[];
  warnings: string[];
  error: string;
  total_pages: number;
  processed_pages: number;
  progress: number;
  files: { id: number; kind: string; filename: string; size_bytes: number; page_count: number | null }[];
  started_at: string | null;
  completed_at: string | null;
}

export interface Section {
  id: number;
  test_id: number;
  skill: Skill;
  section_number: number;
  title: string;
  instructions: string;
  body: string;
  transcript: string;
  audio_file_id: number | null;
  audio_start_sec: number | null;
  audio_end_sec: number | null;
  audio_confidence: number | null;
  first_question: number | null;
  last_question: number | null;
  source_pages: string;
  confidence: number | null;
  status: "READY" | "NEEDS_REVIEW";
  question_count: number;
  needs_review: number;
}

export interface Question {
  id: number;
  question_number: number;
  question_type: string;
  question_text: string;
  options: string[];
  answer: string;
  explanation: string;
  word_limit: string;
  answer_source: "DOCUMENT" | "USER" | "AI";
  source_page: number | null;
  parser_confidence: number | null;
  status: "READY" | "NEEDS_REVIEW";
}

export const SKILL_ORDER: Skill[] = ["LISTENING", "READING", "WRITING", "SPEAKING"];

export function sectionLabel(section: Pick<Section, "skill" | "section_number">): string {
  const noun = { LISTENING: "Section", READING: "Passage", WRITING: "Task", SPEAKING: "Part" }[section.skill];
  return `${noun} ${section.section_number}`;
}

export function formatBytes(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${Math.round(bytes / 1024)} KB`;
  return `${(bytes / 1024 / 1024).toFixed(1)} MB`;
}

/**
 * Multipart upload with real progress and a working cancel.
 *
 * ponytail: XHR, not fetch - fetch still cannot report upload progress in
 * browsers, and this is the one place in the app that needs it.
 */
export function uploadImport(
  form: FormData,
  onProgress: (fraction: number) => void,
): { promise: Promise<{ job_id: number; material_id: number; duplicates: { filename: string; material: string }[] }>; cancel: () => void } {
  const xhr = new XMLHttpRequest();
  const promise = new Promise<{ job_id: number; material_id: number; duplicates: { filename: string; material: string }[] }>(
    (resolve, reject) => {
      xhr.open("POST", `${API_URL}/api/library/import`);
      xhr.withCredentials = true;
      xhr.upload.onprogress = (e) => {
        if (e.lengthComputable) onProgress(e.loaded / e.total);
      };
      xhr.onload = () => {
        let data: Record<string, unknown> = {};
        try {
          data = JSON.parse(xhr.responseText);
        } catch {
          /* server sent no JSON body */
        }
        if (xhr.status >= 200 && xhr.status < 300) {
          onProgress(1);
          resolve(data as never);
        } else {
          reject(new ApiError(String(data.detail || `Upload failed (${xhr.status})`), xhr.status));
        }
      };
      xhr.onerror = () => reject(new ApiError("Upload failed: the server could not be reached.", 0));
      xhr.onabort = () => reject(new ApiError("Upload cancelled.", 0));
      xhr.send(form);
    },
  );
  return { promise, cancel: () => xhr.abort() };
}

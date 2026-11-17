/** 与引擎协议对应的前端模型（字段未知时允许扩展）。 */

export type ProjectStatus =
  | "draft"
  | "running"
  | "waiting_review"
  | "waiting_translation"
  | "done"
  | "failed";

export interface MediaRef {
  path: string;
  fingerprint: string;
  duration: number;
  streams: Record<string, unknown>[];
}

export interface LanguagePair {
  source: string;
  target: string;
}

export interface RunRef {
  id: string;
  recipe_id: string;
  status: string;
  started_at?: string | null;
  finished_at?: string | null;
}

export interface ProjectOutput {
  path: string;
  kind: string;
  step?: string | null;
  created_at: string;
}

export interface Project {
  id: string;
  name: string;
  status: ProjectStatus;
  created_at: string;
  updated_at: string;
  media: MediaRef | null;
  language: LanguagePair;
  runs: RunRef[];
  outputs: ProjectOutput[];
  notes: string;
  workspace: string;
}

export interface ProjectSummary {
  id: string;
  name: string;
  status: ProjectStatus;
  created_at: string;
  updated_at: string;
  media_path: string;
  workspace: string;
  outputs: string[];
}

export interface RecipeSummary {
  id: string;
  name: string;
  version: number;
  description: string;
  builtin: boolean;
  step_count: number;
}

export interface ValidationIssue {
  severity: "error" | "warning";
  code: string;
  message: string;
  step_id?: string | null;
  port?: string | null;
  data?: Record<string, unknown>;
}

export interface ValidationResult {
  ok: boolean;
  errors: ValidationIssue[];
  warnings: ValidationIssue[];
  order: string[];
}

export const VIDEO_EXTENSIONS = [".mkv", ".mp4", ".mov", ".avi", ".ts"];
export const SUBTITLE_EXTENSIONS = [".srt", ".ass", ".vtt"];

export function extensionOf(path: string): string {
  const index = path.lastIndexOf(".");
  return index >= 0 ? path.slice(index).toLowerCase() : "";
}

export function isVideoPath(path: string): boolean {
  return VIDEO_EXTENSIONS.includes(extensionOf(path));
}

export function isSubtitlePath(path: string): boolean {
  return SUBTITLE_EXTENSIONS.includes(extensionOf(path));
}

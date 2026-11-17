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

/** JSON Schema 子集；由引擎的 Pydantic ``model_json_schema()`` 生成。 */
export type JsonSchema = Record<string, unknown>;

export interface StepSpecPort {
  kind: string;
  required: boolean;
  multiple: boolean;
}

/** ``steps.list`` 返回的步骤定义。 */
export interface StepSpec {
  id: string;
  title: string;
  description: string;
  inputs: Record<string, StepSpecPort>;
  outputs: Record<string, StepSpecPort>;
  options_schema: JsonSchema;
  requires_agent: boolean;
  deterministic: boolean;
}

export type RecipeInputKind = "file" | "folder" | "files";

export interface RecipeInput {
  name: string;
  kind: RecipeInputKind;
  accept: string[];
  required: boolean;
}

export interface RecipeStep {
  id: string;
  uses: string;
  needs: string[];
  when: string | null;
  with: Record<string, unknown>;
  ui: Record<string, unknown>;
}

export interface RecipeOutput {
  from: string;
  key: string;
}

/** 完整配方（``recipes.get`` / ``pipeline.validate`` 使用）。 */
export interface RecipeDefinition {
  id: string;
  name: string;
  version: number;
  description: string;
  builtin: boolean;
  inputs: RecipeInput[];
  steps: RecipeStep[];
  outputs: RecipeOutput[];
  ui: Record<string, unknown>;
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

// ---- M5 人工审核（HITL）---------------------------------------------

export type ReviewRecordStatus = "pending" | "submitted";
export type ReviewItemStatus = "pending" | "accepted" | "rejected";
export type ReviewItemAction = "keep" | "remove" | "rewrite";
export type ReviewItemSource = "rules" | "agent" | "human";
export type ReviewDecisionAction = "accept" | "reject";

/** ``review.list`` 返回的扁平审核项。 */
export interface ReviewItem {
  id: string;
  review_id: string;
  review_status: ReviewRecordStatus;
  status: ReviewItemStatus;
  segment_index: number;
  start_ms: number;
  end_ms: number;
  before: string;
  after: string;
  action: ReviewItemAction;
  confidence: number;
  reason: string;
  reasons: string[];
  source: ReviewItemSource;
  file: string;
  artifact_hash: string;
}

/** ``review.submit`` 的单项决策；改写时附带 ``after``。 */
export interface ReviewDecision {
  id: string;
  action: ReviewDecisionAction;
  after?: string | null;
}

/** ``review.undo`` 返回的恢复结果。 */
export interface ReviewUndoResult {
  review_id: string;
  audit_path: string;
  restored: Array<{ path: string; hash: string }>;
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

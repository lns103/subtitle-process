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

export interface RecipeInputBinding {
  step: string;
  port: string;
}

export interface RecipeInput {
  name: string;
  label?: string;
  kind: RecipeInputKind;
  accept: string[];
  required: boolean;
  multiple?: boolean;
  bind?: RecipeInputBinding[];
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

// ---- 首页任务目录（tasks.list）----------------------------------------

export type TaskKind = "workflow" | "function";

export interface TaskInputBinding {
  step: string;
  port: string;
}

export interface TaskInputSpec {
  name: string;
  label?: string;
  kind: RecipeInputKind;
  accept: string[];
  required: boolean;
  multiple?: boolean;
  bind?: TaskInputBinding[];
}

export interface TaskSpec {
  id: string;
  recipe_id: string;
  kind: TaskKind;
  group: string;
  order: number;
  title: string;
  description: string;
  inputs: TaskInputSpec[];
  requires_project: boolean;
}

/** ``files.scan`` 返回的单个文件。 */
export interface ScannedFile {
  path: string;
  name: string;
  extension: string;
  size: number;
}

export interface FileScanResult {
  files: ScannedFile[];
  /** 输入中属于文件夹的路径；用于批量项目按拖入文件夹命名。 */
  directories?: string[];
}

// ---- media.inspect -----------------------------------------------------

export interface MediaSubtitleTrack {
  index: number;
  language: string;
  title: string;
  codec_name?: string;
  default: boolean;
  forced: boolean;
  hearing_impaired: boolean;
}

export interface MediaInfo {
  source_path?: string;
  duration: number;
  audio_langs: Record<string, number>;
  default_audio_lang?: string | null;
  subtitles: MediaSubtitleTrack[];
  warnings: string[];
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

// ---- M6 Agent 设置 -----------------------------------------------------

/** ``settings.get`` 中的 Agent 配置；``api_key`` 永不返回，仅暴露是否已配置。 */
export interface AgentSettings {
  base_url: string;
  model: string;
  temperature: number;
  timeout_s: number;
  max_retries: number;
  batch_size: number;
  context_size: number;
  min_confidence: number;
  auto_apply: boolean;
  delete_ratio_limit: number;
  structured_output: "json_schema" | "json_object";
  api_key_configured?: boolean;
}

export interface AppSettings {
  agent: AgentSettings;
}

/** ``agent.test`` 的连通性结果。 */
export interface AgentTestResult {
  ok: boolean;
  latency_ms: number;
  model?: string;
  base_url?: string;
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

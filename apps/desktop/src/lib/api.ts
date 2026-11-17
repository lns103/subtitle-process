import { engineCall } from "./rpc";
import type {
  Project,
  ProjectSummary,
  RecipeDefinition,
  RecipeSummary,
  ReviewDecision,
  ReviewItem,
  ReviewUndoResult,
  StepSpec,
  ValidationResult,
} from "./models";

/** M3 项目 / 配方 / 流水线 API；全部走泛型 `engine_call`。 */

export function listProjects(): Promise<ProjectSummary[]> {
  return engineCall<ProjectSummary[]>("project.list");
}

export function getProject(id: string): Promise<Project> {
  return engineCall<Project>("project.get", { id });
}

export function createProject(params: {
  name?: string;
  media_path?: string;
  language?: { source?: string; target?: string };
}): Promise<Project> {
  return engineCall<Project>("project.create", params);
}

export function deleteProject(id: string): Promise<string> {
  return engineCall<string>("project.delete", { id });
}

export function listRecipes(): Promise<RecipeSummary[]> {
  return engineCall<RecipeSummary[]>("recipes.list");
}

export function validateRecipe(
  recipeId: string,
  projectId?: string,
): Promise<ValidationResult> {
  return engineCall<ValidationResult>("pipeline.validate", {
    recipe_id: recipeId,
    ...(projectId ? { project_id: projectId } : {}),
  });
}

export function runRecipe(params: {
  recipeId: string;
  inputs: string[];
  projectId?: string;
  options?: Record<string, unknown>;
}): Promise<{ job_id: string; run_id: string }> {
  return engineCall<{ job_id: string; run_id: string }>("pipeline.run", {
    recipe_id: params.recipeId,
    inputs: params.inputs,
    ...(params.projectId ? { project_id: params.projectId } : {}),
    ...(params.options ? { options: params.options } : {}),
  });
}

export function revealPath(path: string): Promise<string> {
  return engineCall<string>("artifact.reveal", { path });
}

// ---- M4 自由连线编辑器 -------------------------------------------------

export function listSteps(): Promise<StepSpec[]> {
  return engineCall<StepSpec[]>("steps.list");
}

export function getRecipe(id: string): Promise<RecipeDefinition> {
  return engineCall<RecipeDefinition>("recipes.get", { id });
}

export function saveRecipe(recipe: RecipeDefinition): Promise<RecipeDefinition> {
  return engineCall<RecipeDefinition>("recipes.save", { recipe });
}

export function deleteRecipe(id: string): Promise<string> {
  return engineCall<string>("recipes.delete", { id });
}

/** 直接校验画布上的配方对象（可能尚未保存）。 */
export function validateRecipePayload(
  recipe: RecipeDefinition,
  projectId?: string,
): Promise<ValidationResult> {
  return engineCall<ValidationResult>("pipeline.validate", {
    recipe,
    ...(projectId ? { project_id: projectId } : {}),
  });
}

/** 直接运行画布上的配方对象（可能尚未保存）。 */
export function runRecipePayload(params: {
  recipe: RecipeDefinition;
  inputs: string[];
  projectId?: string;
  options?: Record<string, unknown>;
}): Promise<{ job_id: string; run_id: string }> {
  return engineCall<{ job_id: string; run_id: string }>("pipeline.run", {
    recipe: params.recipe,
    inputs: params.inputs,
    ...(params.projectId ? { project_id: params.projectId } : {}),
    ...(params.options ? { options: params.options } : {}),
  });
}

export function cancelJob(jobId: string): Promise<string> {
  return engineCall<string>("job.cancel", { job_id: jobId });
}

// ---- M5 人工审核 -------------------------------------------------------

export function listReviews(runId: string): Promise<ReviewItem[]> {
  return engineCall<ReviewItem[]>("review.list", { run_id: runId });
}

export function submitReview(runId: string, decisions: ReviewDecision[]): Promise<string> {
  return engineCall<string>("review.submit", { run_id: runId, decisions });
}

export function undoReview(runId: string): Promise<ReviewUndoResult> {
  return engineCall<ReviewUndoResult>("review.undo", { run_id: runId });
}

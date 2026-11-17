import { engineCall } from "./rpc";
import type {
  Project,
  ProjectSummary,
  RecipeSummary,
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

import { createProject, getJobStatus, getProject, runRecipePayload } from "./api";
import { onEngineEvent } from "./events";
import type { RecipeDefinition } from "./models";
import { pickOriginalSubtitle } from "./tasks";
import { useBatchStore } from "../stores/batchStore";
import { useProjectStore } from "../stores/projectStore";
import { useRunStore } from "../stores/runStore";
import { useTaskStore } from "../stores/taskStore";

interface RunOutcome {
  status: "done" | "failed" | "cancelled";
  error: string | null;
}

/** 等待单个 run 结束；审核期间保持等待，提交后引擎会继续到 run.finished。 */
function waitForRun(runId: string, index: number): Promise<RunOutcome> {
  return new Promise((resolve) => {
    let unlisten: (() => void) | undefined;
    let disposed = false;
    let timer: number | undefined;

    const settle = (outcome: RunOutcome) => {
      if (disposed) return;
      disposed = true;
      unlisten?.();
      if (timer !== undefined) window.clearInterval(timer);
      resolve(outcome);
    };

    const getOutcome = (status: string): RunOutcome => ({
      status:
        status === "done" ? "done" : status === "cancelled" ? "cancelled" : "failed",
      error: null,
    });

    void onEngineEvent((event) => {
      if (disposed || event.run_id !== runId) return;
      if (event.type === "review.requested") {
        useBatchStore.getState().update(index, { status: "waiting_review" });
        return;
      }
      if (event.type === "review.resolved") {
        useBatchStore.getState().update(index, { status: "running" });
        return;
      }
      if (event.type !== "run.finished") return;
      settle({
        ...getOutcome(String(event.status ?? "failed")),
        error: event.error?.message ?? null,
      });
    }).then((fn) => {
      if (disposed) fn();
      else unlisten = fn;
    });

    // 事件丢失兜底：轮询 job.status，避免批量队列永远卡住。
    timer = window.setInterval(() => {
      if (disposed) return;
      void getJobStatus(runId)
        .then((run) => {
          if (disposed) return;
          if (run.status === "waiting_review") {
            useBatchStore.getState().update(index, { status: "waiting_review" });
            return;
          }
          if (["done", "failed", "cancelled"].includes(run.status)) {
            settle(getOutcome(run.status));
          }
        })
        .catch(() => undefined);
    }, 2000);
  });
}

async function resolveProject(mediaPath: string): Promise<string> {
  const existing = useProjectStore
    .getState()
    .projects.find((project) => project.media_path === mediaPath);
  if (existing) return existing.id;
  const project = await createProject({ media_path: mediaPath });
  useProjectStore.getState().applyUpdate(project);
  return project.id;
}

export interface VideoBatchOptions {
  taskId: string;
  recipe: RecipeDefinition;
  paths: string[];
  /** 提取流程结束后把干净字幕填到双语任务的原版槽。 */
  autoFillOriginal?: boolean;
}

/**
 * 顺序处理多个视频：每个视频一个项目 + 一个 run。
 * 失败只标记当前项并继续；遇到人工审核时暂停，审核完成后自动继续。
 */
export async function runVideoBatch(options: VideoBatchOptions): Promise<void> {
  const { taskId, recipe, paths, autoFillOriginal = false } = options;
  useBatchStore.getState().start(taskId, paths);

  let lastProjectId: string | null = null;
  const allOutputs: string[] = [];

  try {
    for (let index = 0; index < paths.length; index += 1) {
      if (!useBatchStore.getState().active) break;
      const path = paths[index];
      useBatchStore.getState().update(index, { status: "running" });

      try {
        const projectId = await resolveProject(path);
        useRunStore.getState().reset();
        const result = await runRecipePayload({
          recipe,
          inputs: [path],
          inputsByName: { video: [path] },
          projectId,
        });
        useBatchStore
          .getState()
          .update(index, { projectId, runId: result.run_id });
        useRunStore.getState().begin(result.run_id, projectId);

        const outcome = await waitForRun(result.run_id, index);
        if (outcome.status !== "done") {
          useBatchStore.getState().update(index, {
            status: outcome.status === "cancelled" ? "failed" : outcome.status,
            error:
              outcome.error ??
              (outcome.status === "cancelled" ? "已取消" : "运行失败"),
          });
          continue;
        }

        let outputs: string[] = [];
        try {
          const project = await getProject(projectId);
          useProjectStore.getState().applyUpdate(project);
          outputs = project.outputs.map((output) => output.path);
        } catch (error) {
          useBatchStore.getState().update(index, {
            status: "failed",
            error: error instanceof Error ? error.message : String(error),
          });
          continue;
        }

        allOutputs.push(...outputs);
        lastProjectId = projectId;
        useBatchStore.getState().update(index, {
          status: "done",
          outputs,
          error: null,
        });
      } catch (error) {
        useBatchStore.getState().update(index, {
          status: "failed",
          error: error instanceof Error ? error.message : String(error),
        });
      }
    }
  } finally {
    useBatchStore.getState().finish();
    void useProjectStore.getState().refresh();
    if (lastProjectId) {
      void useProjectStore.getState().select(lastProjectId);
      if (autoFillOriginal) useProjectStore.getState().preferProject(lastProjectId);
    }
    if (autoFillOriginal) {
      const original = pickOriginalSubtitle(allOutputs);
      if (original) useTaskStore.getState().autoFillOriginal([original]);
    }
  }
}

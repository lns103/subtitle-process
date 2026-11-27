import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  AlertCircle,
  Check,
  Loader2,
  Play,
  RefreshCw,
  Settings,
  Workflow,
} from "lucide-react";
import {
  createProject,
  getProject,
  getRecipe,
  listSteps,
  runRecipePayload,
  scanFiles,
} from "../../lib/api";
import { onEngineEvent } from "../../lib/events";
import { directoriesForPaths, fileName } from "../../lib/inputRouting";
import { subtitleBaseName } from "../../lib/flow2";
import {
  VIDEO_EXTENSIONS,
  type RecipeDefinition,
  type StepSpec,
  type TaskSpec,
} from "../../lib/models";
import { navigate } from "../../lib/router";
import { restartEngine, type EngineStatus } from "../../lib/rpc";
import { pickOriginalSubtitles, taskInputLabel } from "../../lib/tasks";
import { getAppVersion } from "../../lib/version";
import { runVideoBatch } from "../../lib/videoBatch";
import { useBatchStore } from "../../stores/batchStore";
import { useProjectStore } from "../../stores/projectStore";
import { useRunStore } from "../../stores/runStore";
import { useTaskStore, type TrackSelection } from "../../stores/taskStore";
import { HandoffCard } from "../projects/HandoffCard";
import { ProjectList } from "../projects/ProjectList";
import { RunFeedback } from "../run-view/RunFeedback";
import { TaskInputs } from "./TaskInputs";
import { TaskOptions } from "./TaskOptions";
import { TaskPicker } from "./TaskPicker";

interface TaskPageProps {
  engineStatus: EngineStatus;
  initialTaskId?: string | null;
}

function engineBadge(status: EngineStatus): { text: string; tone: string } {
  switch (status.state) {
    case "ready":
      return {
        text: `引擎就绪 · v${status.version}`,
        tone: "bg-emerald-50 text-emerald-700 border-emerald-200",
      };
    case "starting":
      return { text: "引擎启动中…", tone: "bg-amber-50 text-amber-700 border-amber-200" };
    case "failed":
      return {
        text: `引擎不可用：${status.message}`,
        tone: "bg-red-50 text-red-700 border-red-200",
      };
    default:
      return { text: "引擎已停止", tone: "bg-slate-50 text-slate-600 border-slate-200" };
  }
}

function isBilingualTask(task: TaskSpec | null): boolean {
  return Boolean(
    task &&
      (task.id === "batch_translated_to_bilingual" ||
        task.recipe_id === "batch_translated_to_bilingual" ||
        task.inputs.some((input) => input.name === "original")),
  );
}

function isExtractionRecipe(task: TaskSpec | null): boolean {
  if (!task) return false;
  if (
    task.id === "batch_video_to_clean_srt" ||
    task.id === "fn_extract_subtitles" ||
    task.recipe_id === "batch_video_to_clean_srt"
  ) {
    return true;
  }
  // 自定义/内置的视频流水线也走提取逻辑：视频槽支持批量与自动填充原文。
  return task.inputs.some(
    (input) =>
      input.name === "video" &&
      input.accept.some((extension) => VIDEO_EXTENSIONS.includes(extension)),
  );
}

/** 内容寻址中间产物位于 `<数据目录>/artifacts/<sha256>/...`，不展示给用户。 */
function isStoredArtifactPath(path: string): boolean {
  const parts = path.split(/[\\/]/);
  return parts.some(
    (part, index) =>
      part.toLowerCase() === "artifacts" &&
      /^[0-9a-f]{64}$/i.test(parts[index + 1] ?? ""),
  );
}

function artifactPathFrom(event: Record<string, unknown>): string | null {
  const candidates = [event.artifact, event.path, event.output];
  for (const candidate of candidates) {
    if (typeof candidate === "string" && candidate.trim()) {
      return isStoredArtifactPath(candidate) ? null : candidate;
    }
    if (typeof candidate === "object" && candidate !== null && "path" in candidate) {
      const path = (candidate as { path?: unknown }).path;
      if (typeof path === "string" && path.trim()) {
        return isStoredArtifactPath(path) ? null : path;
      }
    }
  }
  return null;
}

/** 首页任务页：选择任务 → 填写输入槽 / 参数 → 运行 → 查看产物。 */
export function TaskPage({ engineStatus, initialTaskId = null }: TaskPageProps) {
  const tasks = useTaskStore((state) => state.tasks);
  const tasksLoading = useTaskStore((state) => state.loading);
  const tasksError = useTaskStore((state) => state.error);
  const selectedTaskId = useTaskStore((state) => state.selectedTaskId);
  const allSlots = useTaskStore((state) => state.slots);
  const allOptions = useTaskStore((state) => state.options);
  const allAutofilled = useTaskStore((state) => state.autofilled);
  const allTracks = useTaskStore((state) => state.tracks);
  const allRouting = useTaskStore((state) => state.lastRouting);

  const {
    projects,
    active,
    loading: projectsLoading,
    deletingId: deletingProjectId,
    lastError: projectError,
    select,
    remove: removeProject,
    refresh,
  } = useProjectStore();
  const preferredProjectId = useProjectStore((state) => state.preferredProjectId);
  const {
    runId,
    projectId: runProjectId,
    status,
    progress,
    logs,
    lastError,
    begin,
    reset,
  } = useRunStore();

  const [steps, setSteps] = useState<StepSpec[]>([]);
  const [recipe, setRecipe] = useState<RecipeDefinition | null>(null);
  const [recipeLoading, setRecipeLoading] = useState(false);
  const [recipeError, setRecipeError] = useState<string | null>(null);
  const [appVersion, setAppVersion] = useState<string | null>(null);
  const [restartBusy, setRestartBusy] = useState(false);
  const [restartError, setRestartError] = useState<string | null>(null);
  const [startedRunId, setStartedRunId] = useState<string | null>(null);
  const [outputs, setOutputs] = useState<string[]>([]);
  const [artifactPaths, setArtifactPaths] = useState<string[]>([]);
  const [outputError, setOutputError] = useState<string | null>(null);
  const [routeNotice, setRouteNotice] = useState<string | null>(null);
  const [targetProjectId, setTargetProjectId] = useState<string | null>(null);

  const startedExtractionRef = useRef(false);
  const handledRunRef = useRef<string | null>(null);
  const artifactPathsRef = useRef<string[]>([]);

  const task = useMemo(
    () => tasks.find((item) => item.id === selectedTaskId) ?? null,
    [tasks, selectedTaskId],
  );
  const slots = task ? (allSlots[task.id] ?? {}) : {};
  const options = task ? (allOptions[task.id] ?? {}) : {};
  const autofilled = task ? (allAutofilled[task.id] ?? {}) : {};
  const trackSelection: TrackSelection | undefined = task ? allTracks[task.id] : undefined;
  const routing = task ? (allRouting[task.id] ?? null) : null;

  const bilingual = isBilingualTask(task);
  const extraction = isExtractionRecipe(task);
  // 批处理任务都需要项目工作区，产物才能落到 <项目>/output/<子目录>。
  const needsWorkspace = Boolean(
    task && (bilingual || task.id.startsWith("batch_") || task.recipe_id.startsWith("batch_")),
  );
  const engineReady = engineStatus.state === "ready";
  const batchTaskId = useBatchStore((state) => state.taskId);
  const allBatchItems = useBatchStore((state) => state.items);
  const batchActive = useBatchStore((state) => state.active);
  const running = status === "running" || batchActive;

  const videoInput = task?.inputs.find((input) => input.name === "video") ?? null;
  const videoPaths = videoInput ? (slots[videoInput.name] ?? []) : [];
  const videoPath = videoPaths[0] ?? null;
  const batchMode = extraction && videoPaths.length > 1;
  const batchItems =
    task && batchTaskId === task.id ? allBatchItems : [];

  useEffect(() => {
    void useTaskStore.getState().load();
    void refresh();
    void getAppVersion().then(setAppVersion);
  }, [refresh]);

  // 引擎启动完成/重启后重新拉取任务目录，避免首次打开时 tasks.list 失败后一直空着。
  useEffect(() => {
    if (engineStatus.state !== "ready") return;
    void useTaskStore.getState().load();
  }, [engineStatus.state]);

  useEffect(() => {
    let disposed = false;
    void listSteps()
      .then((list) => {
        if (!disposed) setSteps(list);
      })
      .catch((error) => {
        if (!disposed) setRecipeError(error instanceof Error ? error.message : String(error));
      });
    return () => {
      disposed = true;
    };
  }, []);

  // 深链接 / 任务切换：同步 store 中的选中项。
  useEffect(() => {
    if (!initialTaskId) return;
    if (!tasks.some((item) => item.id === initialTaskId)) return;
    useTaskStore.getState().selectTask(initialTaskId);
  }, [initialTaskId, tasks]);

  // 读取当前任务的完整配方。
  useEffect(() => {
    if (!task) {
      setRecipe(null);
      return;
    }
    setRouteNotice(null);
    let disposed = false;
    setRecipeLoading(true);
    setRecipeError(null);
    setRecipe(null);
    void getRecipe(task.recipe_id)
      .then((value) => {
        if (!disposed) setRecipe(value);
      })
      .catch((error) => {
        if (!disposed) setRecipeError(error instanceof Error ? error.message : String(error));
      })
      .finally(() => {
        if (!disposed) setRecipeLoading(false);
      });
    return () => {
      disposed = true;
    };
  }, [task]);

  // HandoffCard 写入 preferredProjectId 后，切到双语任务时自动填入原版字幕。
  useEffect(() => {
    if (!task || !bilingual || !preferredProjectId) return;
    let disposed = false;
    const projectId = preferredProjectId;
    void getProject(projectId)
      .then((project) => {
        if (disposed) return;
        useProjectStore.getState().applyUpdate(project);
        const originals = pickOriginalSubtitles(project.outputs.map((output) => output.path));
        if (originals.length > 0) useTaskStore.getState().autoFillOriginal(originals);
        setTargetProjectId(project.id);
        useProjectStore.getState().preferProject(null);
      })
      .catch((error) => {
        if (disposed) return;
        setOutputError(error instanceof Error ? error.message : String(error));
      });
    return () => {
      disposed = true;
    };
  }, [task, bilingual, preferredProjectId]);

  // 采集 step.artifact 事件中的产物路径（run_id 匹配当前运行）。
  useEffect(() => {
    let disposed = false;
    let unlisten: (() => void) | undefined;
    void onEngineEvent((event) => {
      if (event.type !== "step.artifact") return;
      if (startedRunId && event.run_id && event.run_id !== startedRunId) return;
      const path = artifactPathFrom(event);
      if (!path) return;
      if (!artifactPathsRef.current.includes(path)) {
        artifactPathsRef.current = [...artifactPathsRef.current, path];
      }
      setArtifactPaths((current) => (current.includes(path) ? current : [...current, path]));
    }).then((fn) => {
      if (disposed) fn();
      else unlisten = fn;
    });
    return () => {
      disposed = true;
      unlisten?.();
    };
  }, [startedRunId]);

  // 运行结束后读取项目产物；视频流程同时把干净 SRT 自动填入双语「原版」槽。
  useEffect(() => {
    if (status !== "done" || !startedRunId || runId !== startedRunId) return;
    if (handledRunRef.current === startedRunId) return;
    handledRunRef.current = startedRunId;

    const projectId = useRunStore.getState().projectId;
    const extractionRun = startedExtractionRef.current;

    void (async () => {
      let paths: string[] = [];
      if (projectId) {
        try {
          const project = await getProject(projectId);
          useProjectStore.getState().applyUpdate(project);
          paths = project.outputs.map((output) => output.path);
        } catch (error) {
          setOutputError(error instanceof Error ? error.message : String(error));
        }
      } else {
        paths = useProjectStore.getState().active?.outputs.map((output) => output.path) ?? [];
      }
      setOutputs(paths);
      if (extractionRun) {
        const originals = pickOriginalSubtitles([...paths, ...artifactPathsRef.current]);
        if (originals.length > 0) useTaskStore.getState().autoFillOriginal(originals);
        if (projectId) useProjectStore.getState().preferProject(projectId);
      }
      void useProjectStore.getState().refresh();
    })();
  }, [status, runId, startedRunId]);

  const handleSelectTask = useCallback((next: TaskSpec) => {
    useTaskStore.getState().selectTask(next.id);
    navigate({ name: "task", taskId: next.id });
  }, []);

  const handleDeleteProject = useCallback(
    async (id: string) => {
      await removeProject(id);
      if (targetProjectId === id) setTargetProjectId(null);
    },
    [removeProject, targetProjectId],
  );

  const handleSetSlot = useCallback((taskId: string, inputName: string, paths: string[]) => {
    useTaskStore.getState().setSlot(taskId, inputName, paths);
  }, []);

  const handleClearSlot = useCallback((taskId: string, inputName: string) => {
    useTaskStore.getState().clearSlot(taskId, inputName);
  }, []);

  const handleOptionsChange = useCallback(
    (taskId: string, stepId: string, values: Record<string, unknown>) => {
      useTaskStore.getState().setStepOptions(taskId, stepId, values);
    },
    [],
  );

  const handleTrackChange = useCallback((taskId: string, selection: TrackSelection) => {
    useTaskStore.getState().setTrackSelection(taskId, selection);
  }, []);

  const handleRoute = useCallback(
    async (taskId: string, paths: string[], overwrite: boolean, recursive: boolean) => {
      const task = useTaskStore.getState().tasks.find((item) => item.id === taskId);
      if (!task) return;
      setRouteNotice(null);
      const accept = Array.from(
        new Set(task.inputs.flatMap((input) => input.accept)),
      );
      let expanded = paths;
      try {
        const scanned = await scanFiles({ paths, accept, recursive });
        if (scanned.files.length === 0) {
          setRouteNotice("所选文件或文件夹中没有匹配当前任务的文件。");
          return;
        }
        expanded = scanned.files.map((file) => file.path);
        useTaskStore
          .getState()
          .setRoutingDirectories(taskId, scanned.directories ?? []);
      } catch (error) {
        setRouteNotice(
          `读取文件夹失败，已按原始路径分配：${
            error instanceof Error ? error.message : String(error)
          }`,
        );
      }
      useTaskStore.getState().applyRouting(taskId, expanded, overwrite);
    },
    [],
  );

  const handleMoveSlot = useCallback(
    (taskId: string, fromInput: string, toInput: string, path: string) => {
      useTaskStore.getState().moveSlotPath(taskId, fromInput, toInput, path);
    },
    [],
  );

  const handleUndoRouting = useCallback((taskId: string) => {
    useTaskStore.getState().undoRouting(taskId);
  }, []);

  const handleRestart = useCallback(async () => {
    if (restartBusy || engineStatus.state === "starting") return;
    setRestartBusy(true);
    setRestartError(null);
    try {
      await restartEngine();
    } catch (error) {
      setRestartError(error instanceof Error ? error.message : String(error));
    } finally {
      setRestartBusy(false);
    }
  }, [engineStatus.state, restartBusy]);

  const missingInputs = useMemo(
    () =>
      task
        ? task.inputs.filter(
            (input) => input.required && (slots[input.name]?.length ?? 0) === 0,
          )
        : [],
    [task, slots],
  );

  const tracksInvalid =
    extraction && trackSelection?.mode === "manual" && trackSelection.indices.length === 0;

  const canRun =
    Boolean(task && recipe) &&
    engineReady &&
    !running &&
    status !== "waiting_review" &&
    missingInputs.length === 0 &&
    !tracksInvalid;

  const runTask = useCallback(async () => {
    if (!task || !recipe) return;
    reset();
    setOutputs([]);
    setArtifactPaths([]);
    artifactPathsRef.current = [];
    setOutputError(null);
    handledRunRef.current = null;
    setStartedRunId(null);
    startedExtractionRef.current = false;
    if (!batchMode) useBatchStore.getState().reset();

    if (missingInputs.length > 0) {
      useRunStore.setState({
        status: "failed",
        lastError: `请先填写必填输入：${missingInputs.map(taskInputLabel).join("、")}`,
      });
      return;
    }
    if (tracksInvalid) {
      useRunStore.setState({
        status: "failed",
        lastError: "请至少选择一条字幕轨道，或切换为自动选择。",
      });
      return;
    }

    try {
      const nextRecipe: RecipeDefinition = {
        ...recipe,
        steps: recipe.steps.map((step) => {
          const withValues: Record<string, unknown> = {
            ...step.with,
            ...(options[step.id] ?? {}),
          };
          if (extraction && step.uses === "media.extract_subtitles") {
            // 自动模式不传显式 tracks，由引擎按 selection 推荐。
            delete withValues.tracks;
            if (trackSelection?.mode === "manual" && trackSelection.indices.length > 0) {
              withValues.tracks = trackSelection.indices;
            }
          }
          return { ...step, with: withValues };
        }),
      };

      // 视频槽也可能收到文件夹（例如“选择文件夹”按钮）；运行时统一展开成文件。
      let runVideoPaths = videoPaths;
      let sourceDirectories: string[] = [];
      if (extraction && videoPaths.length > 0) {
        try {
          const scanned = await scanFiles({
            paths: videoPaths,
            accept: videoInput?.accept ?? [],
          });
          if (scanned.files.length > 0) {
            runVideoPaths = scanned.files.map((file) => file.path);
            sourceDirectories = directoriesForPaths(
              [
                ...(useTaskStore.getState().routingDirectories[task.id] ?? []),
                ...(scanned.directories ?? []),
              ],
              runVideoPaths,
            );
          } else {
            useRunStore.setState({
              status: "failed",
              lastError: "所选文件夹中没有匹配的视频文件。",
            });
            return;
          }
        } catch (error) {
          useRunStore.setState({
            status: "failed",
            lastError: `读取视频输入失败：${
              error instanceof Error ? error.message : String(error)
            }`,
          });
          return;
        }
      }

      if (extraction && runVideoPaths.length > 1) {
        await runVideoBatch({
          taskId: task.id,
          recipe: nextRecipe,
          paths: runVideoPaths,
          sourceDirectories,
          autoFillOriginal: true,
        });
        return;
      }

      const singleVideoPath = extraction
        ? (runVideoPaths[0] ?? videoPath)
        : videoPath;
      const runSlots: Record<string, string[]> =
        extraction ? { ...slots, video: runVideoPaths } : slots;

      const inputsByName: Record<string, string[]> = {};
      const legacy: string[] = [];
      for (const input of task.inputs) {
        const values = runSlots[input.name] ?? [];
        if (values.length > 0) inputsByName[input.name] = values;
        for (const path of values) if (!legacy.includes(path)) legacy.push(path);
      }

      let projectId: string | undefined;
      if (extraction && singleVideoPath) {
        const existing = useProjectStore
          .getState()
          .projects.find((project) => project.media_path === singleVideoPath);
        if (existing) {
          projectId = existing.id;
          setTargetProjectId(existing.id);
          await useProjectStore.getState().select(existing.id);
        } else {
          const project = await createProject({ media_path: singleVideoPath });
          useProjectStore.getState().applyUpdate(project);
          useProjectStore.getState().setActive(project);
          projectId = project.id;
          setTargetProjectId(project.id);
        }
      } else if (needsWorkspace) {
        projectId =
          targetProjectId ??
          useProjectStore.getState().preferredProjectId ??
          active?.id ??
          undefined;
        if (!projectId) {
          // 没有关联项目时建一个轻量项目，保证产物落在项目 output/ 下，
          // 同时让产物出现在项目列表里。
          const sample =
            task.inputs
              .flatMap((input) => slots[input.name] ?? [])
              .find((path) => path.trim() !== "") ?? "";
          const fallback = bilingual ? "双语合并" : "批处理";
          const name = sample ? subtitleBaseName(sample) || fallback : fallback;
          const existing = useProjectStore
            .getState()
            .projects.find((project) => project.name === name);
          if (existing) {
            projectId = existing.id;
            await useProjectStore.getState().select(existing.id);
          } else {
            const project = await createProject({ name });
            useProjectStore.getState().applyUpdate(project);
            useProjectStore.getState().setActive(project);
            projectId = project.id;
          }
          setTargetProjectId(projectId);
        }
      } else if (task.requires_project) {
        projectId =
          targetProjectId ??
          useProjectStore.getState().preferredProjectId ??
          active?.id ??
          undefined;
      }

      const result = await runRecipePayload({
        recipe: nextRecipe,
        inputs: legacy,
        inputsByName,
        ...(projectId ? { projectId } : {}),
      });
      startedExtractionRef.current = extraction;
      setStartedRunId(result.run_id);
      begin(result.run_id, projectId ?? null);
    } catch (error) {
      useRunStore.setState({
        status: "failed",
        lastError: error instanceof Error ? error.message : String(error),
      });
    }
  }, [
    active,
    batchMode,
    bilingual,
    extraction,
    missingInputs,
    needsWorkspace,
    options,
    recipe,
    reset,
    slots,
    targetProjectId,
    task,
    trackSelection,
    tracksInvalid,
    videoInput,
    videoPath,
    videoPaths,
  ]);

  const displayOutputs = useMemo(() => {
    const merged = [...outputs];
    for (const path of artifactPaths) if (!merged.includes(path)) merged.push(path);
    return merged;
  }, [artifactPaths, outputs]);

  const badge = engineBadge(engineStatus);
  const batchDone = batchItems.filter((item) => item.status === "done").length;
  const batchFailed = batchItems.filter((item) => item.status === "failed").length;

  return (
    <div className="min-h-screen bg-slate-100 px-5 py-6 text-slate-900">
      <div className="mx-auto max-w-6xl space-y-5">
        <header className="flex flex-wrap items-start justify-between gap-3">
          <div>
            <h1 className="flex flex-wrap items-center gap-2 text-2xl font-semibold tracking-tight">
              字幕工具箱 · Pipeline v2
              {appVersion && (
                <span
                  data-testid="app-version"
                  className="rounded-full border border-slate-300 bg-white px-2 py-0.5 text-[11px] font-medium text-slate-500"
                >
                  v{appVersion}
                </span>
              )}
            </h1>
            <p className="text-sm text-slate-500">先选任务，再放入对应文件，最后运行。</p>
          </div>
          <div className="flex flex-wrap items-center gap-2">
            <button
              type="button"
              data-testid="open-settings"
              onClick={() => navigate({ name: "settings" })}
              className="inline-flex items-center gap-1.5 rounded-full border border-slate-300 bg-white px-3 py-1.5 text-xs font-medium text-slate-700 hover:bg-slate-50"
            >
              <Settings className="h-3.5 w-3.5" /> 设置
            </button>
            <button
              type="button"
              onClick={() => navigate({ name: "editor", recipeId: null })}
              className="inline-flex items-center gap-1.5 rounded-full border border-slate-300 bg-white px-3 py-1.5 text-xs font-medium text-slate-700 hover:bg-slate-50"
            >
              <Workflow className="h-3.5 w-3.5" /> 配方编辑器
            </button>
            <span
              className={`inline-flex max-w-md items-center gap-2 rounded-full border px-3 py-1.5 text-xs ${badge.tone}`}
            >
              <span className="truncate">{badge.text}</span>
            </span>
            <button
              type="button"
              title="重启引擎"
              data-testid="restart-engine"
              aria-label="重启引擎"
              disabled={restartBusy || engineStatus.state === "starting"}
              onClick={() => void handleRestart()}
              className="rounded-full border border-slate-300 bg-white p-2 text-slate-600 hover:bg-slate-50 disabled:cursor-not-allowed disabled:opacity-40"
            >
              {restartBusy || engineStatus.state === "starting" ? (
                <Loader2 className="h-4 w-4 animate-spin" />
              ) : (
                <RefreshCw className="h-4 w-4" />
              )}
            </button>
          </div>
        </header>

        {restartError && (
          <p role="alert" className="flex items-start gap-2 rounded-xl border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700">
            <AlertCircle className="mt-0.5 h-4 w-4 shrink-0" /> 重启引擎失败：{restartError}
          </p>
        )}

        <TaskPicker
          tasks={tasks}
          selectedId={selectedTaskId}
          loading={tasksLoading}
          error={tasksError}
          onSelect={handleSelectTask}
        />

        {!task ? (
          <p className="rounded-2xl border border-dashed border-slate-300 bg-white px-5 py-10 text-center text-sm text-slate-500">
            {tasksLoading ? "正在读取任务目录…" : "暂无可执行任务，请确认引擎已就绪。"}
          </p>
        ) : (
          <div className="grid gap-5 lg:grid-cols-[minmax(0,1.55fr)_minmax(0,1fr)]">
            <div className="space-y-5">
              <section className="rounded-2xl border border-slate-200 bg-white p-5">
                <div className="flex flex-wrap items-start justify-between gap-3">
                  <div>
                    <h2 className="text-base font-semibold text-slate-800">{task.title}</h2>
                    <p className="mt-0.5 text-sm text-slate-500">{task.description}</p>
                    <p className="mt-1 font-mono text-[11px] text-slate-400">
                      recipe: {task.recipe_id}
                    </p>
                  </div>
                </div>

                <div className="mt-4">
                  <h3 className="mb-2 text-sm font-semibold text-slate-800">输入文件</h3>
                  <TaskInputs
                    task={task}
                    slots={slots}
                    autofilled={autofilled}
                    routing={routing}
                    disabled={running}
                    onSet={handleSetSlot}
                    onClear={handleClearSlot}
                    onRoute={(paths, overwrite, recursive) =>
                      void handleRoute(task.id, paths, overwrite, recursive)
                    }
                    onMove={handleMoveSlot}
                    onUndoRouting={() => handleUndoRouting(task.id)}
                  />
                  {routeNotice && (
                    <p
                      role="alert"
                      className="mt-2 rounded-lg border border-amber-200 bg-amber-50 px-3 py-2 text-sm text-amber-800"
                    >
                      {routeNotice}
                    </p>
                  )}
                </div>

                {missingInputs.length > 0 && (
                  <p className="mt-3 rounded-lg border border-amber-200 bg-amber-50 px-3 py-2 text-sm text-amber-800">
                    请填写必填输入：{missingInputs.map(taskInputLabel).join("、")}
                  </p>
                )}
                {tracksInvalid && (
                  <p className="mt-3 rounded-lg border border-amber-200 bg-amber-50 px-3 py-2 text-sm text-amber-800">
                    请至少选择一条字幕轨道，或切换为自动选择。
                  </p>
                )}

                <div className="mt-5">
                  <h3 className="mb-2 text-sm font-semibold text-slate-800">运行选项</h3>
                  {recipeError ? (
                    <p className="rounded-lg bg-red-50 px-3 py-2 text-sm text-red-700">
                      读取配方失败：{recipeError}
                    </p>
                  ) : recipeLoading ? (
                    <p className="inline-flex items-center gap-1.5 text-sm text-slate-500">
                      <Loader2 className="h-4 w-4 animate-spin" /> 正在读取配方…
                    </p>
                  ) : (
                    <TaskOptions
                      task={task}
                      steps={steps}
                      recipe={recipe}
                      options={options}
                      selection={trackSelection}
                      videoPath={videoPath}
                      disabled={running}
                      onOptionsChange={handleOptionsChange}
                      onSelectionChange={handleTrackChange}
                    />
                  )}
                </div>

                {bilingual && targetedProjectHint(projects, targetProjectId)}

                <RunFeedback
                  runId={runId}
                  status={status}
                  progress={progress}
                  logs={logs}
                  lastError={lastError}
                  onReset={reset}
                />

                {status === "waiting_review" && runId && (
                  <button
                    type="button"
                    onClick={() => navigate({ name: "review", runId })}
                    className="mt-3 inline-flex items-center gap-1.5 rounded-lg bg-amber-600 px-3 py-2 text-sm font-medium text-white hover:bg-amber-500"
                  >
                    前往审核
                  </button>
                )}

              </section>
            </div>

            <div className="space-y-5">
              {active && (
                <HandoffCard
                  project={active}
                  outputs={runProjectId === active.id ? displayOutputs : undefined}
                  onClose={() => {
                    useProjectStore.getState().clearActive();
                    setTargetProjectId(null);
                  }}
                >
                  {batchItems.length > 0 && (
                    <div
                      data-testid="batch-queue"
                      className="mt-3 rounded-xl border border-emerald-200 bg-white/80 p-3"
                    >
                      <div className="flex flex-wrap items-center justify-between gap-2">
                        <p className="text-xs font-medium text-slate-700">
                          批量队列 · 完成 {batchDone}/{batchItems.length}
                          {batchFailed > 0 && (
                            <span className="text-rose-600"> · 失败 {batchFailed}</span>
                          )}
                        </p>
                        {batchActive ? (
                          <button
                            type="button"
                            onClick={() => useBatchStore.getState().finish()}
                            className="rounded border border-slate-300 bg-white px-2 py-1 text-[11px] text-slate-600 hover:bg-slate-100"
                          >
                            取消批量（当前视频完成后停止）
                          </button>
                        ) : (
                          <button
                            type="button"
                            onClick={() => useBatchStore.getState().reset()}
                            className="rounded border border-slate-300 bg-white px-2 py-1 text-[11px] text-slate-600 hover:bg-slate-100"
                          >
                            清除队列
                          </button>
                        )}
                      </div>
                      <ul className="mt-2 space-y-1">
                        {batchItems.map((item, index) => (
                          <li
                            key={`${item.path}:${index}`}
                            className="flex flex-wrap items-center justify-between gap-2 rounded bg-white px-2 py-1.5 text-xs"
                          >
                            <div className="flex min-w-0 items-center gap-1.5">
                              {item.status === "running" ||
                              item.status === "waiting_review" ? (
                                <Loader2 className="h-3.5 w-3.5 shrink-0 animate-spin text-sky-600" />
                              ) : item.status === "done" ? (
                                <Check className="h-3.5 w-3.5 shrink-0 text-emerald-600" />
                              ) : item.status === "failed" ? (
                                <AlertCircle className="h-3.5 w-3.5 shrink-0 text-rose-600" />
                              ) : (
                                <span className="inline-block h-3.5 w-3.5 shrink-0 rounded-full border border-slate-300" />
                              )}
                              <span
                                className="truncate font-mono text-slate-700"
                                title={item.path}
                              >
                                {index + 1}. {fileName(item.path)}
                              </span>
                            </div>
                            <div className="flex items-center gap-2">
                              {item.error && (
                                <span
                                  className="max-w-[18rem] truncate text-rose-600"
                                  title={item.error}
                                >
                                  {item.error}
                                </span>
                              )}
                              {item.status === "done" && (
                                <span className="text-emerald-700">
                                  {item.outputs.length > 0
                                    ? `${item.outputs.length} 个产物`
                                    : "完成"}
                                </span>
                              )}
                              {item.status === "waiting_review" && item.runId && (
                                <button
                                  type="button"
                                  onClick={() =>
                                    navigate({ name: "review", runId: item.runId! })
                                  }
                                  className="rounded bg-amber-600 px-2 py-0.5 text-[11px] text-white hover:bg-amber-500"
                                >
                                  前往审核
                                </button>
                              )}
                              {item.status === "pending" && (
                                <span className="text-slate-400">排队中</span>
                              )}
                              {item.status === "running" && (
                                <span className="text-sky-700">运行中</span>
                              )}
                              {item.status === "waiting_review" && (
                                <span className="text-amber-700">等待审核</span>
                              )}
                              {item.status === "failed" && (
                                <span className="text-rose-700">失败</span>
                              )}
                            </div>
                          </li>
                        ))}
                      </ul>
                    </div>
                  )}
                  {outputError && <p className="mt-3 text-xs text-red-600">{outputError}</p>}
                </HandoffCard>
              )}
              <ProjectList
                projects={projects}
                activeId={active?.id}
                loading={projectsLoading}
                deletingId={deletingProjectId}
                onDelete={(id) => void handleDeleteProject(id)}
                onSelect={(id) => {
                  setTargetProjectId(id);
                  void select(id);
                }}
              />
              {projectError && (
                <p
                  role="alert"
                  className="rounded-lg border border-red-200 bg-red-50 px-3 py-2 text-xs text-red-700"
                >
                  项目操作失败：{projectError}
                </p>
              )}
            </div>
          </div>
        )}
      </div>

      {task && (
        <button
          type="button"
          data-testid="run-task"
          onClick={() => void runTask()}
          disabled={!canRun}
          className="fixed bottom-6 right-6 z-50 inline-flex items-center gap-2 rounded-full bg-slate-900 px-5 py-3 text-sm font-medium text-white shadow-lg shadow-slate-900/20 transition hover:bg-slate-800 disabled:cursor-not-allowed disabled:bg-slate-300 disabled:shadow-none"
        >
          {running ? (
            <Loader2 className="h-4 w-4 animate-spin" />
          ) : (
            <Play className="h-4 w-4" />
          )}
          {batchActive
            ? batchItems.length > 0
              ? `批量处理中 · ${batchDone}/${batchItems.length}`
              : "其他任务批量处理中…"
            : running
              ? "运行中…"
              : batchMode || batchItems.length > 1
                ? `批量处理 ${Math.max(videoPaths.length, batchItems.length)} 个视频`
                : "开始运行"}
        </button>
      )}
    </div>
  );
}

function targetedProjectHint(
  projects: Array<{ id: string; name: string }>,
  targetProjectId: string | null,
) {
  if (!targetProjectId) return null;
  const project = projects.find((item) => item.id === targetProjectId);
  if (!project) return null;
  return (
    <p className="mt-3 rounded-lg bg-slate-50 px-3 py-2 text-xs text-slate-500">
      目标项目：{project.name}
    </p>
  );
}

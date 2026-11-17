import { useEffect, useMemo, useRef } from "react";
import { Loader2, Play, RotateCcw } from "lucide-react";
import { createProject, runRecipe, validateRecipe } from "../../lib/api";
import { isSubtitlePath, isVideoPath } from "../../lib/models";
import { HandoffCard } from "../projects/HandoffCard";
import { ProjectList } from "../projects/ProjectList";
import { useProjectStore } from "../../stores/projectStore";
import { useRunStore } from "../../stores/runStore";

interface RunViewProps {
  paths: string[];
  engineReady: boolean;
}

const RECIPE_ID = "video_to_clean_srt";

export function RunView({ paths, engineReady }: RunViewProps) {
  const { runId, status, progress, logs, lastError, begin, reset } = useRunStore();
  const { projects, active, loading, select } = useProjectStore();
  const logRef = useRef<HTMLDivElement>(null);

  const videoPath = useMemo(() => paths.find(isVideoPath) ?? null, [paths]);
  const subtitleOnly = !videoPath && paths.some(isSubtitlePath);

  useEffect(() => {
    if (logRef.current) logRef.current.scrollTop = logRef.current.scrollHeight;
  }, [logs]);

  useEffect(() => {
    if ((status === "done" || status === "failed") && runId) {
      const projectId = useRunStore.getState().projectId;
      if (projectId) void select(projectId);
      void useProjectStore.getState().refresh();
    }
  }, [status, runId, select]);

  const start = async () => {
    reset();
    if (!videoPath) {
      useRunStore.setState({
        status: "failed",
        lastError: "请先拖入视频文件（.mkv / .mp4 / .mov / .avi / .ts）",
      });
      return;
    }
    try {
      const project = await createProject({ media_path: videoPath });
      useProjectStore.getState().applyUpdate(project);

      const validation = await validateRecipe(RECIPE_ID, project.id);
      if (!validation.ok) {
        useRunStore.setState({
          status: "failed",
          lastError: validation.errors.map((issue) => issue.message).join("；"),
        });
        return;
      }

      const result = await runRecipe({
        recipeId: RECIPE_ID,
        inputs: [videoPath],
        projectId: project.id,
      });
      begin(result.run_id, project.id);
    } catch (error) {
      useRunStore.setState({
        status: "failed",
        lastError: error instanceof Error ? error.message : String(error),
      });
    }
  };

  const running = status === "running";

  return (
    <div className="grid gap-5 lg:grid-cols-[minmax(0,1.55fr)_minmax(0,1fr)]">
      <div className="space-y-5">
        <section className="rounded-2xl border border-slate-200 bg-white p-5">
          <div className="flex flex-wrap items-center justify-between gap-3">
            <div>
              <h2 className="text-base font-semibold text-slate-800">视频 → 规范字幕</h2>
              <p className="text-sm text-slate-500">
                提取内嵌字幕 → 清理 → 校验 → 导出干净 SRT（recipe: {RECIPE_ID}）
              </p>
            </div>
            <button
              type="button"
              onClick={() => void start()}
              disabled={!engineReady || running}
              className="inline-flex items-center gap-2 rounded-lg bg-slate-900 px-4 py-2 text-sm font-medium text-white hover:bg-slate-800 disabled:cursor-not-allowed disabled:bg-slate-300"
            >
              {running ? <Loader2 className="h-4 w-4 animate-spin" /> : <Play className="h-4 w-4" />}
              {running ? "运行中…" : "开始处理视频"}
            </button>
          </div>

          {paths.length > 0 && (
            <ul className="mt-4 space-y-1 rounded-lg bg-slate-50 p-3 text-xs text-slate-600">
              {paths.map((path) => (
                <li key={path} className="truncate font-mono" title={path}>
                  {path}
                </li>
              ))}
            </ul>
          )}

          {!videoPath && paths.length > 0 && (
            <p className="mt-3 rounded-lg border border-amber-200 bg-amber-50 px-3 py-2 text-sm text-amber-800">
              {subtitleOnly
                ? "检测到字幕文件。译文合并流程将在 M7 开放；当前 M3 请拖入视频生成干净 SRT。"
                : "没有可处理的视频文件。"}
            </p>
          )}

          <div className="mt-4">
            <div className="mb-1 flex justify-between text-xs text-slate-500">
              <span>
                {runId ? `run_id: ${runId}` : "尚未运行"}
                {status !== "idle" && ` · ${status}`}
              </span>
              <span>{Math.round(progress * 100)}%</span>
            </div>
            <div className="h-2 overflow-hidden rounded-full bg-slate-200">
              <div
                className={`h-full rounded-full transition-[width] duration-200 ${
                  status === "failed"
                    ? "bg-red-500"
                    : status === "done"
                      ? "bg-emerald-500"
                      : "bg-sky-500"
                }`}
                style={{ width: `${Math.round(progress * 100)}%` }}
              />
            </div>
          </div>

          {lastError && (
            <p className="mt-3 rounded-lg bg-red-50 px-3 py-2 text-sm text-red-700">{lastError}</p>
          )}

          <div
            ref={logRef}
            className="mt-4 h-64 overflow-auto rounded-lg bg-slate-950 p-3 font-mono text-xs leading-relaxed text-slate-200"
          >
            {logs.length === 0 ? (
              <p className="text-slate-500">日志会显示在这里（提取 / 规范 / 校验 / 导出）。</p>
            ) : (
              logs.map((entry) => (
                <div
                  key={entry.key}
                  className={
                    entry.level === "error"
                      ? "text-red-400"
                      : entry.level === "warning"
                        ? "text-amber-300"
                        : "text-slate-200"
                  }
                >
                  <span className="text-slate-500">[{String(entry.seq).padStart(3, "0")}]</span>{" "}
                  <span className="text-slate-400">{entry.type}</span> {entry.message}
                </div>
              ))
            )}
          </div>

          {status !== "idle" && (
            <button
              type="button"
              onClick={reset}
              className="mt-3 inline-flex items-center gap-1 text-xs text-slate-500 hover:text-slate-700"
            >
              <RotateCcw className="h-3 w-3" /> 清空
            </button>
          )}
        </section>

        {active && (
          <HandoffCard project={active} />
        )}
      </div>

      <ProjectList
        projects={projects}
        activeId={active?.id}
        loading={loading}
        onSelect={(id) => void select(id)}
      />
    </div>
  );
}

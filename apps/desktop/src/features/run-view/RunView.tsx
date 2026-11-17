import { useEffect, useMemo } from "react";
import { ArrowRight, ClipboardCheck, Loader2, Play } from "lucide-react";
import { createProject, runRecipe, validateRecipe } from "../../lib/api";
import { isSubtitleOnly, subtitlePaths } from "../../lib/flow2";
import { isVideoPath } from "../../lib/models";
import { navigate } from "../../lib/router";
import { HandoffCard } from "../projects/HandoffCard";
import { ProjectList } from "../projects/ProjectList";
import { useProjectStore } from "../../stores/projectStore";
import { useRunStore } from "../../stores/runStore";
import { RunFeedback } from "./RunFeedback";
import { TranslatedToBilingual } from "./TranslatedToBilingual";

interface RunViewProps {
  paths: string[];
  engineReady: boolean;
}

const RECIPE_ID = "video_to_clean_srt";

interface VideoToCleanSrtProps {
  paths: string[];
  videoPath: string | null;
  engineReady: boolean;
}

function VideoToCleanSrt({ paths, videoPath, engineReady }: VideoToCleanSrtProps) {
  const { runId, status, progress, logs, lastError, begin, reset } = useRunStore();

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
          disabled={!engineReady || running || status === "waiting_review"}
          className="inline-flex items-center gap-2 rounded-lg bg-slate-900 px-4 py-2 text-sm font-medium text-white hover:bg-slate-800 disabled:cursor-not-allowed disabled:bg-slate-300"
        >
          {running ? <Loader2 className="h-4 w-4 animate-spin" /> : <Play className="h-4 w-4" />}
          {running ? "运行中…" : "开始处理视频"}
        </button>
      </div>

      {status === "waiting_review" && runId && (
        <div className="mt-4 flex flex-wrap items-center justify-between gap-3 rounded-xl border border-amber-300 bg-amber-50 p-3">
          <div className="flex items-start gap-2">
            <ClipboardCheck className="mt-0.5 h-4 w-4 shrink-0 text-amber-700" />
            <div>
              <p className="text-sm font-medium text-amber-900">有字幕项等待人工审核</p>
              <p className="text-xs text-amber-800">
                运行已暂停（waiting_review），审核提交后会自动继续。
              </p>
            </div>
          </div>
          <button
            type="button"
            onClick={() => navigate({ name: "review", runId })}
            className="inline-flex items-center gap-1.5 rounded-lg bg-amber-600 px-4 py-2 text-sm font-medium text-white hover:bg-amber-500"
          >
            前往审核 <ArrowRight className="h-4 w-4" />
          </button>
        </div>
      )}

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
          没有可处理的视频文件。
        </p>
      )}

      <RunFeedback
        runId={runId}
        status={status}
        progress={progress}
        logs={logs}
        lastError={lastError}
        onReset={reset}
      />
    </section>
  );
}

export function RunView({ paths, engineReady }: RunViewProps) {
  const { active, projects, loading, select } = useProjectStore();
  const { status, runId } = useRunStore();

  const videoPath = useMemo(() => paths.find(isVideoPath) ?? null, [paths]);
  const subtitleOnly = useMemo(
    () => !videoPath && isSubtitleOnly(paths),
    [paths, videoPath],
  );
  const subtitles = useMemo(() => subtitlePaths(paths), [paths]);

  useEffect(() => {
    if ((status === "done" || status === "failed") && runId) {
      const projectId = useRunStore.getState().projectId;
      if (projectId) void select(projectId);
      void useProjectStore.getState().refresh();
    }
  }, [status, runId, select]);

  return (
    <div className="grid gap-5 lg:grid-cols-[minmax(0,1.55fr)_minmax(0,1fr)]">
      <div className="space-y-5">
        {subtitleOnly ? (
          <TranslatedToBilingual paths={subtitles} engineReady={engineReady} />
        ) : (
          <VideoToCleanSrt paths={paths} videoPath={videoPath} engineReady={engineReady} />
        )}

        {active && <HandoffCard project={active} />}
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

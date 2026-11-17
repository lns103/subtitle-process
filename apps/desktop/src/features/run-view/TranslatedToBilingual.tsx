import { useCallback, useEffect, useMemo, useState } from "react";
import {
  Check,
  Clipboard,
  FileAudio2,
  FolderOpen,
  Languages,
  Loader2,
  Play,
} from "lucide-react";
import { revealPath, runRecipe, validateRecipe } from "../../lib/api";
import { pickProjectForSubtitles, subtitlePaths } from "../../lib/flow2";
import type { ProjectSummary } from "../../lib/models";
import { useProjectStore } from "../../stores/projectStore";
import { useRunStore } from "../../stores/runStore";
import { RunFeedback } from "./RunFeedback";

interface TranslatedToBilingualProps {
  paths: string[];
  engineReady: boolean;
}

const RECIPE_ID = "translated_to_bilingual";

const STATUS_TEXT: Record<ProjectSummary["status"], string> = {
  draft: "草稿",
  running: "运行中",
  waiting_review: "等待审核",
  waiting_translation: "等待翻译",
  done: "已完成",
  failed: "失败",
};

const STATUS_TONE: Record<ProjectSummary["status"], string> = {
  draft: "bg-slate-100 text-slate-600",
  running: "bg-sky-100 text-sky-700",
  waiting_review: "bg-amber-100 text-amber-700",
  waiting_translation: "bg-violet-100 text-violet-700",
  done: "bg-emerald-100 text-emerald-700",
  failed: "bg-red-100 text-red-700",
};

const UNMATCHED_HINT = "未找到原项目，请先在项目库选择或先完成视频清理流程。";

/** 流程 2：译文 SRT → 匹配项目 → 合并双语 ASS。 */
export function TranslatedToBilingual({ paths, engineReady }: TranslatedToBilingualProps) {
  const { projects, active, loading, preferredProjectId, preferProject } = useProjectStore();
  const { runId, status, progress, logs, lastError, begin, reset } = useRunStore();
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [startedRunId, setStartedRunId] = useState<string | null>(null);
  const [copied, setCopied] = useState(false);

  const subtitles = useMemo(() => subtitlePaths(paths), [paths]);
  const recommended = useMemo(
    () => pickProjectForSubtitles(projects, paths),
    [projects, paths],
  );

  const orderedProjects = useMemo(
    () =>
      [...projects].sort((left, right) => {
        const waiting =
          Number(right.status === "waiting_translation") -
          Number(left.status === "waiting_translation");
        if (waiting !== 0) return waiting;
        return Date.parse(right.updated_at) - Date.parse(left.updated_at);
      }),
    [projects],
  );

  useEffect(() => {
    void useProjectStore.getState().refresh();
  }, []);

  useEffect(() => {
    if (selectedId && projects.some((project) => project.id === selectedId)) return;
    setSelectedId(recommended?.id ?? null);
  }, [recommended, projects, selectedId]);

  // HandoffCard 的「继续合并译文」会先写入 preferredProjectId，这里完成预选。
  useEffect(() => {
    if (!preferredProjectId) return;
    if (!projects.some((project) => project.id === preferredProjectId)) return;
    setSelectedId(preferredProjectId);
    preferProject(null);
  }, [preferredProjectId, projects, preferProject]);

  const selectedSummary = projects.find((project) => project.id === selectedId) ?? null;
  const selectedProject = active?.id === selectedId ? active : null;
  const outputPaths = selectedProject
    ? selectedProject.outputs.map((output) => output.path)
    : (selectedSummary?.outputs ?? []);
  const assOutput = useMemo(
    () => [...outputPaths].reverse().find((path) => /\.ass$/i.test(path)) ?? null,
    [outputPaths],
  );

  const running = status === "running";
  const showOutput = status === "done" && Boolean(runId) && runId === startedRunId;
  const unmatched = useMemo(
    () => Boolean(lastError && /未找到|匹配|原文|no_candidates|low_confidence/i.test(lastError)),
    [lastError],
  );

  const start = async () => {
    reset();
    if (!selectedId) {
      useRunStore.setState({ status: "failed", lastError: "请先选择译文对应的目标项目。" });
      return;
    }
    if (subtitles.length === 0) {
      useRunStore.setState({ status: "failed", lastError: "请拖入译文字幕（.srt / .ass / .vtt）。" });
      return;
    }

    try {
      const validation = await validateRecipe(RECIPE_ID, selectedId);
      if (!validation.ok) {
        useRunStore.setState({
          status: "failed",
          lastError: validation.errors.map((issue) => issue.message).join("；"),
        });
        return;
      }

      const result = await runRecipe({
        recipeId: RECIPE_ID,
        inputs: subtitles,
        projectId: selectedId,
      });
      setStartedRunId(result.run_id);
      begin(result.run_id, selectedId);
    } catch (error) {
      useRunStore.setState({
        status: "failed",
        lastError: error instanceof Error ? error.message : String(error),
      });
    }
  };

  const handleReveal = useCallback(async () => {
    if (!assOutput) return;
    try {
      await revealPath(assOutput);
    } catch (error) {
      useRunStore.setState({
        lastError: error instanceof Error ? error.message : String(error),
      });
    }
  }, [assOutput]);

  const handleCopy = useCallback(async () => {
    if (!assOutput) return;
    try {
      await navigator.clipboard.writeText(assOutput);
      setCopied(true);
      window.setTimeout(() => setCopied(false), 1500);
    } catch (error) {
      useRunStore.setState({
        lastError: error instanceof Error ? error.message : String(error),
      });
    }
  }, [assOutput]);

  return (
    <section className="rounded-2xl border border-slate-200 bg-white p-5">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h2 className="flex items-center gap-2 text-base font-semibold text-slate-800">
            <Languages className="h-4 w-4" /> 译文 → 双语 ASS
          </h2>
          <p className="text-sm text-slate-500">
            匹配原项目 → 校验译文 → 合并双语 ASS（recipe: {RECIPE_ID}）
          </p>
        </div>
        <button
          type="button"
          data-testid="run-translated"
          onClick={() => void start()}
          disabled={!engineReady || running || !selectedId || subtitles.length === 0}
          className="inline-flex items-center gap-2 rounded-lg bg-slate-900 px-4 py-2 text-sm font-medium text-white hover:bg-slate-800 disabled:cursor-not-allowed disabled:bg-slate-300"
        >
          {running ? <Loader2 className="h-4 w-4 animate-spin" /> : <Play className="h-4 w-4" />}
          {running ? "合并中…" : "合并为双语 ASS"}
        </button>
      </div>

      <div className="mt-4 rounded-lg bg-slate-50 p-3">
        <p className="text-xs font-medium text-slate-500">拖入的译文字幕</p>
        <ul className="mt-1 space-y-1 text-xs text-slate-600">
          {subtitles.map((path) => (
            <li key={path} className="truncate font-mono" title={path}>
              {path}
            </li>
          ))}
        </ul>
      </div>

      <div className="mt-4">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <p className="text-xs font-medium text-slate-500">选择目标项目</p>
          {recommended && recommended.id === selectedId && (
            <span className="text-[11px] text-emerald-600">已按文件名推荐</span>
          )}
        </div>

        {orderedProjects.length === 0 ? (
          <p className="mt-2 rounded-lg border border-amber-200 bg-amber-50 px-3 py-2 text-sm text-amber-800">
            还没有项目。请先拖入视频完成「视频 → 规范字幕」流程。
          </p>
        ) : (
          <ul className="mt-2 max-h-60 space-y-1 overflow-auto">
            {orderedProjects.map((project) => {
              const isSelected = project.id === selectedId;
              const latest = project.outputs[project.outputs.length - 1] ?? null;
              return (
                <li key={project.id}>
                  <button
                    type="button"
                    onClick={() => setSelectedId(project.id)}
                    className={`flex w-full items-start justify-between gap-3 rounded-lg border px-3 py-2 text-left ${
                      isSelected
                        ? "border-slate-900 bg-slate-50"
                        : "border-slate-200 bg-white hover:bg-slate-50"
                    }`}
                  >
                    <span className="min-w-0">
                      <span className="flex items-center gap-2">
                        <span className="truncate text-sm font-medium text-slate-800">
                          {project.name}
                        </span>
                        {project.id === recommended?.id && (
                          <span className="shrink-0 rounded bg-emerald-100 px-1.5 py-0.5 text-[10px] text-emerald-700">
                            推荐
                          </span>
                        )}
                      </span>
                      <span
                        className="mt-1 block truncate font-mono text-[11px] text-slate-400"
                        title={latest ?? project.workspace}
                      >
                        {latest ?? "暂无产物"}
                      </span>
                    </span>
                    <span
                      className={`shrink-0 rounded-full px-2 py-0.5 text-xs ${STATUS_TONE[project.status]}`}
                    >
                      {STATUS_TEXT[project.status]}
                    </span>
                  </button>
                </li>
              );
            })}
          </ul>
        )}

        {!selectedId && orderedProjects.length > 0 && (
          <p className="mt-2 text-xs text-amber-700">请选择一个项目后再运行合并。</p>
        )}
        {loading && <p className="mt-2 text-xs text-slate-400">项目加载中…</p>}
      </div>

      {showOutput && assOutput && (
        <div className="mt-4 rounded-xl border border-emerald-200 bg-emerald-50/60 p-3">
          <p className="text-xs font-medium text-emerald-800">双语 ASS 已导出</p>
          <p className="mt-1 break-all font-mono text-xs text-slate-800" title={assOutput}>
            {assOutput}
          </p>
          <div className="mt-2 flex flex-wrap gap-2">
            <button
              type="button"
              onClick={() => void handleReveal()}
              className="inline-flex items-center gap-2 rounded-lg border border-emerald-300 bg-white px-3 py-2 text-sm text-emerald-800 hover:bg-emerald-100"
            >
              <FolderOpen className="h-4 w-4" /> 打开所在文件夹
            </button>
            <button
              type="button"
              onClick={() => void handleCopy()}
              className="inline-flex items-center gap-2 rounded-lg border border-emerald-300 bg-white px-3 py-2 text-sm text-emerald-800 hover:bg-emerald-100"
            >
              {copied ? <Check className="h-4 w-4" /> : <Clipboard className="h-4 w-4" />}
              {copied ? "已复制" : "复制路径"}
            </button>
          </div>
        </div>
      )}

      <RunFeedback
        runId={runId}
        status={status}
        progress={progress}
        logs={logs}
        lastError={lastError}
        errorHint={unmatched ? UNMATCHED_HINT : null}
        logPlaceholder="日志会显示在这里（匹配项目 / 校验译文 / 合并双语 / 导出）。"
        onReset={reset}
      />

      <p className="mt-3 flex items-center gap-1.5 text-xs text-slate-400">
        <FileAudio2 className="h-3.5 w-3.5" /> 需要当前项目已有原文 SRT；匹配失败时可手动切换项目。
      </p>
    </section>
  );
}

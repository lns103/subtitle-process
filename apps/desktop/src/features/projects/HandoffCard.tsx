import { useCallback, useMemo, useState, type ReactNode } from "react";
import {
  ArrowRight,
  Check,
  Clipboard,
  FileCheck2,
  FolderOpen,
  Languages,
  Loader2,
  Pencil,
  ShieldCheck,
  X,
} from "lucide-react";
import { revealPath } from "../../lib/api";
import type { Project } from "../../lib/models";
import { navigate } from "../../lib/router";
import { findBilingualTask } from "../../lib/tasks";
import { useProjectStore } from "../../stores/projectStore";
import { useTaskStore } from "../../stores/taskStore";

interface HandoffCardProps {
  project: Project;
  /** 关闭当前项目面板；不会删除项目数据。 */
  onClose?: () => void;
  /** 当前运行/本次任务展示的产物；省略时使用项目已归档产物。 */
  outputs?: string[];
  /** 附加内容（例如运行中的批量队列）。 */
  children?: ReactNode;
}

const STATUS_TEXT: Record<Project["status"], string> = {
  draft: "草稿",
  running: "运行中",
  waiting_review: "等待审核",
  waiting_translation: "等待翻译",
  done: "已完成",
  failed: "失败",
};

export function HandoffCard({ project, onClose, outputs, children }: HandoffCardProps) {
  const [copied, setCopied] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [editingName, setEditingName] = useState(false);
  const [draftName, setDraftName] = useState(project.name);
  const [savingName, setSavingName] = useState(false);
  const [nameError, setNameError] = useState<string | null>(null);
  const [expanded, setExpanded] = useState(false);

  const paths = useMemo(() => {
    if (outputs && outputs.length > 0) return outputs;
    return project.outputs.map((output) => output.path);
  }, [outputs, project.outputs]);

  const latestPath = paths.length > 0 ? paths[paths.length - 1] : null;
  const running = project.status === "running";
  // 运行中实时展开；完成后默认折叠，只保留最新产物。
  const showAll = running || expanded;
  const visiblePaths = showAll ? paths : latestPath ? [latestPath] : [];

  const handleReveal = useCallback(async () => {
    const target = latestPath ?? project.workspace;
    if (!target) return;
    try {
      await revealPath(target);
      setError(null);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : String(reason));
    }
  }, [latestPath, project.workspace]);

  const handleCopy = useCallback(async () => {
    if (!latestPath) return;
    try {
      await navigator.clipboard.writeText(latestPath);
      setCopied(true);
      window.setTimeout(() => setCopied(false), 1500);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : String(reason));
    }
  }, [latestPath]);

  const startRename = () => {
    setDraftName(project.name);
    setNameError(null);
    setEditingName(true);
  };

  const submitRename = async () => {
    const next = draftName.trim();
    if (!next) {
      setNameError("项目名不能为空");
      return;
    }
    if (next === project.name) {
      setEditingName(false);
      return;
    }
    setSavingName(true);
    try {
      await useProjectStore.getState().rename(project.id, next);
      setEditingName(false);
      setNameError(null);
    } catch (reason) {
      setNameError(reason instanceof Error ? reason.message : String(reason));
    } finally {
      setSavingName(false);
    }
  };

  const isWaiting = project.status === "waiting_translation";
  const reviewRunId = useMemo(() => {
    if (project.status !== "waiting_review") return null;
    const pending = [...project.runs]
      .reverse()
      .find((run) => run.status === "waiting_review");
    return pending?.id ?? project.runs[project.runs.length - 1]?.id ?? null;
  }, [project.runs, project.status]);

  return (
    <section className="rounded-2xl border border-emerald-200 bg-emerald-50/60 p-5">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="min-w-0">
          {editingName ? (
            <form
              onSubmit={(event) => {
                event.preventDefault();
                void submitRename();
              }}
              className="flex items-center gap-1.5"
            >
              <input
                autoFocus
                value={draftName}
                maxLength={120}
                aria-label="项目名称"
                data-testid="project-name-input"
                onChange={(event) => setDraftName(event.target.value)}
                onKeyDown={(event) => {
                  if (event.key === "Escape") setEditingName(false);
                }}
                className="w-56 rounded-lg border border-emerald-300 bg-white px-2 py-1 text-base font-semibold text-emerald-900 outline-none focus:border-emerald-500"
              />
              <button
                type="submit"
                aria-label="保存项目名称"
                title="保存"
                data-testid="save-project-name"
                disabled={savingName}
                className="rounded-full p-1.5 text-emerald-700 transition hover:bg-emerald-100 disabled:opacity-40"
              >
                {savingName ? (
                  <Loader2 className="h-4 w-4 animate-spin" />
                ) : (
                  <Check className="h-4 w-4" />
                )}
              </button>
              <button
                type="button"
                aria-label="取消修改项目名称"
                title="取消"
                onClick={() => setEditingName(false)}
                disabled={savingName}
                className="rounded-full p-1.5 text-emerald-700 transition hover:bg-emerald-100 disabled:opacity-40"
              >
                <X className="h-4 w-4" />
              </button>
            </form>
          ) : (
            <h3 className="flex items-center gap-2 text-base font-semibold text-emerald-900">
              <FileCheck2 className="h-4 w-4 shrink-0" />
              <span className="truncate" title={project.name}>
                {project.name}
              </span>
              <button
                type="button"
                aria-label="修改项目名称"
                title="修改项目名称"
                data-testid="edit-project-name"
                onClick={startRename}
                className="rounded-full p-1 text-emerald-700 transition hover:bg-emerald-100 hover:text-emerald-900"
              >
                <Pencil className="h-3.5 w-3.5" />
              </button>
            </h3>
          )}
          {nameError && <p className="mt-1 text-xs text-red-600">{nameError}</p>}
          <p className="mt-1 text-sm text-emerald-800">
            {isWaiting
              ? "干净字幕已导出。请用 LinguaGacha 翻译后，把译文 SRT 拖回首页即可继续合并双语 ASS。"
              : `项目状态：${STATUS_TEXT[project.status]}`}
          </p>
        </div>
        <div className="flex items-center gap-2">
          <span className="rounded-full border border-emerald-300 bg-white px-2.5 py-1 text-xs text-emerald-700">
            {STATUS_TEXT[project.status]}
          </span>
          {onClose && (
            <button
              type="button"
              aria-label="关闭当前项目"
              title="关闭项目面板（不会删除项目）"
              data-testid="close-project"
              onClick={onClose}
              className="rounded-full p-1.5 text-emerald-700 transition hover:bg-emerald-100 hover:text-emerald-900"
            >
              <X className="h-4 w-4" />
            </button>
          )}
        </div>
      </div>

      <div className="mt-4 rounded-lg border border-emerald-200 bg-white p-3">
        <div className="flex items-center justify-between gap-2">
          <p className="text-xs text-slate-500">
            产物{paths.length > 1 && !showAll ? `（共 ${paths.length} 个，显示最新）` : ""}
          </p>
          {paths.length > 1 && !running && (
            <button
              type="button"
              onClick={() => setExpanded((value) => !value)}
              className="rounded px-1.5 py-0.5 text-[11px] text-emerald-700 hover:bg-emerald-50"
            >
              {expanded ? "收起" : `展开全部 (${paths.length})`}
            </button>
          )}
        </div>
        {visiblePaths.length > 0 ? (
          <ul className="mt-1 space-y-1">
            {visiblePaths.map((path) => (
              <li
                key={path}
                className="break-all font-mono text-xs text-slate-800"
                title={path}
              >
                {path}
              </li>
            ))}
          </ul>
        ) : running ? (
          <p className="mt-1 text-sm text-slate-500">运行中，产物生成后会显示在这里。</p>
        ) : (
          <p className="mt-1 rounded-lg border border-amber-200 bg-amber-50 p-2 text-sm text-amber-800">
            本次运行没有登记导出产物；请查看运行日志或打开项目工作区。
          </p>
        )}
      </div>

      {children}

      <div className="mt-4 flex flex-wrap gap-2">
        <button
          type="button"
          onClick={() => void handleReveal()}
          className="inline-flex items-center gap-2 rounded-lg border border-emerald-300 bg-white px-3 py-2 text-sm text-emerald-800 hover:bg-emerald-100"
        >
          <FolderOpen className="h-4 w-4" /> 打开所在文件夹
        </button>
        {latestPath && (
          <button
            type="button"
            onClick={() => void handleCopy()}
            className="inline-flex items-center gap-2 rounded-lg border border-emerald-300 bg-white px-3 py-2 text-sm text-emerald-800 hover:bg-emerald-100"
          >
            {copied ? <Check className="h-4 w-4" /> : <Clipboard className="h-4 w-4" />}
            {copied ? "已复制" : "复制路径"}
          </button>
        )}
        {reviewRunId && (
          <button
            type="button"
            onClick={() => navigate({ name: "review", runId: reviewRunId })}
            className="inline-flex items-center gap-2 rounded-lg bg-emerald-600 px-3 py-2 text-sm font-medium text-white hover:bg-emerald-500"
          >
            <ShieldCheck className="h-4 w-4" /> 继续审核
          </button>
        )}
        {isWaiting && (
          <button
            type="button"
            data-testid="continue-translation"
            onClick={() => {
              useProjectStore.getState().preferProject(project.id);
              const bilingual = findBilingualTask(useTaskStore.getState().tasks);
              if (bilingual) {
                useTaskStore.getState().selectTask(bilingual.id);
                navigate({ name: "task", taskId: bilingual.id });
              } else {
                navigate({ name: "home" });
              }
            }}
            className="inline-flex items-center gap-2 rounded-lg bg-emerald-600 px-3 py-2 text-sm font-medium text-white hover:bg-emerald-500"
          >
            <Languages className="h-4 w-4" /> 继续合并译文
            <ArrowRight className="h-4 w-4" />
          </button>
        )}
      </div>

      {isWaiting && (
        <p className="mt-3 text-xs text-emerald-700">
          提示：回到首页后把翻译好的字幕（.srt / .ass / .vtt）拖入窗口，系统会预选该项目。
        </p>
      )}

      {error && (
        <p className="mt-3 rounded-lg bg-red-50 px-3 py-2 text-sm text-red-700">{error}</p>
      )}
    </section>
  );
}

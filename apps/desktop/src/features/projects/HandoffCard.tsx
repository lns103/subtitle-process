import { useCallback, useMemo, useState } from "react";
import { ArrowRight, Check, Clipboard, FileCheck2, FolderOpen, Languages, ShieldCheck } from "lucide-react";
import { revealPath } from "../../lib/api";
import type { Project } from "../../lib/models";
import { navigate } from "../../lib/router";
import { useProjectStore } from "../../stores/projectStore";

interface HandoffCardProps {
  project: Project;
}

const STATUS_TEXT: Record<Project["status"], string> = {
  draft: "草稿",
  running: "运行中",
  waiting_review: "等待审核",
  waiting_translation: "等待翻译",
  done: "已完成",
  failed: "失败",
};

export function HandoffCard({ project }: HandoffCardProps) {
  const [copied, setCopied] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const latest = useMemo(
    () => (project.outputs.length > 0 ? project.outputs[project.outputs.length - 1] : null),
    [project.outputs],
  );

  const handleReveal = useCallback(async () => {
    const target = latest?.path ?? project.workspace;
    if (!target) return;
    try {
      await revealPath(target);
      setError(null);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : String(reason));
    }
  }, [latest, project.workspace]);

  const handleCopy = useCallback(async () => {
    if (!latest) return;
    try {
      await navigator.clipboard.writeText(latest.path);
      setCopied(true);
      window.setTimeout(() => setCopied(false), 1500);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : String(reason));
    }
  }, [latest]);

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
        <div>
          <h3 className="flex items-center gap-2 text-base font-semibold text-emerald-900">
            <FileCheck2 className="h-4 w-4" /> {project.name}
          </h3>
          <p className="mt-1 text-sm text-emerald-800">
            {isWaiting
              ? "干净字幕已导出。请用 LinguaGacha 翻译后，把译文 SRT 拖回首页即可继续合并双语 ASS。"
              : `项目状态：${STATUS_TEXT[project.status]}`}
          </p>
        </div>
        <span className="rounded-full border border-emerald-300 bg-white px-2.5 py-1 text-xs text-emerald-700">
          {STATUS_TEXT[project.status]}
        </span>
      </div>

      {latest ? (
        <div className="mt-4 rounded-lg border border-emerald-200 bg-white p-3">
          <p className="text-xs text-slate-500">最新产物</p>
          <p className="mt-1 break-all font-mono text-xs text-slate-800" title={latest.path}>
            {latest.path}
          </p>
        </div>
      ) : (
        <p className="mt-4 rounded-lg border border-amber-200 bg-amber-50 p-3 text-sm text-amber-800">
          本次运行没有登记导出产物；请查看运行日志或打开项目工作区。
        </p>
      )}

      <div className="mt-4 flex flex-wrap gap-2">
        <button
          type="button"
          onClick={() => void handleReveal()}
          className="inline-flex items-center gap-2 rounded-lg border border-emerald-300 bg-white px-3 py-2 text-sm text-emerald-800 hover:bg-emerald-100"
        >
          <FolderOpen className="h-4 w-4" /> 打开所在文件夹
        </button>
        {latest && (
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
              navigate({ name: "home" });
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

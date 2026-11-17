import { useEffect, useRef } from "react";
import { RotateCcw } from "lucide-react";
import type { RunLogEntry } from "../../stores/runStore";

interface RunFeedbackProps {
  runId: string | null;
  status: "idle" | "running" | "waiting_review" | "done" | "failed" | "cancelled";
  progress: number;
  logs: RunLogEntry[];
  lastError: string | null;
  /** 失败时的补充说明（如流程 2 未匹配到项目）。 */
  errorHint?: string | null;
  logPlaceholder?: string;
  onReset: () => void;
}

/** 视频流程与译文流程共用的进度条、日志与清空按钮。 */
export function RunFeedback({
  runId,
  status,
  progress,
  logs,
  lastError,
  errorHint,
  logPlaceholder = "日志会显示在这里（提取 / 规范 / 校验 / 导出）。",
  onReset,
}: RunFeedbackProps) {
  const logRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (logRef.current) logRef.current.scrollTop = logRef.current.scrollHeight;
  }, [logs]);

  return (
    <>
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

      {lastError && errorHint && (
        <p className="mt-2 rounded-lg border border-amber-200 bg-amber-50 px-3 py-2 text-sm text-amber-800">
          {errorHint}
        </p>
      )}

      <div
        ref={logRef}
        className="mt-4 h-64 overflow-auto rounded-lg bg-slate-950 p-3 font-mono text-xs leading-relaxed text-slate-200"
      >
        {logs.length === 0 ? (
          <p className="text-slate-500">{logPlaceholder}</p>
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
          onClick={onReset}
          className="mt-3 inline-flex items-center gap-1 text-xs text-slate-500 hover:text-slate-700"
        >
          <RotateCcw className="h-3 w-3" /> 清空
        </button>
      )}
    </>
  );
}

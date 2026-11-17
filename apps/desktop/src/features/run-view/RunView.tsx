import { useEffect, useRef } from "react";
import { Loader2, Play, RotateCcw } from "lucide-react";
import { engineCall } from "../../lib/rpc";
import { useRunStore } from "../../stores/runStore";

interface RunViewProps {
  paths: string[];
  engineReady: boolean;
}

export function RunView({ paths, engineReady }: RunViewProps) {
  const { runId, status, progress, logs, lastError, begin, reset } = useRunStore();
  const logRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (logRef.current) logRef.current.scrollTop = logRef.current.scrollHeight;
  }, [logs]);

  const start = async () => {
    reset();
    try {
      const result = await engineCall<{ job_id: string; run_id: string }>("pipeline.run", {
        inputs: paths,
      });
      begin(result.run_id);
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
          <h2 className="text-base font-semibold text-slate-800">运行示例</h2>
          <p className="text-sm text-slate-500">
            M0 冒烟流水线：只演示进度事件，不修改任何文件。
          </p>
        </div>
        <button
          type="button"
          onClick={start}
          disabled={!engineReady || running}
          className="inline-flex items-center gap-2 rounded-lg bg-slate-900 px-4 py-2 text-sm font-medium text-white hover:bg-slate-800 disabled:cursor-not-allowed disabled:bg-slate-300"
        >
          {running ? <Loader2 className="h-4 w-4 animate-spin" /> : <Play className="h-4 w-4" />}
          {running ? "运行中…" : "运行示例"}
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
              status === "failed" ? "bg-red-500" : status === "done" ? "bg-emerald-500" : "bg-sky-500"
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
        className="mt-4 h-56 overflow-auto rounded-lg bg-slate-950 p-3 font-mono text-xs leading-relaxed text-slate-200"
      >
        {logs.length === 0 ? (
          <p className="text-slate-500">日志会显示在这里（0 → 100% 进度）。</p>
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
  );
}

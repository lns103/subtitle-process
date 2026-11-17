import { useCallback, useEffect, useState } from "react";
import { RefreshCw, Server } from "lucide-react";
import { DropZone } from "./features/dropzone/DropZone";
import { RunView } from "./features/run-view/RunView";
import { onEngineEvent, onEngineStatus } from "./lib/events";
import type { Project } from "./lib/models";
import { getEngineStatus, restartEngine, type EngineStatus } from "./lib/rpc";
import { useProjectStore } from "./stores/projectStore";
import { useRunStore } from "./stores/runStore";

function statusLabel(status: EngineStatus): { text: string; tone: string } {
  switch (status.state) {
    case "ready":
      return {
        text: `引擎就绪 · v${status.version} · Python ${status.python}`,
        tone: "bg-emerald-50 text-emerald-700 border-emerald-200",
      };
    case "starting":
      return { text: "引擎启动中…", tone: "bg-amber-50 text-amber-700 border-amber-200" };
    case "failed":
      return { text: `引擎不可用：${status.message}`, tone: "bg-red-50 text-red-700 border-red-200" };
    default:
      return { text: "引擎已停止", tone: "bg-slate-50 text-slate-600 border-slate-200" };
  }
}

export default function App() {
  const [status, setStatus] = useState<EngineStatus>({ state: "starting" });
  const [paths, setPaths] = useState<string[]>([]);

  useEffect(() => {
    let disposed = false;
    const cleanups: Array<() => void> = [];

    void getEngineStatus().then((value) => {
      if (!disposed) setStatus(value);
    });
    void onEngineStatus((value) => setStatus(value)).then((fn) => {
      if (disposed) fn();
      else cleanups.push(fn);
    });
    void onEngineEvent((event) => {
      useRunStore.getState().applyEvent(event);
      if (event.type === "project.updated" && event.project) {
        useProjectStore.getState().applyUpdate(event.project as Project);
      }
    }).then((fn) => {
      if (disposed) fn();
      else cleanups.push(fn);
    });

    void useProjectStore.getState().refresh();

    return () => {
      disposed = true;
      cleanups.forEach((fn) => fn());
    };
  }, []);

  const addPaths = useCallback((incoming: string[]) => setPaths(incoming), []);
  const badge = statusLabel(status);

  return (
    <div className="min-h-screen bg-slate-100 px-5 py-6 text-slate-900">
      <div className="mx-auto max-w-4xl space-y-5">
        <header className="flex flex-wrap items-center justify-between gap-3">
          <div>
            <h1 className="text-2xl font-semibold tracking-tight">字幕工具箱 · Pipeline v2</h1>
            <p className="text-sm text-slate-500">拖入媒体 → 运行 → 查看结构化进度</p>
          </div>
          <div className="flex items-center gap-2">
            <span className={`inline-flex max-w-md items-center gap-2 rounded-full border px-3 py-1.5 text-xs ${badge.tone}`}>
              <Server className="h-3.5 w-3.5 shrink-0" />
              <span className="truncate">{badge.text}</span>
            </span>
            <button
              type="button"
              title="重启引擎"
              onClick={() => void restartEngine().catch((error) => setStatus({ state: "failed", message: String(error) }))}
              className="rounded-full border border-slate-300 bg-white p-2 text-slate-600 hover:bg-slate-50"
            >
              <RefreshCw className="h-4 w-4" />
            </button>
          </div>
        </header>

        <DropZone onPaths={addPaths} />
        <RunView paths={paths} engineReady={status.state === "ready"} />
      </div>
    </div>
  );
}

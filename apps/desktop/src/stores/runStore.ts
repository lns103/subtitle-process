import { create } from "zustand";
import type { EngineEvent } from "../lib/events";

export interface RunLogEntry {
  key: string;
  seq: number;
  type: string;
  message: string;
  level: "info" | "warning" | "error";
  ts: string;
}

interface RunState {
  runId: string | null;
  projectId: string | null;
  status: "idle" | "running" | "done" | "failed" | "cancelled";
  progress: number;
  logs: RunLogEntry[];
  lastError: string | null;
  begin: (runId: string, projectId?: string | null) => void;
  applyEvent: (event: EngineEvent) => void;
  reset: () => void;
}

const MAX_LOGS = 300;

function describe(event: EngineEvent): { message: string; level: RunLogEntry["level"] } {
  switch (event.type) {
    case "run.started":
      return { message: `开始运行配方 ${String(event.recipe_id ?? "")}`, level: "info" };
    case "step.started":
      return { message: `步骤 ${event.step ?? ""} 开始`, level: "info" };
    case "step.progress":
      return {
        message: event.message ?? `进度 ${Math.round((event.percent ?? 0) * 100)}%`,
        level: "info",
      };
    case "step.log":
      return {
        message: event.message ?? "",
        level: event.level === "error" ? "error" : event.level === "warning" ? "warning" : "info",
      };
    case "step.failed":
      return {
        message: `步骤 ${event.step ?? ""} 失败：${event.error?.message ?? "未知错误"}`,
        level: "error",
      };
    case "run.finished":
      return { message: `运行结束：${event.status ?? "unknown"}`, level: event.status === "failed" ? "error" : "info" };
    default:
      return { message: event.type, level: "info" };
  }
}

export const useRunStore = create<RunState>((set) => ({
  runId: null,
  projectId: null,
  status: "idle",
  progress: 0,
  logs: [],
  lastError: null,

  begin: (runId, projectId = null) =>
    set({ runId, projectId, status: "running", progress: 0, logs: [], lastError: null }),

  applyEvent: (event) =>
    set((state) => {
      // 只处理当前 run 的事件，避免旧 run 的迟到事件覆盖进度。
      if (state.runId && event.run_id && event.run_id !== state.runId) return state;
      if (event.type === "project.updated") return state;
      const { message, level } = describe(event);
      const entry: RunLogEntry = {
        key: `${event.event_id}:${state.logs.length}`,
        seq: event.seq,
        type: event.type,
        message,
        level,
        ts: event.ts,
      };
      const logs = [...state.logs, entry].slice(-MAX_LOGS);

      if (event.type === "step.progress") {
        return { ...state, logs, progress: Math.min(Math.max(event.percent ?? 0, 0), 1) };
      }
      if (event.type === "run.finished") {
        const status =
          event.status === "done"
            ? "done"
            : event.status === "cancelled"
              ? "cancelled"
              : "failed";
        return {
          ...state,
          logs,
          status,
          progress: status === "done" ? 1 : state.progress,
          lastError: status === "failed" ? (event.error?.message ?? "运行失败") : state.lastError,
        };
      }
      if (event.type === "step.failed") {
        return { ...state, logs, lastError: event.error?.message ?? "步骤失败" };
      }
      return { ...state, logs };
    }),

  reset: () => set({ runId: null, projectId: null, status: "idle", progress: 0, logs: [], lastError: null }),
}));

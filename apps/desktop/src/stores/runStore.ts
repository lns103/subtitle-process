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
  status: "idle" | "running" | "waiting_review" | "done" | "failed" | "cancelled";
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
    case "review.requested": {
      const count = Array.isArray(event.items) ? event.items.length : 0;
      return {
        message: `等待人工审核：${event.step ?? "human.review"} · ${count} 项`,
        level: "info",
      };
    }
    case "review.resolved":
      return {
        message: `审核已提交：${event.review_id ? String(event.review_id) : (event.step ?? "human.review")}`,
        level: "info",
      };
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
    set((state) =>
      // pipeline.run 的响应与首批事件可能乱序：若事件已先行绑定同一个
      // run_id，不要重置已收到的状态（尤其是 waiting_review）。
      state.runId === runId
        ? { ...state, projectId: projectId ?? state.projectId }
        : { runId, projectId, status: "running", progress: 0, logs: [], lastError: null },
    ),

  applyEvent: (event) =>
    set((state) => {
      // 只处理当前 run 的事件，避免旧 run 的迟到事件覆盖进度。
      if (state.runId && event.run_id && event.run_id !== state.runId) return state;
      if (event.type === "project.updated") return state;
      // 事件可能早于 pipeline.run 响应到达：先绑定 run_id，begin() 再补齐状态。
      const activeRunId = state.runId ?? event.run_id ?? null;
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
        return {
          ...state,
          runId: activeRunId,
          logs,
          progress: Math.min(Math.max(event.percent ?? 0, 0), 1),
        };
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
          runId: activeRunId,
          logs,
          status,
          progress: status === "done" ? 1 : state.progress,
          lastError: status === "failed" ? (event.error?.message ?? "运行失败") : state.lastError,
        };
      }
      if (event.type === "step.failed") {
        return {
          ...state,
          runId: activeRunId,
          logs,
          lastError: event.error?.message ?? "步骤失败",
        };
      }
      if (event.type === "review.requested") {
        return { ...state, runId: activeRunId, logs, status: "waiting_review" };
      }
      if (event.type === "review.resolved") {
        return {
          ...state,
          runId: activeRunId,
          logs,
          status: state.status === "waiting_review" ? "running" : state.status,
        };
      }
      return { ...state, runId: activeRunId, logs };
    }),

  reset: () => set({ runId: null, projectId: null, status: "idle", progress: 0, logs: [], lastError: null }),
}));

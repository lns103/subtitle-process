import { listen, type UnlistenFn } from "@tauri-apps/api/event";
import type { EngineStatus } from "./rpc";

/** 引擎事件（PROTOCOL.md 第 7 节）；未知字段必须忽略。 */
export interface EngineEvent {
  event_id: string;
  run_id?: string | null;
  project_id?: string | null;
  seq: number;
  type: string;
  ts: string;
  step?: string;
  percent?: number;
  message?: string;
  level?: string;
  status?: string;
  duration_ms?: number;
  error?: { code: number; message: string; data?: unknown };
  [key: string]: unknown;
}

export function onEngineEvent(handler: (event: EngineEvent) => void): Promise<UnlistenFn> {
  return listen<EngineEvent>("engine:event", (event) => handler(event.payload));
}

export function onEngineLog(handler: (line: string) => void): Promise<UnlistenFn> {
  return listen<{ line: string; level: string }>("engine:log", (event) => handler(event.payload.line));
}

export function onEngineStatus(handler: (status: EngineStatus) => void): Promise<UnlistenFn> {
  return listen<EngineStatus>("engine:status", (event) => handler(event.payload));
}

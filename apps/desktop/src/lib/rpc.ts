import { invoke } from "@tauri-apps/api/core";

/** 引擎错误对象（PROTOCOL.md 第 5 节）。 */
export interface RpcErrorPayload {
  code: number;
  message: string;
  data?: unknown;
}

/** 可直接映射到提示文案的错误类型。 */
export class EngineError extends Error {
  readonly code: number;
  readonly data?: unknown;

  constructor(payload: RpcErrorPayload) {
    super(payload.message);
    this.name = "EngineError";
    this.code = payload.code;
    this.data = payload.data;
  }
}

function toEngineError(error: unknown): EngineError {
  if (error instanceof EngineError) return error;
  if (typeof error === "object" && error !== null && "code" in error && "message" in error) {
    const payload = error as RpcErrorPayload;
    return new EngineError({ code: payload.code, message: String(payload.message), data: payload.data });
  }
  return new EngineError({ code: -32603, message: String(error) });
}

/**
 * 泛型引擎调用：所有 JSON-RPC 方法都走 Tauri 的 `engine_call`。
 * `pipeline.run` 立即返回，不等待流水线结束。
 */
export async function engineCall<T>(
  method: string,
  params: Record<string, unknown> = {},
  timeoutMs?: number,
): Promise<T> {
  try {
    return await invoke<T>("engine_call", { method, params, timeoutMs });
  } catch (error) {
    throw toEngineError(error);
  }
}

export type EngineStatus =
  | { state: "starting" }
  | { state: "ready"; version: string; protocol: number; python: string }
  | { state: "failed"; message: string }
  | { state: "stopped" };

export async function getEngineStatus(): Promise<EngineStatus> {
  try {
    return await invoke<EngineStatus>("engine_status");
  } catch (error) {
    return { state: "failed", message: String(error) };
  }
}

export async function restartEngine(): Promise<void> {
  try {
    await invoke("engine_restart");
  } catch (error) {
    throw toEngineError(error);
  }
}

export async function pickFiles(): Promise<string[]> {
  return invoke<string[]>("pick_files");
}

export async function pickFolder(): Promise<string | null> {
  return invoke<string | null>("pick_folder");
}

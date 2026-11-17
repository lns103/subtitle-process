import type { Edge, Node } from "@xyflow/react";
import type { StepSpecPort } from "./models";

/**
 * 画布节点数据。只保存**配方语义**，展示用的校验徽标由画布在渲染时注入，
 * 避免把临时 UI 状态写进撤销历史。
 */
export interface EditorNodeData extends Record<string, unknown> {
  uses: string;
  title: string;
  options: Record<string, unknown>;
  when: string | null;
}

export type EditorNode = Node<EditorNodeData, "step">;

/** 边的 id 编码端口，便于从配方还原时稳定复用。 */
export interface EditorEdgeData extends Record<string, unknown> {
  kind?: string;
}

export type EditorEdge = Edge<EditorEdgeData>;

/** 画布展示层的节点数据：在语义数据上附加校验徽标与端口定义。 */
export interface DisplayNodeData extends EditorNodeData {
  inputs: Record<string, StepSpecPort>;
  outputs: Record<string, StepSpecPort>;
  requiresAgent: boolean;
  errorCount: number;
  warningCount: number;
}

export type DisplayNode = Node<DisplayNodeData, "step">;

export function edgeId(
  source: string,
  sourceHandle: string | null | undefined,
  target: string,
  targetHandle: string | null | undefined,
): string {
  return `${source}:${sourceHandle ?? "out"}->${target}:${targetHandle ?? "in"}`;
}

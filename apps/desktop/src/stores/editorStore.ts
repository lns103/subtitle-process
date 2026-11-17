import { create } from "zustand";
import { temporal } from "zundo";
import {
  applyEdgeChanges,
  applyNodeChanges,
  type Connection,
  type EdgeChange,
  type NodeChange,
} from "@xyflow/react";
import type { EditorEdge, EditorNode, EditorNodeData } from "../lib/editorTypes";
import { edgeId } from "../lib/editorTypes";
import {
  connectionIssue,
  defaultStepOptions,
  nodesAndEdgesFromRecipe,
  recipeFromGraph,
  uniqueStepId,
} from "../lib/recipeGraph";
import type {
  RecipeDefinition,
  RecipeInput,
  StepSpec,
  ValidationIssue,
} from "../lib/models";

export interface EditorMeta {
  recipeId: string;
  name: string;
  version: number;
  description: string;
  inputs: RecipeInput[];
  ui: Record<string, unknown>;
}

export interface SnapshotNode {
  id: string;
  type: "step";
  position: { x: number; y: number };
  data: EditorNodeData;
}

export interface SnapshotEdge {
  id: string;
  source: string;
  target: string;
  sourceHandle: string | null;
  targetHandle: string | null;
}

/** 参与撤销/重做的配方状态；选中态、校验结果等临时字段不进入历史。 */
export interface EditorSnapshot extends EditorMeta {
  nodes: SnapshotNode[];
  edges: SnapshotEdge[];
}

export type EditorSaveState = "idle" | "dirty" | "saving" | "saved";

export interface EditorState extends EditorMeta {
  builtin: boolean;
  specs: StepSpec[];
  nodes: EditorNode[];
  edges: EditorEdge[];
  selection: string[];
  issues: ValidationIssue[];
  validationOk: boolean | null;
  saveState: EditorSaveState;
  lastError: string | null;
  savedAt: string | null;
  /** 打开/保存时的快照 JSON，用于判断是否有未保存修改。 */
  baseline: string;
}

export interface EditorActions {
  loadRecipe: (recipe: RecipeDefinition, specs: StepSpec[]) => void;
  newRecipe: (specs: StepSpec[], name?: string) => void;
  setMeta: (patch: Partial<EditorMeta>) => void;
  addStep: (spec: StepSpec, position: { x: number; y: number }) => string;
  removeNodes: (ids: string[]) => void;
  updateNode: (id: string, patch: Partial<Pick<EditorNodeData, "options" | "when">>) => void;
  connect: (connection: Connection) => string | null;
  applyNodes: (changes: NodeChange<EditorNode>[]) => void;
  applyEdges: (changes: EdgeChange<EditorEdge>[]) => void;
  moveNode: (id: string, position: { x: number; y: number }) => void;
  replaceNodes: (nodes: EditorNode[]) => void;
  setSelection: (ids: string[]) => void;
  setIssues: (issues: ValidationIssue[], ok: boolean | null) => void;
  clearIssues: () => void;
  setSaveState: (state: EditorSaveState, error?: string | null) => void;
  markSaved: (saved?: RecipeDefinition) => void;
  toRecipe: () => { recipe: RecipeDefinition; cycle: string[] | null };
}

export type EditorStore = EditorState & EditorActions;

export function snapshotOf(state: EditorState): EditorSnapshot {
  return {
    recipeId: state.recipeId,
    name: state.name,
    version: state.version,
    description: state.description,
    inputs: state.inputs,
    ui: state.ui,
    nodes: state.nodes.map((node) => ({
      id: node.id,
      type: "step" as const,
      position: { x: Math.round(node.position.x), y: Math.round(node.position.y) },
      data: {
        uses: node.data.uses,
        title: node.data.title,
        options: node.data.options,
        when: node.data.when,
      },
    })),
    edges: state.edges.map((edge) => ({
      id: edge.id,
      source: edge.source,
      target: edge.target,
      sourceHandle: edge.sourceHandle ?? null,
      targetHandle: edge.targetHandle ?? null,
    })),
  };
}

export function serializeSnapshot(state: EditorState): string {
  return JSON.stringify(snapshotOf(state));
}

export function isEditorDirty(state: EditorState): boolean {
  return serializeSnapshot(state) !== state.baseline;
}

function blankMeta(name = "未命名配方"): EditorMeta {
  return {
    recipeId: "untitled",
    name,
    version: 1,
    description: "",
    inputs: [
      { name: "video", kind: "file", accept: [".mkv", ".mp4", ".mov", ".avi", ".ts"], required: true },
    ],
    ui: {},
  };
}

function initialSnapshot(meta: EditorMeta): EditorSnapshot {
  return { ...meta, nodes: [], edges: [] };
}

function buildRecipe(
  state: EditorStore,
  nodes: EditorNode[],
  edges: EditorEdge[],
): { recipe: RecipeDefinition; cycle: string[] | null } {
  const meta = {
    id: state.recipeId,
    name: state.name,
    version: state.version,
    description: state.description,
    inputs: state.inputs,
    ui: state.ui,
  };
  return recipeFromGraph(meta, nodes, edges, state.specs);
}

const meta = blankMeta();

export const useEditorStore = create<EditorStore>()(
  temporal(
    (set, get) => ({
      ...initialSnapshot(meta),
      builtin: false,
      specs: [],
      selection: [],
      issues: [],
      validationOk: null,
      saveState: "idle",
      lastError: null,
      savedAt: null,
      baseline: JSON.stringify(initialSnapshot(meta)),

      loadRecipe: (recipe, specs) => {
        const { nodes, edges } = nodesAndEdgesFromRecipe(recipe, specs);
        const nextMeta: EditorMeta = {
          recipeId: recipe.id,
          name: recipe.name,
          version: recipe.version,
          description: recipe.description,
          inputs: recipe.inputs,
          ui: recipe.ui ?? {},
        };
        const snapshot: EditorSnapshot = { ...nextMeta, nodes: nodes.map(snapshotNode), edges: edges.map(snapshotEdge) };
        set({
          ...nextMeta,
          builtin: recipe.builtin,
          specs,
          nodes,
          edges,
          selection: [],
          issues: [],
          validationOk: null,
          saveState: "saved",
          lastError: null,
          savedAt: null,
          baseline: JSON.stringify(snapshot),
        });
        useEditorStore.temporal.getState().clear();
      },

      newRecipe: (specs, name) => {
        const nextMeta = blankMeta(name);
        const snapshot = initialSnapshot(nextMeta);
        set({
          ...nextMeta,
          builtin: false,
          specs,
          nodes: [],
          edges: [],
          selection: [],
          issues: [],
          validationOk: null,
          saveState: "dirty",
          lastError: null,
          savedAt: null,
          baseline: JSON.stringify(snapshot),
        });
        useEditorStore.temporal.getState().clear();
      },

      setMeta: (patch) =>
        set((state) => ({ ...patch, saveState: state.saveState === "saving" ? state.saveState : "dirty" })),

      addStep: (spec, position) => {
        const state = get();
        const id = uniqueStepId(spec.id, state.nodes.map((node) => node.id));
        const node: EditorNode = {
          id,
          type: "step",
          position,
          data: {
            uses: spec.id,
            title: spec.title,
            options: defaultStepOptions(spec),
            when: null,
          },
        };
        set({ nodes: [...state.nodes, node], selection: [id], saveState: "dirty", issues: [], validationOk: null });
        return id;
      },

      removeNodes: (ids) => {
        const remove = new Set(ids);
        if (remove.size === 0) return;
        set((state) => ({
          nodes: state.nodes.filter((node) => !remove.has(node.id)),
          edges: state.edges.filter((edge) => !remove.has(edge.source) && !remove.has(edge.target)),
          selection: state.selection.filter((id) => !remove.has(id)),
          issues: [],
          validationOk: null,
          saveState: "dirty",
        }));
      },

      updateNode: (id, patch) => {
        set((state) => ({
          nodes: state.nodes.map((node) =>
            node.id === id
              ? { ...node, data: { ...node.data, ...patch } }
              : node,
          ),
          issues: [],
          validationOk: null,
          saveState: "dirty",
        }));
      },

      connect: (connection) => {
        const state = get();
        if (!connection.source || !connection.target) return "连线缺少起点或终点";
        if (connection.source === connection.target) return "不能连接节点自身";
        const specsById: Record<string, StepSpec> = {};
        for (const node of state.nodes) {
          const spec = state.specs.find((item) => item.id === node.data.uses);
          if (spec) specsById[node.id] = spec;
        }
        if (!state.nodes.some((node) => node.id === connection.source) ||
            !state.nodes.some((node) => node.id === connection.target)) {
          return "节点不存在";
        }
        // 端口名在画布上保存为 handle id。
        const issue = connectionIssue(
          {
            source: connection.source,
            target: connection.target,
            sourceHandle: connection.sourceHandle,
            targetHandle: connection.targetHandle,
          },
          specsById,
        );
        if (issue) return issue;
        const id = edgeId(connection.source, connection.sourceHandle, connection.target, connection.targetHandle);
        if (state.edges.some((edge) => edge.id === id)) return "这条连线已经存在";
        const sourceSpec = specsById[connection.source];
        const edge: EditorEdge = {
          id,
          source: connection.source,
          target: connection.target,
          sourceHandle: connection.sourceHandle ?? null,
          targetHandle: connection.targetHandle ?? null,
          data: {
            kind: connection.sourceHandle
              ? sourceSpec?.outputs[connection.sourceHandle]?.kind
              : undefined,
          },
        };
        set({ edges: [...state.edges, edge], issues: [], validationOk: null, saveState: "dirty" });
        return null;
      },

      applyNodes: (changes) => {
        set((state) => {
          const nodes = applyNodeChanges(changes, state.nodes);
          const removed = new Set(
            changes.filter((change) => change.type === "remove").map((change) => change.id),
          );
          const edges =
            removed.size > 0
              ? state.edges.filter((edge) => !removed.has(edge.source) && !removed.has(edge.target))
              : state.edges;
          const selection = nodes.filter((node) => node.selected).map((node) => node.id);
          const structural = changes.some((change) => change.type === "remove");
          return {
            nodes,
            edges,
            selection,
            ...(structural ? { issues: [], validationOk: null, saveState: "dirty" as const } : {}),
          };
        });
      },

      applyEdges: (changes) => {
        set((state) => {
          const edges = applyEdgeChanges(changes, state.edges);
          const structural = changes.some(
            (change) => change.type === "remove" || change.type === "add",
          );
          return structural
            ? { edges, issues: [], validationOk: null, saveState: "dirty" as const }
            : { edges };
        });
      },

      moveNode: (id, position) => {
        set((state) => ({
          nodes: state.nodes.map((node) => (node.id === id ? { ...node, position } : node)),
          saveState: "dirty",
        }));
      },

      replaceNodes: (nodes) =>
        set({
          nodes,
          issues: [],
          validationOk: null,
          saveState: "dirty",
        }),

      setSelection: (ids) => set({ selection: ids }),
      setIssues: (issues, ok) =>
        set({
          issues,
          validationOk: ok,
          saveState: ok === false ? "dirty" : get().saveState,
        }),
      clearIssues: () => set({ issues: [], validationOk: null }),
      setSaveState: (saveState, lastError = null) => set({ saveState, lastError }),
      markSaved: (saved) => {
        const state = get();
        const nextMeta: Partial<EditorMeta> = saved
          ? {
              recipeId: saved.id,
              name: saved.name,
              description: saved.description,
              version: saved.version,
              inputs: saved.inputs,
              ui: saved.ui,
            }
          : {};
        const next: EditorState = { ...state, ...nextMeta };
        set({
          ...nextMeta,
          builtin: saved ? saved.builtin : state.builtin,
          baseline: serializeSnapshot(next),
          saveState: "saved",
          lastError: null,
          savedAt: new Date().toISOString(),
        });
      },

      toRecipe: () => buildRecipe(get(), get().nodes, get().edges),
    }),
    {
      limit: 80,
      partialize: (state) => snapshotOf(state),
      equality: (past, current) => JSON.stringify(past) === JSON.stringify(current),
    },
  ),
);

function snapshotNode(node: EditorNode): SnapshotNode {
  return {
    id: node.id,
    type: "step",
    position: { x: Math.round(node.position.x), y: Math.round(node.position.y) },
    data: {
      uses: node.data.uses,
      title: node.data.title,
      options: node.data.options,
      when: node.data.when,
    },
  };
}

function snapshotEdge(edge: EditorEdge): SnapshotEdge {
  return {
    id: edge.id,
    source: edge.source,
    target: edge.target,
    sourceHandle: edge.sourceHandle ?? null,
    targetHandle: edge.targetHandle ?? null,
  };
}

export function useEditorTemporal() {
  return useEditorStore.temporal;
}

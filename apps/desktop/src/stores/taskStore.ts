import { create } from "zustand";
import { listTasks } from "../lib/api";
import { routePaths, type RoutingResult } from "../lib/inputRouting";
import type { TaskSpec } from "../lib/models";
import { findBilingualTask, sortTasks } from "../lib/tasks";

export type TrackMode = "auto" | "manual";

export interface TrackSelection {
  mode: TrackMode;
  /** 显式字幕流索引；auto 模式下忽略。 */
  indices: number[];
}

interface TaskState {
  tasks: TaskSpec[];
  loading: boolean;
  error: string | null;
  selectedTaskId: string | null;
  /** taskId -> inputName -> 路径列表。 */
  slots: Record<string, Record<string, string[]>>;
  /** taskId -> stepId -> 用户覆盖的步骤参数。 */
  options: Record<string, Record<string, Record<string, unknown>>>;
  /** taskId -> inputName -> 是否为自动填充。 */
  autofilled: Record<string, Record<string, boolean>>;
  /** taskId -> inputName -> 用户是否手动编辑过（自动填充不得覆盖）。 */
  touched: Record<string, Record<string, boolean>>;
  /** taskId -> 字幕轨道选择。 */
  tracks: Record<string, TrackSelection>;
  /** taskId -> 最近一次通用槽分发结果。 */
  lastRouting: Record<string, RoutingResult | null>;
  /** taskId -> 最近一次通用分发包含的文件夹；用于批量项目命名。 */
  routingDirectories: Record<string, string[]>;
  /** taskId -> 分发前的槽位快照，用于撤销。 */
  routeSnapshot: Record<string, Record<string, string[]> | null>;

  load: () => Promise<void>;
  selectTask: (taskId: string | null) => void;
  setSlot: (taskId: string, inputName: string, paths: string[]) => void;
  clearSlot: (taskId: string, inputName: string) => void;
  setStepOptions: (taskId: string, stepId: string, values: Record<string, unknown>) => void;
  setTrackSelection: (taskId: string, selection: TrackSelection) => void;
  /** 通用槽：按规则把文件/文件夹分发到输入槽。 */
  applyRouting: (taskId: string, paths: string[], overwrite?: boolean) => RoutingResult | null;
  /** 记录最近一次通用分发包含的文件夹。 */
  setRoutingDirectories: (taskId: string, directories: string[]) => void;
  /** 把某个已选文件从 fromInput 移到 toInput（拖动改槽）。 */
  moveSlotPath: (taskId: string, fromInput: string, toInput: string, path: string) => void;
  undoRouting: (taskId: string) => void;
  /** 把视频流程导出的干净 SRT 填入双语任务的 original；绝不覆盖用户手动填写的槽。 */
  autoFillOriginal: (paths: string[]) => void;
  reset: () => void;
}

const INITIAL = {
  tasks: [] as TaskSpec[],
  loading: false,
  error: null as string | null,
  selectedTaskId: null as string | null,
  slots: {} as Record<string, Record<string, string[]>>,
  options: {} as Record<string, Record<string, Record<string, unknown>>>,
  autofilled: {} as Record<string, Record<string, boolean>>,
  touched: {} as Record<string, Record<string, boolean>>,
  tracks: {} as Record<string, TrackSelection>,
  lastRouting: {} as Record<string, RoutingResult | null>,
  routingDirectories: {} as Record<string, string[]>,
  routeSnapshot: {} as Record<string, Record<string, string[]> | null>,
};

function unique(paths: string[]): string[] {
  return Array.from(new Set(paths.filter((path) => path.trim() !== "")));
}

function samePaths(left: string[], right: string[]): boolean {
  return left.length === right.length && left.every((path, index) => path === right[index]);
}

function originalInputName(task: TaskSpec): string | null {
  const input =
    task.inputs.find((item) => item.name === "original") ??
    task.inputs.find((item) => item.label?.trim() === "原版");
  return input?.name ?? null;
}

function errorMessage(error: unknown): string {
  return error instanceof Error ? error.message : String(error);
}

export const useTaskStore = create<TaskState>((set, get) => ({
  ...INITIAL,

  load: async () => {
    set({ loading: true, error: null });
    try {
      const tasks = sortTasks(await listTasks());
      const current = get().selectedTaskId;
      const selectedTaskId = tasks.some((task) => task.id === current)
        ? current
        : (tasks[0]?.id ?? null);
      set({ tasks, loading: false, error: null, selectedTaskId });
    } catch (error) {
      set({ loading: false, error: errorMessage(error) });
    }
  },

  selectTask: (taskId) => set({ selectedTaskId: taskId }),

  setSlot: (taskId, inputName, paths) =>
    set((state) => {
      const values = unique(paths);
      return {
        slots: {
          ...state.slots,
          [taskId]: { ...(state.slots[taskId] ?? {}), [inputName]: values },
        },
        touched: {
          ...state.touched,
          [taskId]: { ...(state.touched[taskId] ?? {}), [inputName]: true },
        },
        autofilled: {
          ...state.autofilled,
          [taskId]: { ...(state.autofilled[taskId] ?? {}), [inputName]: false },
        },
        lastRouting: { ...state.lastRouting, [taskId]: null },
        routingDirectories: { ...state.routingDirectories, [taskId]: [] },
        routeSnapshot: { ...state.routeSnapshot, [taskId]: null },
      };
    }),

  clearSlot: (taskId, inputName) =>
    set((state) => ({
      slots: {
        ...state.slots,
        [taskId]: { ...(state.slots[taskId] ?? {}), [inputName]: [] },
      },
      // 清空后允许未来的自动填充重新写入。
      touched: {
        ...state.touched,
        [taskId]: { ...(state.touched[taskId] ?? {}), [inputName]: false },
      },
      autofilled: {
        ...state.autofilled,
        [taskId]: { ...(state.autofilled[taskId] ?? {}), [inputName]: false },
      },
      lastRouting: { ...state.lastRouting, [taskId]: null },
      routingDirectories: { ...state.routingDirectories, [taskId]: [] },
      routeSnapshot: { ...state.routeSnapshot, [taskId]: null },
    })),

  setStepOptions: (taskId, stepId, values) =>
    set((state) => ({
      options: {
        ...state.options,
        [taskId]: { ...(state.options[taskId] ?? {}), [stepId]: values },
      },
    })),

  setTrackSelection: (taskId, selection) =>
    set((state) => ({
      tracks: {
        ...state.tracks,
        [taskId]: { mode: selection.mode, indices: uniqueIndices(selection.indices) },
      },
    })),

  applyRouting: (taskId, paths, overwrite = false) => {
    const state = get();
    const task = state.tasks.find((item) => item.id === taskId);
    if (!task) return null;
    const current = state.slots[taskId] ?? {};
    const result = routePaths(task, current, paths, { overwrite });
    const next = { ...current };
    const touched = { ...(state.touched[taskId] ?? {}) };
    const autofilled = { ...(state.autofilled[taskId] ?? {}) };
    for (const assignment of result.assigned) {
      next[assignment.input] = assignment.paths;
      touched[assignment.input] = true;
      autofilled[assignment.input] = false;
    }
    set({
      slots: { ...state.slots, [taskId]: next },
      touched: { ...state.touched, [taskId]: touched },
      autofilled: { ...state.autofilled, [taskId]: autofilled },
      lastRouting: { ...state.lastRouting, [taskId]: result },
      routeSnapshot: { ...state.routeSnapshot, [taskId]: current },
    });
    return result;
  },

  setRoutingDirectories: (taskId, directories) =>
    set((state) => ({
      routingDirectories: { ...state.routingDirectories, [taskId]: unique(directories) },
    })),

  undoRouting: (taskId) =>
    set((state) => {
      const snapshot = state.routeSnapshot[taskId];
      if (!snapshot) return state;
      return {
        slots: { ...state.slots, [taskId]: snapshot },
        lastRouting: { ...state.lastRouting, [taskId]: null },
        routingDirectories: { ...state.routingDirectories, [taskId]: [] },
        routeSnapshot: { ...state.routeSnapshot, [taskId]: null },
      };
    }),

  moveSlotPath: (taskId, fromInput, toInput, path) => {
    if (fromInput === toInput) return;
    const state = get();
    const task = state.tasks.find((item) => item.id === taskId);
    if (!task) return;
    const targetSpec = task.inputs.find((input) => input.name === toInput);
    if (!targetSpec) return;

    const current = state.slots[taskId] ?? {};
    const from = (current[fromInput] ?? []).filter((item) => item !== path);
    const targetCurrent = (current[toInput] ?? []).filter((item) => item !== path);
    const singleTarget = targetSpec.multiple !== true && targetSpec.kind !== "files";
    // 单文件槽已有内容时做交换，避免直接覆盖导致文件丢失。
    const displaced = singleTarget ? targetCurrent[0] : undefined;
    const fromNext = displaced ? [...from, displaced] : from;
    const targetNext = singleTarget ? [path] : [...targetCurrent, path];
    const next = { ...current, [fromInput]: fromNext, [toInput]: targetNext };

    const touched = {
      ...(state.touched[taskId] ?? {}),
      [fromInput]: true,
      [toInput]: true,
    };
    const autofilled = {
      ...(state.autofilled[taskId] ?? {}),
      [fromInput]: false,
      [toInput]: false,
    };

    const routing = state.lastRouting[taskId];
    let nextRouting: RoutingResult | null = routing;
    if (routing) {
      const assigned = task.inputs
        .map((input) => ({ input: input.name, paths: next[input.name] ?? [] }))
        .filter((assignment) => assignment.paths.length > 0);
      const assignedPaths = new Set(assigned.flatMap((assignment) => assignment.paths));
      nextRouting = {
        ...routing,
        assigned,
        ambiguous: routing.ambiguous.filter((item) => !assignedPaths.has(item)),
      };
    }

    set({
      slots: { ...state.slots, [taskId]: next },
      touched: { ...state.touched, [taskId]: touched },
      autofilled: { ...state.autofilled, [taskId]: autofilled },
      lastRouting: { ...state.lastRouting, [taskId]: nextRouting },
    });
  },

  autoFillOriginal: (paths) => {
    const values = unique(paths);
    if (values.length === 0) return;
    const state = get();
    const task = findBilingualTask(state.tasks);
    if (!task) return;
    const inputName = originalInputName(task);
    if (!inputName) return;

    const current = state.slots[task.id]?.[inputName] ?? [];
    if (state.touched[task.id]?.[inputName] && current.length > 0) return;
    if (samePaths(current, values)) return;

    set({
      slots: {
        ...state.slots,
        [task.id]: { ...(state.slots[task.id] ?? {}), [inputName]: values },
      },
      autofilled: {
        ...state.autofilled,
        [task.id]: { ...(state.autofilled[task.id] ?? {}), [inputName]: true },
      },
      lastRouting: { ...state.lastRouting, [task.id]: null },
      routingDirectories: { ...state.routingDirectories, [task.id]: [] },
      routeSnapshot: { ...state.routeSnapshot, [task.id]: null },
    });
  },

  reset: () => set({ ...INITIAL }),
}));

function uniqueIndices(indices: number[]): number[] {
  return Array.from(new Set(indices.filter((index) => Number.isInteger(index) && index >= 0))).sort(
    (left, right) => left - right,
  );
}

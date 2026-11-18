import { create } from "zustand";

/** 视频批量队列：顺序执行，跨页面保留进度（例如去审核页再回来）。 */

export type BatchItemStatus = "pending" | "running" | "waiting_review" | "done" | "failed";

export interface BatchItem {
  path: string;
  status: BatchItemStatus;
  projectId: string | null;
  runId: string | null;
  /** 当前项产出的文件路径。 */
  outputs: string[];
  error: string | null;
}

interface BatchState {
  taskId: string | null;
  items: BatchItem[];
  active: boolean;
  start: (taskId: string, paths: string[]) => void;
  update: (index: number, patch: Partial<BatchItem>) => void;
  finish: () => void;
  reset: () => void;
}

const INITIAL = {
  taskId: null as string | null,
  items: [] as BatchItem[],
  active: false,
};

export const useBatchStore = create<BatchState>((set) => ({
  ...INITIAL,

  start: (taskId, paths) =>
    set({
      taskId,
      active: true,
      items: paths.map((path) => ({
        path,
        status: "pending",
        projectId: null,
        runId: null,
        outputs: [],
        error: null,
      })),
    }),

  update: (index, patch) =>
    set((state) => ({
      items: state.items.map((item, itemIndex) =>
        itemIndex === index ? { ...item, ...patch } : item,
      ),
    })),

  finish: () => set({ active: false }),

  reset: () => set({ ...INITIAL }),
}));

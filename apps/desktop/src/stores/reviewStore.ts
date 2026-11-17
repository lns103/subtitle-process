import { create } from "zustand";
import { listReviews, submitReview, undoReview } from "../lib/api";
import type { ReviewDecision, ReviewItem, ReviewUndoResult } from "../lib/models";

export type DecisionValue = "accept" | "reject";

interface ReviewState {
  runId: string | null;
  items: ReviewItem[];
  decisions: Record<string, DecisionValue>;
  /** 用户改写后的文本；只在不同于引擎给出的 ``after`` 时提交。 */
  afterEdits: Record<string, string>;
  loading: boolean;
  submitting: boolean;
  undoing: boolean;
  submitted: boolean;
  undoResult: ReviewUndoResult | null;
  lastError: string | null;
  load: (runId: string) => Promise<void>;
  setDecision: (id: string, decision: DecisionValue) => void;
  clearDecision: (id: string) => void;
  setAfter: (id: string, value: string) => void;
  acceptHighConfidence: (threshold?: number) => void;
  rejectAll: () => void;
  submit: (runId?: string) => Promise<void>;
  undo: (runId?: string) => Promise<void>;
  reset: () => void;
}

const INITIAL = {
  runId: null,
  items: [] as ReviewItem[],
  decisions: {} as Record<string, DecisionValue>,
  afterEdits: {} as Record<string, string>,
  loading: false,
  submitting: false,
  undoing: false,
  submitted: false,
  undoResult: null as ReviewUndoResult | null,
  lastError: null as string | null,
};

function messageOf(error: unknown): string {
  return error instanceof Error ? error.message : String(error);
}

/**
 * 生成提交载荷：所有审核项都要发送，未决策的默认 ``reject``。
 * 只有用户实际改写了 ``after`` 时才附带该字段。
 */
export function buildReviewDecisions(
  items: ReviewItem[],
  decisions: Record<string, DecisionValue>,
  afterEdits: Record<string, string>,
): ReviewDecision[] {
  return items.map((item) => {
    const decision: ReviewDecision = {
      id: item.id,
      action: decisions[item.id] ?? "reject",
    };
    const edited = afterEdits[item.id];
    if (edited !== undefined && edited !== item.after) {
      decision.after = edited;
    }
    return decision;
  });
}

export const useReviewStore = create<ReviewState>((set, get) => ({
  ...INITIAL,

  load: async (runId) => {
    set({ ...INITIAL, runId, loading: true });
    try {
      const items = await listReviews(runId);
      const pending = items.some((item) => item.review_status === "pending");
      set({
        items,
        loading: false,
        submitted: items.length > 0 && !pending,
        lastError: null,
      });
    } catch (error) {
      set({ loading: false, lastError: messageOf(error) });
    }
  },

  setDecision: (id, decision) =>
    set((state) => ({ decisions: { ...state.decisions, [id]: decision } })),

  clearDecision: (id) =>
    set((state) => {
      const next = { ...state.decisions };
      delete next[id];
      return { decisions: next };
    }),

  setAfter: (id, value) =>
    set((state) => ({ afterEdits: { ...state.afterEdits, [id]: value } })),

  acceptHighConfidence: (threshold = 0.8) =>
    set((state) => {
      const decisions = { ...state.decisions };
      for (const item of state.items) {
        // 不覆盖用户已手动做出的决定。
        if (item.confidence >= threshold && !decisions[item.id]) {
          decisions[item.id] = "accept";
        }
      }
      return { decisions };
    }),

  rejectAll: () =>
    set((state) => ({
      decisions: Object.fromEntries(state.items.map((item) => [item.id, "reject" as const])),
    })),

  submit: async (runIdParam) => {
    if (get().submitting) return;
    const runId = runIdParam ?? get().runId;
    if (!runId) {
      set({ lastError: "缺少 run_id，无法提交审核" });
      return;
    }
    const { items, decisions, afterEdits } = get();
    if (items.length === 0) {
      set({ lastError: "没有可提交的审核项" });
      return;
    }
    set({ submitting: true, lastError: null });
    try {
      const payload = buildReviewDecisions(items, decisions, afterEdits);
      await submitReview(runId, payload);
      set((state) => ({
        submitting: false,
        submitted: true,
        undoResult: null,
        items: state.items.map((item) => ({
          ...item,
          review_status: "submitted" as const,
          status: state.decisions[item.id] === "accept" ? ("accepted" as const) : ("rejected" as const),
        })),
      }));
    } catch (error) {
      set({ submitting: false, lastError: messageOf(error) });
    }
  },

  undo: async (runIdParam) => {
    if (get().undoing) return;
    const runId = runIdParam ?? get().runId;
    if (!runId) {
      set({ lastError: "缺少 run_id，无法撤销审核" });
      return;
    }
    set({ undoing: true, lastError: null });
    try {
      const result = await undoReview(runId);
      // 撤销只生成恢复副本，不重新打开审核；继续保留 submitted 状态，
      // 避免前端误以为可以再次提交（引擎侧审核记录仍是 submitted）。
      set({ undoing: false, undoResult: result });
    } catch (error) {
      set({ undoing: false, lastError: messageOf(error) });
    }
  },

  reset: () => set({ ...INITIAL }),
}));

import { beforeEach, describe, expect, it, vi } from "vitest";
import { listReviews, submitReview, undoReview } from "../lib/api";
import type { ReviewItem } from "../lib/models";
import { buildReviewDecisions, useReviewStore } from "./reviewStore";

vi.mock("../lib/api", () => ({
  listReviews: vi.fn(),
  submitReview: vi.fn(),
  undoReview: vi.fn(),
}));

const listMock = vi.mocked(listReviews);
const submitMock = vi.mocked(submitReview);
const undoMock = vi.mocked(undoReview);

function item(overrides: Partial<ReviewItem> & { id: string }): ReviewItem {
  return {
    review_id: "rev_1",
    review_status: "pending",
    status: "pending",
    segment_index: 1,
    start_ms: 0,
    end_ms: 1000,
    before: "[door slams]",
    after: "",
    action: "remove",
    confidence: 0.5,
    reason: "bracketed sound effect",
    reasons: ["bracketed"],
    source: "rules",
    file: "ep01.srt",
    artifact_hash: "abc",
    ...overrides,
  };
}

const ITEMS: ReviewItem[] = [
  item({ id: "a", segment_index: 1, confidence: 0.93 }),
  item({ id: "b", segment_index: 2, confidence: 0.65, before: "♪ music", after: "music" }),
  item({ id: "c", segment_index: 3, confidence: 0.4, action: "keep", before: "hello", after: "hello" }),
];

describe("reviewStore", () => {
  beforeEach(() => {
    listMock.mockReset();
    submitMock.mockReset();
    undoMock.mockReset();
    useReviewStore.getState().reset();
  });

  it("加载审核项并记录 run_id", async () => {
    listMock.mockResolvedValue(ITEMS);

    await useReviewStore.getState().load("run_01");

    const state = useReviewStore.getState();
    expect(listMock).toHaveBeenCalledWith("run_01");
    expect(state.runId).toBe("run_01");
    expect(state.items).toHaveLength(3);
    expect(state.loading).toBe(false);
    expect(state.lastError).toBeNull();
    expect(state.submitted).toBe(false);
  });

  it("加载失败时记录错误", async () => {
    listMock.mockRejectedValue(new Error("engine offline"));

    await useReviewStore.getState().load("run_01");

    expect(useReviewStore.getState().lastError).toContain("engine offline");
  });

  it("记录单条决策", async () => {
    listMock.mockResolvedValue(ITEMS);
    await useReviewStore.getState().load("run_01");

    useReviewStore.getState().setDecision("a", "accept");
    useReviewStore.getState().setDecision("b", "reject");

    expect(useReviewStore.getState().decisions).toEqual({ a: "accept", b: "reject" });

    useReviewStore.getState().clearDecision("a");
    expect(useReviewStore.getState().decisions).toEqual({ b: "reject" });
  });

  it("批量接受高置信度且不覆盖已有决策", async () => {
    listMock.mockResolvedValue(ITEMS);
    await useReviewStore.getState().load("run_01");

    useReviewStore.getState().setDecision("a", "reject");
    useReviewStore.getState().acceptHighConfidence(0.8);

    expect(useReviewStore.getState().decisions).toEqual({ a: "reject" });
  });

  it("按阈值批量接受", async () => {
    listMock.mockResolvedValue([
      item({ id: "high", confidence: 0.9 }),
      item({ id: "mid", confidence: 0.7 }),
    ]);
    await useReviewStore.getState().load("run_01");

    useReviewStore.getState().acceptHighConfidence(); // 默认 0.8
    expect(useReviewStore.getState().decisions).toEqual({ high: "accept" });
  });

  it("全部拒绝", async () => {
    listMock.mockResolvedValue(ITEMS);
    await useReviewStore.getState().load("run_01");

    useReviewStore.getState().rejectAll();

    expect(useReviewStore.getState().decisions).toEqual({
      a: "reject",
      b: "reject",
      c: "reject",
    });
  });

  it("提交时发送所有项，未决策默认拒绝，改写附带 after", async () => {
    listMock.mockResolvedValue(ITEMS);
    submitMock.mockResolvedValue("ok");
    await useReviewStore.getState().load("run_01");

    useReviewStore.getState().setDecision("a", "accept");
    useReviewStore.getState().setAfter("b", "♪ music");

    await useReviewStore.getState().submit("run_01");

    expect(submitMock).toHaveBeenCalledTimes(1);
    expect(submitMock).toHaveBeenCalledWith("run_01", [
      { id: "a", action: "accept" },
      { id: "b", action: "reject", after: "♪ music" },
      { id: "c", action: "reject" },
    ]);

    const state = useReviewStore.getState();
    expect(state.submitted).toBe(true);
    expect(state.submitting).toBe(false);
    expect(state.items.map((entry) => entry.status)).toEqual([
      "accepted",
      "rejected",
      "rejected",
    ]);
    expect(state.items.every((entry) => entry.review_status === "submitted")).toBe(true);
  });

  it("after 与原始值相同时不附带", async () => {
    listMock.mockResolvedValue(ITEMS);
    submitMock.mockResolvedValue("ok");
    await useReviewStore.getState().load("run_01");

    useReviewStore.getState().setAfter("b", ITEMS[1]!.after);
    await useReviewStore.getState().submit();

    const payload = submitMock.mock.calls[0]?.[1] ?? [];
    expect(payload.find((entry) => entry.id === "b")).toEqual({ id: "b", action: "reject" });
  });

  it("提交失败时保留状态并记录错误", async () => {
    listMock.mockResolvedValue(ITEMS);
    submitMock.mockRejectedValue(new Error("1004 busy"));
    await useReviewStore.getState().load("run_01");

    await useReviewStore.getState().submit("run_01");

    const state = useReviewStore.getState();
    expect(state.submitted).toBe(false);
    expect(state.submitting).toBe(false);
    expect(state.lastError).toContain("1004");
  });

  it("撤销审核并保存恢复结果", async () => {
    listMock.mockResolvedValue(ITEMS);
    submitMock.mockResolvedValue("ok");
    undoMock.mockResolvedValue({
      review_id: "rev_1",
      audit_path: "reviews/audit-run_01.jsonl",
      restored: [{ path: "clean/ep01.clean.srt", hash: "deadbeef" }],
    });
    await useReviewStore.getState().load("run_01");
    useReviewStore.getState().setDecision("a", "accept");
    await useReviewStore.getState().submit("run_01");

    await useReviewStore.getState().undo("run_01");

    expect(undoMock).toHaveBeenCalledWith("run_01");
    const state = useReviewStore.getState();
    // 撤销只生成恢复副本，不重新打开审核。
    expect(state.submitted).toBe(true);
    expect(state.undoResult?.audit_path).toBe("reviews/audit-run_01.jsonl");
    expect(state.items.map((entry) => entry.status)).toEqual([
      "accepted",
      "rejected",
      "rejected",
    ]);
  });

  it("buildReviewDecisions 只包含已改写项", () => {
    const payload = buildReviewDecisions(
      ITEMS,
      { a: "accept" },
      { b: "changed", c: "hello" },
    );

    expect(payload).toEqual([
      { id: "a", action: "accept" },
      { id: "b", action: "reject", after: "changed" },
      { id: "c", action: "reject" },
    ]);
  });
});

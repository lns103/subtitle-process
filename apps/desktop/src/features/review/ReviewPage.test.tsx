// @vitest-environment jsdom
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { listReviews, submitReview, undoReview } from "../../lib/api";
import type { ReviewItem } from "../../lib/models";
import { useReviewStore } from "../../stores/reviewStore";
import { ReviewPage } from "./ReviewPage";

vi.mock("../../lib/api", () => ({
  listReviews: vi.fn(),
  submitReview: vi.fn(),
  undoReview: vi.fn(),
}));

vi.mock("@monaco-editor/react", () => ({
  DiffEditor: () => null,
  loader: { config: vi.fn() },
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
  item({ id: "a", segment_index: 1, confidence: 0.93, reason: "bracketed sound effect" }),
  item({
    id: "b",
    segment_index: 2,
    confidence: 0.65,
    before: "♪ music",
    after: "music",
    action: "rewrite",
    reason: "music note",
  }),
  item({
    id: "c",
    segment_index: 3,
    confidence: 0.4,
    before: "hello",
    action: "keep",
    reason: "uppercase",
  }),
];

afterEach(cleanup);

beforeEach(() => {
  listMock.mockReset();
  submitMock.mockReset();
  undoMock.mockReset();
  useReviewStore.getState().reset();
  listMock.mockResolvedValue(ITEMS);
  submitMock.mockResolvedValue("ok");
});

describe("ReviewPage", () => {
  it("渲染 run_id、进度与按置信度排序的列表", async () => {
    render(<ReviewPage runId="run_01" />);

    expect(await screen.findByText(/run_id: run_01/)).toBeTruthy();
    expect(screen.getByText("进度 0/3")).toBeTruthy();

    const entries = screen.getAllByTestId(/^review-item-/);
    expect(entries.map((entry) => entry.getAttribute("data-testid"))).toEqual([
      "review-item-a",
      "review-item-b",
      "review-item-c",
    ]);

    const detail = await screen.findByTestId("review-detail");
    expect(within(detail).getByText(/段落 #1/)).toBeTruthy();
  });

  it("接受/拒绝当前项并更新进度", async () => {
    render(<ReviewPage runId="run_01" />);
    await screen.findByTestId("review-detail");

    fireEvent.click(screen.getByTestId("accept-current"));
    expect(useReviewStore.getState().decisions.a).toBe("accept");

    // 决策后自动跳到下一条待审项。
    fireEvent.click(screen.getByTestId("reject-current"));
    expect(useReviewStore.getState().decisions.b).toBe("reject");

    expect(screen.getByText("进度 2/3")).toBeTruthy();
  });

  it("快捷键 J/K 切换，A 接受，R 拒绝；输入框聚焦时不触发", async () => {
    render(<ReviewPage runId="run_01" />);
    await screen.findByTestId("review-detail");

    fireEvent.keyDown(window, { key: "a" });
    expect(useReviewStore.getState().decisions.a).toBe("accept");

    fireEvent.keyDown(window, { key: "j" });
    fireEvent.keyDown(window, { key: "r" });
    expect(useReviewStore.getState().decisions.c).toBe("reject");

    const textarea = screen.getByLabelText("修改后的文本") as HTMLTextAreaElement;
    fireEvent.keyDown(textarea, { key: "a" });
    expect(useReviewStore.getState().decisions.b).toBeUndefined();
  });

  it("批量接受高置信度与全部拒绝", async () => {
    render(<ReviewPage runId="run_01" />);
    await screen.findByTestId("review-detail");

    fireEvent.click(screen.getByTestId("accept-high-confidence"));
    expect(useReviewStore.getState().decisions).toEqual({ a: "accept" });

    fireEvent.click(screen.getByTestId("reject-all"));
    expect(useReviewStore.getState().decisions).toEqual({
      a: "reject",
      b: "reject",
      c: "reject",
    });
  });

  it("提交时附带改写文本，未决策项默认拒绝", async () => {
    render(<ReviewPage runId="run_01" />);
    await screen.findByTestId("review-detail");

    fireEvent.change(screen.getByLabelText("修改后的文本"), {
      target: { value: "rewritten" },
    });
    fireEvent.click(screen.getByTestId("accept-current"));
    fireEvent.click(screen.getByTestId("submit-review"));

    await waitFor(() => expect(submitMock).toHaveBeenCalledTimes(1));
    expect(submitMock).toHaveBeenCalledWith("run_01", [
      { id: "a", action: "accept", after: "rewritten" },
      { id: "b", action: "reject" },
      { id: "c", action: "reject" },
    ]);

    expect(await screen.findByText(/审核已提交/)).toBeTruthy();
    expect(screen.getByTestId("undo-review")).toBeTruthy();
  });

  it("撤销后展示审计日志与恢复产物路径", async () => {
    undoMock.mockResolvedValue({
      review_id: "rev_1",
      audit_path: "reviews/audit-run_01.jsonl",
      restored: [{ path: "clean/ep01.clean.srt", hash: "deadbeef" }],
    });
    render(<ReviewPage runId="run_01" />);
    await screen.findByTestId("review-detail");

    fireEvent.click(screen.getByTestId("submit-review"));
    const undoButton = await screen.findByTestId("undo-review");
    fireEvent.click(undoButton);

    expect(await screen.findByText(/audit-run_01\.jsonl/)).toBeTruthy();
    expect(screen.getByText("clean/ep01.clean.srt")).toBeTruthy();
    expect(undoMock).toHaveBeenCalledWith("run_01");
  });

  it("空状态与错误状态", async () => {
    listMock.mockResolvedValueOnce([]);
    const { unmount } = render(<ReviewPage runId="run_01" />);
    expect(await screen.findByText("没有需要人工审核的字幕项。")).toBeTruthy();
    unmount();

    listMock.mockRejectedValueOnce(new Error("engine offline"));
    render(<ReviewPage runId="run_02" />);
    const alert = await screen.findByRole("alert");
    expect(alert.textContent).toContain("engine offline");
  });
});

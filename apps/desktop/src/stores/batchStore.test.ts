import { beforeEach, describe, expect, it } from "vitest";
import { useBatchStore } from "./batchStore";

describe("batchStore", () => {
  beforeEach(() => useBatchStore.getState().reset());

  it("start 为每个视频创建排队项", () => {
    useBatchStore.getState().start("video_to_clean_srt", ["C:/a.mkv", "C:/b.mkv"]);
    const state = useBatchStore.getState();
    expect(state.active).toBe(true);
    expect(state.items.map((item) => item.status)).toEqual(["pending", "pending"]);
    expect(state.items[1]?.path).toBe("C:/b.mkv");
  });

  it("update 只修改指定项并保留其他字段", () => {
    useBatchStore.getState().start("video_to_clean_srt", ["C:/a.mkv", "C:/b.mkv"]);
    useBatchStore.getState().update(0, { status: "done", outputs: ["C:/out/a.clean.srt"] });
    const [first, second] = useBatchStore.getState().items;
    expect(first?.status).toBe("done");
    expect(first?.outputs).toEqual(["C:/out/a.clean.srt"]);
    expect(second?.status).toBe("pending");
  });

  it("finish 保留队列用于展示，reset 清空", () => {
    useBatchStore.getState().start("video_to_clean_srt", ["C:/a.mkv"]);
    useBatchStore.getState().finish();
    expect(useBatchStore.getState().active).toBe(false);
    expect(useBatchStore.getState().items).toHaveLength(1);

    useBatchStore.getState().reset();
    expect(useBatchStore.getState().items).toEqual([]);
    expect(useBatchStore.getState().taskId).toBeNull();
  });
});

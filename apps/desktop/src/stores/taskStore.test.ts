import { beforeEach, describe, expect, it, vi } from "vitest";
import { listTasks } from "../lib/api";
import type { TaskSpec } from "../lib/models";
import { pickOriginalSubtitle } from "../lib/tasks";
import { useTaskStore } from "./taskStore";

vi.mock("../lib/api", () => ({
  listTasks: vi.fn(),
}));

const listMock = vi.mocked(listTasks);

const EXTRACTION: TaskSpec = {
  id: "video_to_clean_srt",
  recipe_id: "video_to_clean_srt",
  kind: "workflow",
  group: "视频",
  order: 10,
  title: "视频 → 规范字幕",
  description: "",
  inputs: [
    { name: "video", label: "视频", kind: "file", accept: [".mkv"], required: true },
  ],
  requires_project: true,
};

const BILINGUAL: TaskSpec = {
  id: "translated_to_bilingual",
  recipe_id: "translated_to_bilingual",
  kind: "workflow",
  group: "字幕",
  order: 20,
  title: "双语合并",
  description: "",
  inputs: [
    { name: "original", label: "原版", kind: "file", accept: [".srt"], required: true },
    { name: "translated", label: "译文", kind: "files", accept: [".srt"], required: true },
  ],
  requires_project: true,
};

beforeEach(() => {
  listMock.mockReset();
  useTaskStore.getState().reset();
  listMock.mockResolvedValue([BILINGUAL, EXTRACTION]);
});

describe("taskStore", () => {
  it("加载目录后按 order 选中首个任务", async () => {
    await useTaskStore.getState().load();
    expect(useTaskStore.getState().tasks.map((task) => task.id)).toEqual([
      EXTRACTION.id,
      BILINGUAL.id,
    ]);
    expect(useTaskStore.getState().selectedTaskId).toBe(EXTRACTION.id);
  });

  it("autoFillOriginal 填充空的原版槽并标记为自动填充", () => {
    useTaskStore.setState({ tasks: [EXTRACTION, BILINGUAL] });
    useTaskStore.getState().autoFillOriginal(["C:/out/Show.clean.srt"]);

    const state = useTaskStore.getState();
    expect(state.slots[BILINGUAL.id]?.original).toEqual(["C:/out/Show.clean.srt"]);
    expect(state.autofilled[BILINGUAL.id]?.original).toBe(true);
  });

  it("autoFillOriginal 不覆盖用户手动填写的原版槽", () => {
    useTaskStore.setState({ tasks: [EXTRACTION, BILINGUAL] });
    useTaskStore.getState().setSlot(BILINGUAL.id, "original", ["C:/manual/old.srt"]);
    useTaskStore.getState().autoFillOriginal(["C:/out/Show.clean.srt"]);

    const state = useTaskStore.getState();
    expect(state.slots[BILINGUAL.id]?.original).toEqual(["C:/manual/old.srt"]);
    expect(state.autofilled[BILINGUAL.id]?.original).toBe(false);
  });

  it("清空后可再次自动填充", () => {
    useTaskStore.setState({ tasks: [EXTRACTION, BILINGUAL] });
    useTaskStore.getState().setSlot(BILINGUAL.id, "original", ["C:/manual/old.srt"]);
    useTaskStore.getState().clearSlot(BILINGUAL.id, "original");
    useTaskStore.getState().autoFillOriginal(["C:/out/Show.clean.srt"]);

    expect(useTaskStore.getState().slots[BILINGUAL.id]?.original).toEqual([
      "C:/out/Show.clean.srt",
    ]);
  });

  it("通用槽分发后可以撤销", () => {
    useTaskStore.setState({ tasks: [EXTRACTION, BILINGUAL] });
    useTaskStore.getState().setSlot(BILINGUAL.id, "translated", ["C:/old/EP00.zh.srt"]);

    const result = useTaskStore.getState().applyRouting(BILINGUAL.id, [
      "C:/show/EP01.clean.srt",
      "C:/show/EP01.zh.srt",
    ]);
    expect(result?.assigned).toEqual([
      { input: "original", paths: ["C:/show/EP01.clean.srt"] },
    ]);
    expect(result?.unassigned[0]?.path).toBe("C:/show/EP01.zh.srt");
    expect(useTaskStore.getState().slots[BILINGUAL.id]).toEqual({
      translated: ["C:/old/EP00.zh.srt"],
      original: ["C:/show/EP01.clean.srt"],
    });

    useTaskStore.getState().undoRouting(BILINGUAL.id);
    expect(useTaskStore.getState().slots[BILINGUAL.id]).toEqual({
      translated: ["C:/old/EP00.zh.srt"],
    });
    expect(useTaskStore.getState().lastRouting[BILINGUAL.id]).toBeNull();
  });

  it("拖动改槽会移动文件并更新分配结果", () => {
    useTaskStore.setState({ tasks: [EXTRACTION, BILINGUAL] });
    useTaskStore.getState().applyRouting(BILINGUAL.id, [
      "C:/show/EP01.clean.srt",
      "C:/show/EP01.zh.srt",
    ]);

    useTaskStore
      .getState()
      .moveSlotPath(BILINGUAL.id, "original", "translated", "C:/show/EP01.clean.srt");

    const state = useTaskStore.getState();
    expect(state.slots[BILINGUAL.id]).toEqual({
      original: [],
      translated: ["C:/show/EP01.zh.srt", "C:/show/EP01.clean.srt"],
    });
    expect(state.lastRouting[BILINGUAL.id]?.assigned).toEqual([
      { input: "translated", paths: ["C:/show/EP01.zh.srt", "C:/show/EP01.clean.srt"] },
    ]);
  });

  it("拖到已有内容的单文件槽会交换而不是覆盖", () => {
    useTaskStore.setState({ tasks: [EXTRACTION, BILINGUAL] });
    useTaskStore.getState().setSlot(BILINGUAL.id, "original", ["C:/show/A.srt"]);
    useTaskStore.getState().setSlot(BILINGUAL.id, "translated", ["C:/show/B.zh.srt"]);

    useTaskStore.getState().moveSlotPath(BILINGUAL.id, "translated", "original", "C:/show/B.zh.srt");

    expect(useTaskStore.getState().slots[BILINGUAL.id]).toEqual({
      original: ["C:/show/B.zh.srt"],
      translated: ["C:/show/A.srt"],
    });
  });
});

describe("pickOriginalSubtitle", () => {
  it("优先选择最新 .clean.srt", () => {
    expect(
      pickOriginalSubtitle([
        "C:/a/Show.srt",
        "C:/a/Show.clean.srt",
        "C:/a/Show.ass",
        "C:/a/Episode2.clean.srt",
      ]),
    ).toBe("C:/a/Episode2.clean.srt");
  });

  it("没有 clean 时回退到最新 .srt", () => {
    expect(pickOriginalSubtitle(["C:/a/Show.ass", "C:/a/Show.srt", "C:/a/b.srt"])).toBe(
      "C:/a/b.srt",
    );
    expect(pickOriginalSubtitle(["C:/a/Show.ass"])).toBeNull();
  });
});

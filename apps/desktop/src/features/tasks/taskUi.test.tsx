// @vitest-environment jsdom
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { TaskSpec } from "../../lib/models";
import { TaskInputs } from "./TaskInputs";
import { TaskPicker } from "./TaskPicker";

const { dropHandlers } = vi.hoisted(() => ({
  dropHandlers: [] as Array<(event: { payload: { type: string; paths: string[] } }) => void>,
}));

vi.mock("@tauri-apps/api/webview", () => ({
  getCurrentWebview: () => ({
    onDragDropEvent: async (handler: (event: { payload: { type: string; paths: string[] } }) => void) => {
      dropHandlers.push(handler);
      return () => undefined;
    },
  }),
}));

vi.mock("../../lib/rpc", () => ({
  pickFiles: vi.fn().mockResolvedValue([]),
  pickFolder: vi.fn().mockResolvedValue(null),
}));

const BILINGUAL: TaskSpec = {
  id: "batch_translated_to_bilingual",
  recipe_id: "batch_translated_to_bilingual",
  kind: "workflow",
  group: "字幕",
  order: 20,
  title: "双语合并",
  description: "合并原版与译文",
  inputs: [
    { name: "original", label: "原版", kind: "file", accept: [".srt"], required: true },
    { name: "translated", label: "译文", kind: "files", accept: [".srt"], required: true },
  ],
  requires_project: true,
};

const EXTRACT: TaskSpec = {
  id: "fn_extract_subtitles",
  recipe_id: "batch_video_to_clean_srt",
  kind: "function",
  group: "媒体",
  order: 5,
  title: "提取字幕",
  description: "从视频中提取字幕",
  inputs: [
    { name: "video", label: "视频", kind: "file", accept: [".mkv", ".mp4"], required: true },
    { name: "subtitle", label: "字幕", kind: "file", accept: [".srt"], required: false },
  ],
  requires_project: false,
};

beforeEach(() => {
  dropHandlers.length = 0;
});

afterEach(cleanup);

describe("TaskPicker", () => {
  it("按流水线 / 单项功能分栏展示任务", async () => {
    const user = userEvent.setup();
    render(
      <TaskPicker
        tasks={[BILINGUAL, EXTRACT]}
        selectedId={BILINGUAL.id}
        onSelect={() => undefined}
      />,
    );

    expect(screen.getByTestId("task-card-batch_translated_to_bilingual")).toBeTruthy();
    expect(screen.queryByTestId("task-card-fn_extract_subtitles")).toBeNull();

    await user.click(screen.getByTestId("task-tab-function"));
    expect(screen.getByTestId("task-card-fn_extract_subtitles")).toBeTruthy();
    expect(screen.queryByTestId("task-card-batch_translated_to_bilingual")).toBeNull();
  });
});

describe("TaskInputs", () => {
  it("为每个输入渲染槽位、必填标记与自动填充徽标", () => {
    render(
      <TaskInputs
        task={BILINGUAL}
        slots={{ original: ["C:/out/Show.clean.srt"] }}
        autofilled={{ original: true }}
        onSet={() => undefined}
        onClear={() => undefined}
        onRoute={() => undefined}
        onMove={() => undefined}
        onUndoRouting={() => undefined}
      />,
    );

    expect(screen.getByTestId("input-slot-original")).toBeTruthy();
    expect(screen.getByTestId("input-slot-translated")).toBeTruthy();
    expect(screen.getByText("原版")).toBeTruthy();
    expect(screen.getAllByText("必填")).toHaveLength(2);
    expect(screen.getByText("自动填充")).toBeTruthy();
    expect(screen.getByText("C:/out/Show.clean.srt")).toBeTruthy();
  });

  it("原生拖拽在没有焦点槽时交给通用槽规则", async () => {
    const onRoute = vi.fn();
    render(
      <TaskInputs
        task={EXTRACT}
        slots={{}}
        autofilled={{}}
        onSet={() => undefined}
        onClear={() => undefined}
        onRoute={onRoute}
        onMove={() => undefined}
        onUndoRouting={() => undefined}
      />,
    );

    await waitFor(() => expect(dropHandlers.length).toBeGreaterThan(0));
    dropHandlers[0]({
      payload: {
        type: "drop",
        paths: ["C:/media/Show.mkv", "C:/subs/Show.srt"],
      },
    });

    await waitFor(() => {
      expect(onRoute).toHaveBeenCalledWith(
        ["C:/media/Show.mkv", "C:/subs/Show.srt"],
        false,
        false,
      );
    });
  });

  it("清空按钮调用 onClear", async () => {
    const user = userEvent.setup();
    const onClear = vi.fn();
    render(
      <TaskInputs
        task={BILINGUAL}
        slots={{ original: ["C:/out/Show.clean.srt"] }}
        autofilled={{}}
        onSet={() => undefined}
        onClear={onClear}
        onRoute={() => undefined}
        onMove={() => undefined}
        onUndoRouting={() => undefined}
      />,
    );

    const slot = screen.getByTestId("input-slot-original");
    const clear = within(slot).getByRole("button", { name: "清空" });
    await user.click(clear);
    expect(onClear).toHaveBeenCalledWith(BILINGUAL.id, "original");
  });

  it("把文件行拖到另一个槽位会调用 onMove", async () => {
    const onMove = vi.fn();
    render(
      <TaskInputs
        task={BILINGUAL}
        slots={{ original: ["C:/out/Show.clean.srt"] }}
        autofilled={{}}
        onSet={() => undefined}
        onClear={() => undefined}
        onRoute={() => undefined}
        onMove={onMove}
        onUndoRouting={() => undefined}
      />,
    );

    const file = screen.getByText("C:/out/Show.clean.srt");
    const translated = screen.getByTestId("input-slot-translated");
    const original = document.elementFromPoint;
    Object.defineProperty(document, "elementFromPoint", {
      configurable: true,
      value: () => translated,
    });

    const pointer = (type: string, clientX: number, clientY: number) =>
      new MouseEvent(type, { bubbles: true, clientX, clientY, button: 0 });

    file.dispatchEvent(pointer("pointerdown", 10, 10));
    window.dispatchEvent(pointer("pointermove", 40, 40));
    window.dispatchEvent(pointer("pointerup", 40, 40));

    expect(onMove).toHaveBeenCalledWith(
      BILINGUAL.id,
      "original",
      "translated",
      "C:/out/Show.clean.srt",
    );
    Object.defineProperty(document, "elementFromPoint", {
      configurable: true,
      value: original,
    });
  });
});

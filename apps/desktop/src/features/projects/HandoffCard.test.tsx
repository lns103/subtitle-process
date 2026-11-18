// @vitest-environment jsdom
import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { Project } from "../../lib/models";
import { HandoffCard } from "./HandoffCard";

const { renameProjectMock } = vi.hoisted(() => ({ renameProjectMock: vi.fn() }));

vi.mock("../../lib/api", () => ({
  revealPath: vi.fn().mockResolvedValue("ok"),
  renameProject: renameProjectMock,
}));

const PROJECT: Project = {
  id: "prj_test",
  name: "测试项目",
  status: "done",
  created_at: "2026-01-01T00:00:00Z",
  updated_at: "2026-01-01T00:00:00Z",
  media: null,
  language: { source: "en", target: "zh" },
  runs: [],
  outputs: [],
  notes: "",
  workspace: "C:/tmp/prj_test",
};

const PROJECT_WITH_OUTPUTS: Project = {
  ...PROJECT,
  status: "done",
  outputs: [
    { path: "C:/tmp/prj_test/out/a.srt", kind: "srt", created_at: "2026-01-01T00:00:00Z" },
    { path: "C:/tmp/prj_test/out/b.ass", kind: "ass", created_at: "2026-01-01T00:00:01Z" },
  ],
};

afterEach(() => {
  cleanup();
  renameProjectMock.mockReset();
});

describe("HandoffCard", () => {
  it("点击关闭按钮只关闭面板，不删除项目", async () => {
    const user = userEvent.setup();
    const onClose = vi.fn();
    render(<HandoffCard project={PROJECT} onClose={onClose} />);

    await user.click(screen.getByTestId("close-project"));

    expect(onClose).toHaveBeenCalledTimes(1);
  });

  it("未传入 onClose 时不显示关闭按钮", () => {
    render(<HandoffCard project={PROJECT} />);
    expect(screen.queryByTestId("close-project")).toBeNull();
  });

  it("完成后折叠产物，只显示最新，可展开全部", async () => {
    const user = userEvent.setup();
    render(<HandoffCard project={PROJECT_WITH_OUTPUTS} />);

    expect(screen.getByText("C:/tmp/prj_test/out/b.ass")).toBeTruthy();
    expect(screen.queryByText("C:/tmp/prj_test/out/a.srt")).toBeNull();

    await user.click(screen.getByText("展开全部 (2)"));
    expect(screen.getByText("C:/tmp/prj_test/out/a.srt")).toBeTruthy();
  });

  it("运行中展示全部产物", () => {
    render(<HandoffCard project={{ ...PROJECT_WITH_OUTPUTS, status: "running" }} />);
    expect(screen.getByText("C:/tmp/prj_test/out/a.srt")).toBeTruthy();
    expect(screen.getByText("C:/tmp/prj_test/out/b.ass")).toBeTruthy();
  });

  it("可以修改项目名", async () => {
    const user = userEvent.setup();
    renameProjectMock.mockResolvedValue({ ...PROJECT, name: "新名字" });
    render(<HandoffCard project={PROJECT} />);

    await user.click(screen.getByTestId("edit-project-name"));
    const input = screen.getByTestId("project-name-input");
    await user.clear(input);
    await user.type(input, "新名字");
    await user.click(screen.getByTestId("save-project-name"));

    expect(renameProjectMock).toHaveBeenCalledWith("prj_test", "新名字");
  });
});

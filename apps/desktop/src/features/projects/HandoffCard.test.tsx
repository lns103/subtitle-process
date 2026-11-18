// @vitest-environment jsdom
import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { Project } from "../../lib/models";
import { HandoffCard } from "./HandoffCard";

vi.mock("../../lib/api", () => ({
  revealPath: vi.fn().mockResolvedValue("ok"),
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

afterEach(cleanup);

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
});

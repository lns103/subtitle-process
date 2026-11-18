// @vitest-environment jsdom
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { confirm } from "@tauri-apps/plugin-dialog";
import type { ProjectSummary } from "../../lib/models";
import { ProjectList } from "./ProjectList";

vi.mock("@tauri-apps/plugin-dialog", () => ({
  confirm: vi.fn(),
}));

const confirmMock = vi.mocked(confirm);

const READY: ProjectSummary = {
  id: "prj_1",
  name: "Show.S01E01",
  status: "done",
  created_at: "2026-11-01T00:00:00Z",
  updated_at: "2026-11-02T00:00:00Z",
  media_path: "C:/media/Show.S01E01.mkv",
  workspace: "C:/projects/prj_1",
  outputs: ["C:/projects/prj_1/output/Show.S01E01.clean.srt"],
};

const RUNNING: ProjectSummary = {
  ...READY,
  id: "prj_running",
  name: "Show.S01E02",
  status: "running",
};

beforeEach(() => {
  confirmMock.mockReset();
});

afterEach(cleanup);

describe("ProjectList 删除", () => {
  it("点击删除会二次确认、阻止选中并回调 onDelete", async () => {
    const user = userEvent.setup();
    const onSelect = vi.fn();
    const onDelete = vi.fn();
    confirmMock.mockResolvedValue(true);

    render(<ProjectList projects={[READY]} onSelect={onSelect} onDelete={onDelete} />);

    await user.click(screen.getByTestId(`delete-project-${READY.id}`));

    expect(confirmMock).toHaveBeenCalledTimes(1);
    const [message, options] = confirmMock.mock.calls[0];
    expect(message).toContain(READY.name);
    expect(message).toContain("项目工作区");
    expect(message).toContain("已导出的字幕文件");
    expect(message).toContain("无法恢复");
    expect(typeof options).toBe("object");
    if (typeof options === "object" && options !== null) {
      expect(options.title).toBe("删除项目");
    }

    await waitFor(() => expect(onDelete).toHaveBeenCalledWith(READY.id));
    expect(onSelect).not.toHaveBeenCalled();
  });

  it("取消确认时不调用 onDelete", async () => {
    const user = userEvent.setup();
    const onSelect = vi.fn();
    const onDelete = vi.fn();
    confirmMock.mockResolvedValue(false);

    render(<ProjectList projects={[READY]} onSelect={onSelect} onDelete={onDelete} />);

    await user.click(screen.getByTestId(`delete-project-${READY.id}`));

    await waitFor(() => expect(confirmMock).toHaveBeenCalledTimes(1));
    expect(onDelete).not.toHaveBeenCalled();
    expect(onSelect).not.toHaveBeenCalled();
  });

  it("running 项目禁用删除并给出提示", async () => {
    const user = userEvent.setup();
    const onDelete = vi.fn();

    render(<ProjectList projects={[RUNNING]} onSelect={() => undefined} onDelete={onDelete} />);

    const button = screen.getByTestId(`delete-project-${RUNNING.id}`) as HTMLButtonElement;
    expect(button.disabled).toBe(true);
    expect(button.title).toContain("运行中");

    await user.click(button);
    expect(confirmMock).not.toHaveBeenCalled();
    expect(onDelete).not.toHaveBeenCalled();
  });

  it("deletingId 对应行显示禁用态", () => {
    render(
      <ProjectList
        projects={[READY]}
        onSelect={() => undefined}
        onDelete={() => undefined}
        deletingId={READY.id}
      />,
    );

    const button = screen.getByTestId(`delete-project-${READY.id}`) as HTMLButtonElement;
    expect(button.disabled).toBe(true);
  });

  it("未接线 onDelete 时删除按钮保持禁用", () => {
    render(<ProjectList projects={[READY]} onSelect={() => undefined} />);

    const button = screen.getByTestId(`delete-project-${READY.id}`) as HTMLButtonElement;
    expect(button.disabled).toBe(true);
  });
});

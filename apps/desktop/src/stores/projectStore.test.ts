import { beforeEach, describe, expect, it, vi } from "vitest";
import { deleteProject, getProject, listProjects } from "../lib/api";
import type { Project, ProjectSummary } from "../lib/models";
import { useProjectStore } from "./projectStore";

vi.mock("../lib/api", () => ({
  deleteProject: vi.fn(),
  getProject: vi.fn(),
  listProjects: vi.fn(),
}));

const deleteMock = vi.mocked(deleteProject);
const getMock = vi.mocked(getProject);
const listMock = vi.mocked(listProjects);

const FIRST: ProjectSummary = {
  id: "prj_1",
  name: "Show.S01E01",
  status: "done",
  created_at: "2026-11-01T00:00:00Z",
  updated_at: "2026-11-02T00:00:00Z",
  media_path: "C:/media/Show.S01E01.mkv",
  workspace: "C:/projects/prj_1",
  outputs: ["C:/projects/prj_1/output/Show.S01E01.clean.srt"],
};

const SECOND: ProjectSummary = {
  ...FIRST,
  id: "prj_2",
  name: "Show.S01E02",
  workspace: "C:/projects/prj_2",
  outputs: [],
};

const FIRST_DETAIL: Project = {
  id: FIRST.id,
  name: FIRST.name,
  status: FIRST.status,
  created_at: FIRST.created_at,
  updated_at: FIRST.updated_at,
  media: null,
  language: { source: "ja", target: "zh" },
  runs: [],
  outputs: [],
  notes: "",
  workspace: FIRST.workspace,
};

beforeEach(() => {
  deleteMock.mockReset();
  getMock.mockReset();
  listMock.mockReset();

  useProjectStore.setState({
    projects: [FIRST, SECOND],
    active: FIRST_DETAIL,
    loading: false,
    lastError: null,
    deletingId: null,
    preferredProjectId: FIRST.id,
  });
});

describe("projectStore.remove", () => {
  it("删除成功后移除项目，并清空 active 与 preferredProjectId", async () => {
    deleteMock.mockResolvedValue("ok");

    await useProjectStore.getState().remove(FIRST.id);

    expect(deleteMock).toHaveBeenCalledWith(FIRST.id);
    const state = useProjectStore.getState();
    expect(state.projects).toEqual([SECOND]);
    expect(state.active).toBeNull();
    expect(state.preferredProjectId).toBeNull();
    expect(state.deletingId).toBeNull();
    expect(state.lastError).toBeNull();
  });

  it("只清空匹配项目的 active / preferredProjectId", async () => {
    deleteMock.mockResolvedValue("ok");

    await useProjectStore.getState().remove(SECOND.id);

    const state = useProjectStore.getState();
    expect(state.projects).toEqual([FIRST]);
    expect(state.active).toEqual(FIRST_DETAIL);
    expect(state.preferredProjectId).toBe(FIRST.id);
  });

  it("删除失败时保留列表并写入 lastError", async () => {
    deleteMock.mockRejectedValue(new Error("delete failed"));

    await useProjectStore.getState().remove(FIRST.id);

    const state = useProjectStore.getState();
    expect(state.projects).toEqual([FIRST, SECOND]);
    expect(state.active).toEqual(FIRST_DETAIL);
    expect(state.preferredProjectId).toBe(FIRST.id);
    expect(state.deletingId).toBeNull();
    expect(state.lastError).toBe("delete failed");
  });

  it("删除过程中设置 deletingId，结束后复位", async () => {
    let resolveDelete: (value: string) => void = () => undefined;
    deleteMock.mockReturnValue(
      new Promise<string>((resolve) => {
        resolveDelete = resolve;
      }),
    );

    const pending = useProjectStore.getState().remove(FIRST.id);

    expect(useProjectStore.getState().deletingId).toBe(FIRST.id);

    resolveDelete("ok");
    await pending;

    expect(useProjectStore.getState().deletingId).toBeNull();
    expect(useProjectStore.getState().projects).toEqual([SECOND]);
  });
});

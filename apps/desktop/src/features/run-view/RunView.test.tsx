// @vitest-environment jsdom
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import {
  createProject,
  getProject,
  listProjects,
  revealPath,
  runRecipe,
  validateRecipe,
} from "../../lib/api";
import type { Project, ProjectSummary } from "../../lib/models";
import { useProjectStore } from "../../stores/projectStore";
import { useRunStore } from "../../stores/runStore";
import { RunView } from "./RunView";

vi.mock("../../lib/api", () => ({
  createProject: vi.fn(),
  getProject: vi.fn(),
  listProjects: vi.fn(),
  revealPath: vi.fn(),
  runRecipe: vi.fn(),
  validateRecipe: vi.fn(),
}));

const listMock = vi.mocked(listProjects);
const getMock = vi.mocked(getProject);
const createMock = vi.mocked(createProject);
const validateMock = vi.mocked(validateRecipe);
const runMock = vi.mocked(runRecipe);
const revealMock = vi.mocked(revealPath);

const WAITING: ProjectSummary = {
  id: "prj_1",
  name: "Show.S01E01",
  status: "waiting_translation",
  created_at: "2026-11-01T00:00:00Z",
  updated_at: "2026-11-02T00:00:00Z",
  media_path: "C:/media/Show.S01E01.mkv",
  workspace: "C:/projects/prj_1",
  outputs: ["C:/projects/prj_1/output/Show.S01E01.clean.srt"],
};

const WAITING_DETAIL: Project = {
  id: WAITING.id,
  name: WAITING.name,
  status: WAITING.status,
  created_at: WAITING.created_at,
  updated_at: WAITING.updated_at,
  media: null,
  language: { source: "ja", target: "zh" },
  runs: [],
  outputs: [
    {
      path: WAITING.outputs[0],
      kind: "subtitle",
      step: "export",
      created_at: WAITING.updated_at,
    },
  ],
  notes: "",
  workspace: WAITING.workspace,
};

beforeEach(() => {
  listMock.mockReset();
  getMock.mockReset();
  createMock.mockReset();
  validateMock.mockReset();
  runMock.mockReset();
  revealMock.mockReset();

  useProjectStore.setState({
    projects: [],
    active: null,
    loading: false,
    lastError: null,
    preferredProjectId: null,
  });
  useRunStore.getState().reset();

  listMock.mockResolvedValue([WAITING]);
  getMock.mockResolvedValue(WAITING_DETAIL);
  validateMock.mockResolvedValue({ ok: true, errors: [], warnings: [], order: [] });
  runMock.mockResolvedValue({ job_id: "job_1", run_id: "run_1" });
});

afterEach(cleanup);

describe("RunView 流程分派", () => {
  it("拖入视频时仍显示视频 → 规范字幕流程", () => {
    render(<RunView paths={["C:/media/movie.mkv"]} engineReady />);
    expect(screen.getByText("视频 → 规范字幕")).toBeTruthy();
    expect(screen.queryByText("译文 → 双语 ASS")).toBeNull();
  });

  it("仅拖入字幕时进入译文流程，推荐等待翻译项目并调用 runRecipe", async () => {
    const user = userEvent.setup();
    render(<RunView paths={["C:/subs/Show.S01E01.zh.srt"]} engineReady />);

    expect(await screen.findByText("译文 → 双语 ASS")).toBeTruthy();
    await waitFor(() => expect(listMock).toHaveBeenCalled());

    const runButton = screen.getByTestId("run-translated") as HTMLButtonElement;
    await waitFor(() => expect(runButton.disabled).toBe(false));

    await user.click(runButton);

    await waitFor(() => expect(validateMock).toHaveBeenCalledWith("batch_translated_to_bilingual", "prj_1"));
    await waitFor(() =>
      expect(runMock).toHaveBeenCalledWith({
        recipeId: "batch_translated_to_bilingual",
        inputs: ["C:/subs/Show.S01E01.zh.srt"],
        projectId: "prj_1",
      }),
    );
    expect(useRunStore.getState().runId).toBe("run_1");
  });
});

// @vitest-environment jsdom
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { confirm } from "@tauri-apps/plugin-dialog";
import {
  deleteRecipe,
  getRecipe,
  listRecipes,
  listSteps,
} from "../../lib/api";
import { navigate } from "../../lib/router";
import { useEditorStore } from "../../stores/editorStore";
import { EditorPage } from "./EditorPage";

vi.mock("@tauri-apps/plugin-dialog", () => ({
  confirm: vi.fn(),
}));

vi.mock("../../lib/api", () => ({
  cancelJob: vi.fn(),
  createProject: vi.fn(),
  deleteRecipe: vi.fn(),
  getRecipe: vi.fn(),
  listRecipes: vi.fn(),
  listSteps: vi.fn(),
  runRecipePayload: vi.fn(),
  saveRecipe: vi.fn(),
  validateRecipePayload: vi.fn(),
}));

vi.mock("../../lib/router", () => ({
  navigate: vi.fn(),
}));

vi.mock("./FlowCanvas", () => ({ FlowCanvas: () => <div data-testid="flow-canvas" /> }));
vi.mock("./Inspector", () => ({ Inspector: () => <div data-testid="inspector" /> }));
vi.mock("./RunInputs", () => ({ RunInputs: () => <div data-testid="run-inputs" /> }));
vi.mock("./StepPanel", () => ({ StepPanel: () => <div data-testid="step-panel" /> }));
vi.mock("./SaveAsDialog", () => ({ SaveAsDialog: () => null }));

const confirmMock = vi.mocked(confirm);
const deleteRecipeMock = vi.mocked(deleteRecipe);
const getRecipeMock = vi.mocked(getRecipe);
const listRecipesMock = vi.mocked(listRecipes);
const listStepsMock = vi.mocked(listSteps);
const navigateMock = vi.mocked(navigate);

const RECIPE = {
  id: "my_flow",
  name: "我的流程",
  version: 1,
  description: "",
  builtin: false,
  inputs: [],
  steps: [],
  outputs: [],
  ui: {},
};

beforeEach(() => {
  confirmMock.mockReset();
  deleteRecipeMock.mockReset();
  deleteRecipeMock.mockResolvedValue("ok");
  listStepsMock.mockResolvedValue([]);
  listRecipesMock.mockResolvedValue([
    {
      id: RECIPE.id,
      name: RECIPE.name,
      version: RECIPE.version,
      description: RECIPE.description,
      builtin: false,
      step_count: 0,
    },
  ]);
  getRecipeMock.mockResolvedValue(RECIPE);
});

afterEach(() => {
  cleanup();
  useEditorStore.temporal.getState().clear();
});

describe("EditorPage 删除自定义配方", () => {
  it("二次确认后删除当前配方并回到未保存状态", async () => {
    const user = userEvent.setup();
    confirmMock.mockResolvedValue(true);

    render(<EditorPage initialRecipeId={RECIPE.id} paths={[]} />);

    const button = (await screen.findByTestId("delete-recipe")) as HTMLButtonElement;
    await waitFor(() => expect(button.disabled).toBe(false));
    await user.click(button);

    await waitFor(() => expect(confirmMock).toHaveBeenCalledTimes(1));
    const [message, options] = confirmMock.mock.calls[0];
    expect(message).toContain(RECIPE.name);
    expect(message).toContain("无法恢复");
    if (typeof options === "object" && options !== null) {
      expect(options.title).toBe("删除配方");
    }

    await waitFor(() => expect(deleteRecipeMock).toHaveBeenCalledWith(RECIPE.id));
    await waitFor(() =>
      expect(navigateMock).toHaveBeenCalledWith({ name: "editor", recipeId: null }),
    );
    expect(useEditorStore.getState().recipeId).not.toBe(RECIPE.id);
  });

  it("取消确认时不删除配方", async () => {
    const user = userEvent.setup();
    confirmMock.mockResolvedValue(false);

    render(<EditorPage initialRecipeId={RECIPE.id} paths={[]} />);

    const button = (await screen.findByTestId("delete-recipe")) as HTMLButtonElement;
    await waitFor(() => expect(button.disabled).toBe(false));
    await user.click(button);

    await waitFor(() => expect(confirmMock).toHaveBeenCalledTimes(1));
    expect(deleteRecipeMock).not.toHaveBeenCalled();
    expect(navigateMock).not.toHaveBeenCalled();
  });
});

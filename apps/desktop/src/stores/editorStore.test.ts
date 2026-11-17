// @vitest-environment jsdom
import { beforeEach, describe, expect, it } from "vitest";
import type { StepSpec } from "../lib/models";
import { isEditorDirty, useEditorStore } from "./editorStore";
function spec(
  id: string,
  inputs: Record<string, { kind: string; required?: boolean }> = {},
  outputs: Record<string, { kind: string }> = {},
): StepSpec {
  return {
    id,
    title: id,
    description: "",
    inputs: Object.fromEntries(
      Object.entries(inputs).map(([name, port]) => [
        name,
        { kind: port.kind, required: port.required ?? true, multiple: false },
      ]),
    ),
    outputs: Object.fromEntries(
      Object.entries(outputs).map(([name, port]) => [
        name,
        { kind: port.kind, required: true, multiple: false },
      ]),
    ),
    options_schema: { type: "object", properties: {} },
    requires_agent: false,
    deterministic: true,
  };
}

const SPECS: StepSpec[] = [
  spec("media.probe", {}, { probe: { kind: "media_info" } }),
  spec("media.extract_subtitles", { probe: { kind: "media_info" } }, { subs: { kind: "srt" } }),
  spec("sub.normalize", { subs: { kind: "srt", required: false } }, { subs: { kind: "srt" } }),
  spec("sub.validate", { subs: { kind: "srt" } }, { subs: { kind: "srt" }, report: { kind: "validation" } }),
  spec("sub.export", { subs: { kind: "any" } }, { files: { kind: "any" } }),
];

function reset() {
  useEditorStore.getState().newRecipe(SPECS, "测试配方");
  useEditorStore.temporal.getState().clear();
}

function add(uses: string, x = 0, y = 0) {
  const found = SPECS.find((item) => item.id === uses);
  if (!found) throw new Error(`missing spec ${uses}`);
  return useEditorStore.getState().addStep(found, { x, y });
}

function connect(source: string, target: string, sourceHandle: string, targetHandle: string) {
  return useEditorStore.getState().connect({ source, target, sourceHandle, targetHandle });
}

describe("editorStore", () => {
  beforeEach(reset);

  it("添加步骤使用唯一 id 和 schema 默认参数", () => {
    expect(add("media.probe")).toBe("probe");
    expect(add("media.probe")).toBe("probe_2");
    expect(useEditorStore.getState().nodes).toHaveLength(2);
  });

  it("拒绝类型不兼容的连线", () => {
    const probe = add("media.probe");
    const validate = add("sub.validate");
    const problem = connect(probe, validate, "probe", "subs");
    expect(problem).toContain("不兼容");
    expect(useEditorStore.getState().edges).toHaveLength(0);
  });

  it("允许 any 端口并生成配方 needs/outputs", () => {
    const probe = add("media.probe");
    const extract = add("media.extract_subtitles");
    const normalize = add("sub.normalize");
    const validate = add("sub.validate");
    const exporter = add("sub.export");

    expect(connect(probe, extract, "probe", "probe")).toBeNull();
    expect(connect(extract, normalize, "subs", "subs")).toBeNull();
    expect(connect(normalize, validate, "subs", "subs")).toBeNull();
    expect(connect(validate, exporter, "subs", "subs")).toBeNull();
    expect(useEditorStore.getState().edges).toHaveLength(4);

    const { recipe, cycle } = useEditorStore.getState().toRecipe();
    expect(cycle).toBeNull();
    expect(recipe.steps.map((step) => step.id)).toEqual([
      probe,
      extract,
      normalize,
      validate,
      exporter,
    ]);
    expect(recipe.steps.find((step) => step.id === exporter)?.needs).toEqual([validate]);
    expect(recipe.outputs).toEqual([
      { from: exporter, key: "files" },
    ]);
  });

  it("撤销/重做结构变化", () => {
    add("media.probe");
    add("media.extract_subtitles");
    expect(useEditorStore.getState().nodes).toHaveLength(2);

    useEditorStore.temporal.getState().undo();
    expect(useEditorStore.getState().nodes).toHaveLength(1);

    useEditorStore.temporal.getState().redo();
    expect(useEditorStore.getState().nodes).toHaveLength(2);
  });

  it("选中状态不进入撤销历史", () => {
    const probe = add("media.probe");
    useEditorStore.temporal.getState().clear();
    useEditorStore.getState().setSelection([probe]);
    expect(useEditorStore.temporal.getState().pastStates).toHaveLength(0);
  });

  it("拖动结束后可以一步撤销回拖动前位置", () => {
    const probe = add("media.probe");
    useEditorStore.temporal.getState().clear();
    const store = useEditorStore.getState();
    const before = store.nodes.find((node) => node.id === probe)?.position ?? { x: 0, y: 0 };

    // 模拟 FlowCanvas：拖动期间暂停记录，松手后先还原再提交最终位置。
    useEditorStore.temporal.getState().pause();
    store.moveNode(probe, { x: 300, y: 200 });
    store.moveNode(probe, before);
    useEditorStore.temporal.getState().resume();
    store.moveNode(probe, { x: 300, y: 200 });

    expect(useEditorStore.temporal.getState().pastStates).toHaveLength(1);
    useEditorStore.temporal.getState().undo();
    const afterUndo = useEditorStore.getState().nodes.find((node) => node.id === probe);
    expect(afterUndo?.position).toEqual(before);
  });

  it("删除节点同时清理连线", () => {
    const probe = add("media.probe");
    const extract = add("media.extract_subtitles");
    connect(probe, extract, "probe", "probe");
    useEditorStore.getState().removeNodes([probe]);
    expect(useEditorStore.getState().nodes.map((node) => node.id)).toEqual([extract]);
    expect(useEditorStore.getState().edges).toHaveLength(0);
  });

  it("修改后进入 dirty，保存后回到干净状态", () => {
    expect(isEditorDirty(useEditorStore.getState())).toBe(false);

    add("media.probe");
    expect(isEditorDirty(useEditorStore.getState())).toBe(true);

    useEditorStore.getState().markSaved();
    expect(useEditorStore.getState().saveState).toBe("saved");
    expect(useEditorStore.getState().savedAt).not.toBeNull();
    expect(isEditorDirty(useEditorStore.getState())).toBe(false);
  });
});

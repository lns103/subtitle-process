import { describe, expect, it } from "vitest";

import type { EditorEdge, EditorNode } from "./editorTypes";
import { edgeId } from "./editorTypes";
import type {
  JsonSchema,
  RecipeDefinition,
  StepSpec,
  StepSpecPort,
  ValidationIssue,
} from "./models";
import {
  connectionIssue,
  defaultStepOptions,
  edgeIdsForIssue,
  issueCountsByStep,
  layoutGraph,
  nodesAndEdgesFromRecipe,
  portCompatible,
  RECIPE_INPUT_HANDLE,
  recipeFromGraph,
  recipeInputNodesAndEdges,
  stripRecipeUi,
  topologicalOrder,
  uniqueStepId,
} from "./recipeGraph";

function port(kind: string, required = true, multiple = false): StepSpecPort {
  return { kind, required, multiple };
}

function spec(
  id: string,
  inputs: Record<string, StepSpecPort> = {},
  outputs: Record<string, StepSpecPort> = {},
  optionsSchema: JsonSchema = {},
): StepSpec {
  return {
    id,
    title: `标题 ${id}`,
    description: "",
    inputs,
    outputs,
    options_schema: optionsSchema,
    requires_agent: false,
    deterministic: true,
  };
}

function node(
  id: string,
  uses: string,
  options: Record<string, unknown> = {},
  position: { x: number; y: number } = { x: 0, y: 0 },
  when: string | null = null,
): EditorNode {
  return {
    id,
    type: "step",
    position,
    data: { uses, title: uses, options, when },
  };
}

function edge(
  source: string,
  sourceHandle: string | null,
  target: string,
  targetHandle: string | null,
): EditorEdge {
  return {
    id: edgeId(source, sourceHandle, target, targetHandle),
    source,
    target,
    sourceHandle,
    targetHandle,
  };
}

const PROBE = spec("media.probe", {}, { video: port("video") });
const EXTRACT = spec("media.extract_subtitles", { video: port("video") }, {
  subtitle: port("subtitle"),
});
const NORMALIZE = spec(
  "sub.normalize",
  { subtitle: port("subtitle"), video: port("video") },
  { subtitle: port("subtitle") },
);
const EXPORT = spec("sub.export", { subtitle: port("subtitle") }, {
  file: port("file"),
});

describe("defaultStepOptions", () => {
  it("读取 $defs、anyOf 与嵌套默认值，忽略无默认字段", () => {
    const schema: JsonSchema = {
      type: "object",
      properties: {
        track: { type: "string", default: "auto" },
        prefer_embedded: { type: "boolean", default: true },
        nested: { type: "object", default: { rules: ["a", "b"], depth: 2 } },
        without_default: { type: "number" },
        nullable: { anyOf: [{ type: "string" }, { type: "null" }], default: null },
        mode: { anyOf: [{ type: "string", default: "fast" }, { type: "null" }] },
        lang: { $ref: "#/$defs/Lang" },
      },
      required: ["without_default"],
      $defs: {
        Lang: { type: "string", default: "zh" },
      },
    };

    const options = defaultStepOptions(spec("x", {}, {}, schema));
    expect(options).toEqual({
      track: "auto",
      prefer_embedded: true,
      nested: { rules: ["a", "b"], depth: 2 },
      nullable: null,
      mode: "fast",
      lang: "zh",
    });
    expect("without_default" in options).toBe(false);
  });

  it("返回深拷贝，修改结果不影响 schema", () => {
    const schema: JsonSchema = {
      type: "object",
      properties: { nested: { type: "object", default: { rules: ["a"] } } },
    };
    const options = defaultStepOptions(spec("x", {}, {}, schema));
    const nested = options.nested as { rules: string[] };
    nested.rules.push("b");
    expect(schema).toEqual({
      type: "object",
      properties: { nested: { type: "object", default: { rules: ["a"] } } },
    });
  });
});

describe("uniqueStepId", () => {
  it("取 uses 最后一段并清洗非法字符", () => {
    expect(uniqueStepId("media.probe", [])).toBe("probe");
    expect(uniqueStepId("sub.clean-up", [])).toBe("clean_up");
    expect(uniqueStepId("a.b.c", [])).toBe("c");
  });

  it("冲突时追加 _2、_3", () => {
    expect(uniqueStepId("media.probe", ["probe"])).toBe("probe_2");
    expect(uniqueStepId("media.probe", new Set(["probe", "probe_2"]))).toBe("probe_3");
  });
});

describe("端口兼容与连线校验", () => {
  it("相同类型或 any 兼容", () => {
    expect(portCompatible("video", "video")).toBe(true);
    expect(portCompatible("any", "subtitle")).toBe(true);
    expect(portCompatible("video", "any")).toBe(true);
    expect(portCompatible("video", "subtitle")).toBe(false);
  });

  it("connectionIssue 放行兼容连线并拒绝不兼容/未知端口", () => {
    const specsById: Record<string, StepSpec> = {
      probe: PROBE,
      extract: spec(
        "media.extract_subtitles",
        { video: port("video"), extra: port("any") },
        { subtitle: port("subtitle") },
      ),
      normalize: NORMALIZE,
    };

    expect(
      connectionIssue(
        { source: "probe", target: "extract", sourceHandle: "video", targetHandle: "video" },
        specsById,
      ),
    ).toBeNull();

    expect(
      connectionIssue(
        { source: "probe", target: "extract", sourceHandle: "video", targetHandle: "extra" },
        specsById,
      ),
    ).toBeNull();

    const mismatch = connectionIssue(
      { source: "extract", target: "normalize", sourceHandle: "subtitle", targetHandle: "video" },
      specsById,
    );
    expect(mismatch).toContain("不兼容");

    expect(
      connectionIssue(
        { source: "probe", target: "extract", sourceHandle: "missing", targetHandle: "video" },
        specsById,
      ),
    ).toContain("没有输出端口");
  });
});

describe("配方与画布互转", () => {
  const recipe: RecipeDefinition = {
    id: "demo",
    name: "演示",
    version: 2,
    description: "desc",
    builtin: false,
    inputs: [{ name: "video", kind: "file", accept: [".mkv"], required: true }],
    steps: [
      {
        id: "probe",
        uses: "media.probe",
        needs: [],
        when: null,
        with: {},
        ui: { x: 40, y: 80 },
      },
      {
        id: "extract",
        uses: "media.extract_subtitles",
        needs: ["probe"],
        when: null,
        with: { track: "auto", prefer_embedded: true },
        ui: { x: 400, y: 80 },
      },
      {
        id: "normalize",
        uses: "sub.normalize",
        needs: ["extract"],
        when: null,
        with: { merge_short: true },
        ui: { x: 800, y: 80 },
      },
      {
        id: "export",
        uses: "sub.export",
        needs: ["normalize"],
        when: "${options.enabled}",
        with: { format: "srt" },
        ui: { x: 1200, y: 80 },
      },
    ],
    outputs: [{ from: "export", key: "file" }],
    ui: { zoom: 1 },
  };

  it("nodesAndEdgesFromRecipe 使用 ui 坐标并按端口类型连线", () => {
    const { nodes, edges } = nodesAndEdgesFromRecipe(recipe, [PROBE, EXTRACT, NORMALIZE, EXPORT]);

    expect(nodes.map((item) => item.id)).toEqual(["probe", "extract", "normalize", "export"]);
    expect(nodes[0].position).toEqual({ x: 40, y: 80 });
    expect(nodes[3].position).toEqual({ x: 1200, y: 80 });
    expect(nodes[1].data.title).toBe("标题 media.extract_subtitles");
    expect(nodes[1].data.options).toEqual({ track: "auto", prefer_embedded: true });

    expect(edges).toHaveLength(3);
    expect(edges[0]).toMatchObject({
      id: edgeId("probe", "video", "extract", "video"),
      source: "probe",
      target: "extract",
      sourceHandle: "video",
      targetHandle: "video",
    });
    expect(edges[2].targetHandle).toBe("subtitle");
  });

  it("缺少 ui 坐标的节点由布局补全", () => {
    const unpositioned: RecipeDefinition = {
      ...recipe,
      steps: recipe.steps.map((step) => ({ ...step, ui: {} })),
    };
    const { nodes, edges } = nodesAndEdgesFromRecipe(unpositioned, [PROBE, EXTRACT, NORMALIZE, EXPORT]);
    for (const item of nodes) {
      expect(Number.isFinite(item.position.x)).toBe(true);
      expect(Number.isFinite(item.position.y)).toBe(true);
    }
    const probe = nodes.find((item) => item.id === "probe");
    const extract = nodes.find((item) => item.id === "extract");
    expect(probe && extract && extract.position.x > probe.position.x).toBe(true);
    expect(edges).toHaveLength(3);
  });

  it("同一对步骤按兼容端口画出多条边", () => {
    const scan = spec(
      "sub.sdh_scan",
      {},
      { candidates: port("sdh_candidates"), subs: port("srt") },
    );
    const review = spec(
      "human.review",
      { subs: port("srt"), candidates: port("sdh_candidates", false) },
      { subs: port("srt") },
    );
    const scanReview: RecipeDefinition = {
      id: "scan_review",
      name: "扫描审核",
      version: 1,
      description: "",
      builtin: false,
      inputs: [
        { name: "video", kind: "file", accept: [".mkv"], required: true },
        {
          name: "original",
          label: "原版字幕",
          kind: "files",
          accept: [".srt"],
          required: true,
          bind: [{ step: "review", port: "candidates" }],
        },
      ],
      steps: [
        { id: "scan", uses: "sub.sdh_scan", needs: [], when: null, with: {}, ui: { x: 0, y: 0 } },
        {
          id: "review",
          uses: "human.review",
          needs: ["scan"],
          when: null,
          with: {},
          ui: { x: 320, y: 0 },
        },
      ],
      outputs: [],
      ui: {},
    };

    const { nodes, edges } = nodesAndEdgesFromRecipe(scanReview, [scan, review]);
    expect(edges.map((edge) => edge.id)).toEqual(
      expect.arrayContaining([
        edgeId("scan", "candidates", "review", "candidates"),
        edgeId("scan", "subs", "review", "subs"),
      ]),
    );

    const inputGraph = recipeInputNodesAndEdges(scanReview.inputs, nodes, edges);
    expect(inputGraph.nodes.map((node) => node.data.name)).toEqual(["video", "original"]);
    expect(inputGraph.nodes[1].data).toMatchObject({
      label: "原版字幕",
      bound: true,
    });
    expect(inputGraph.edges).toEqual(
      expect.arrayContaining([
        expect.objectContaining({
          source: "input:video",
          target: "scan",
          targetHandle: RECIPE_INPUT_HANDLE,
        }),
        expect.objectContaining({
          source: "input:original",
          target: "review",
          targetHandle: "candidates",
        }),
      ]),
    );
  });

  it("recipeFromGraph 回写 needs/options/ui 并生成叶子输出", () => {
    const { nodes, edges } = nodesAndEdgesFromRecipe(recipe, [PROBE, EXTRACT, NORMALIZE, EXPORT]);
    const { recipe: rebuilt, cycle } = recipeFromGraph(
      {
        id: recipe.id,
        name: recipe.name,
        version: recipe.version,
        description: recipe.description,
        inputs: recipe.inputs,
        ui: recipe.ui,
      },
      nodes,
      edges,
      [PROBE, EXTRACT, NORMALIZE, EXPORT],
    );

    expect(cycle).toBeNull();
    expect(rebuilt.steps.map((step) => step.id)).toEqual([
      "probe",
      "extract",
      "normalize",
      "export",
    ]);
    expect(rebuilt.steps[1].needs).toEqual(["probe"]);
    expect(rebuilt.steps[1].with).toEqual({ track: "auto", prefer_embedded: true });
    expect(rebuilt.steps[1].ui).toEqual({ x: 400, y: 80 });
    expect(rebuilt.steps[3].when).toBe("${options.enabled}");
    expect(rebuilt.outputs).toEqual([{ from: "export", key: "file" }]);
    expect(rebuilt.ui).toEqual({ zoom: 1 });
    expect(rebuilt.builtin).toBe(false);
  });

  it("recipeFromGraph 按拓扑序输出步骤，needs 去重", () => {
    const nodes = [node("b", "sub.normalize"), node("a", "media.probe")];
    const edges = [edge("a", "video", "b", "subtitle"), edge("a", "video", "b", "subtitle")];
    const { recipe: rebuilt } = recipeFromGraph(
      { id: "r", name: "R", version: 1, description: "", inputs: [] },
      nodes,
      edges,
    );
    expect(rebuilt.steps.map((step) => step.id)).toEqual(["a", "b"]);
    expect(rebuilt.steps[1].needs).toEqual(["a"]);
    expect(rebuilt.outputs).toEqual([]);
  });

  it("有环时返回环节点列表", () => {
    const nodes = [node("a", "sub.normalize"), node("b", "sub.normalize")];
    const edges = [edge("a", "subtitle", "b", "subtitle"), edge("b", "subtitle", "a", "subtitle")];

    expect(topologicalOrder(nodes, edges)).toBeNull();
    const { cycle } = recipeFromGraph(
      { id: "r", name: "R", version: 1, description: "", inputs: [] },
      nodes,
      edges,
    );
    expect(cycle).toEqual(["a", "b", "a"]);
  });
});

describe("layoutGraph", () => {
  const nodes = [
    node("a", "media.probe"),
    node("b", "media.extract_subtitles"),
    node("c", "sub.normalize"),
  ];
  const edges = [edge("a", "video", "b", "video"), edge("b", "subtitle", "c", "subtitle")];

  it("LR 布局按层级从左到右且坐标有限", () => {
    const laidOut = layoutGraph(nodes, edges);
    const x = laidOut.map((item) => item.position.x);
    expect(x.every((value) => Number.isFinite(value))).toBe(true);
    expect(x[0]).toBeLessThan(x[1]);
    expect(x[1]).toBeLessThan(x[2]);
    expect(laidOut[0].position.y).toBeCloseTo(laidOut[1].position.y, 5);
  });

  it("TB 方向改为纵向层级", () => {
    const laidOut = layoutGraph(nodes, edges, "TB");
    expect(laidOut[0].position.y).toBeLessThan(laidOut[1].position.y);
    expect(laidOut[1].position.y).toBeLessThan(laidOut[2].position.y);
  });

  it("结果确定且不修改输入", () => {
    const first = layoutGraph(nodes, edges);
    const second = layoutGraph(nodes, edges);
    expect(first).toEqual(second);
    expect(nodes.every((item) => item.position.x === 0 && item.position.y === 0)).toBe(true);
  });
});

describe("stripRecipeUi", () => {
  it("移除顶层与步骤 ui，且不修改输入", () => {
    const recipe: RecipeDefinition = {
      id: "r",
      name: "R",
      version: 1,
      description: "",
      builtin: true,
      inputs: [],
      steps: [
        {
          id: "a",
          uses: "media.probe",
          needs: [],
          when: null,
          with: { x: 1 },
          ui: { x: 10, y: 20 },
        },
      ],
      outputs: [{ from: "a", key: "video" }],
      ui: { zoom: 0.8 },
    };
    const before = JSON.stringify(recipe);

    const stripped = stripRecipeUi(recipe);
    expect("ui" in stripped).toBe(false);
    expect("ui" in stripped.steps[0]).toBe(false);
    expect(stripped.steps[0].with).toEqual({ x: 1 });
    expect(stripped.steps[0].needs).toEqual([]);

    // 修改返回对象不应影响原配方。
    (stripped.steps[0].with as Record<string, unknown>).x = 2;
    expect(JSON.stringify(recipe)).toBe(before);
  });
});

describe("校验问题定位", () => {
  it("issueCountsByStep 按步骤统计错误与警告", () => {
    const issues: ValidationIssue[] = [
      { severity: "error", code: "invalid_options", message: "x", step_id: "a" },
      { severity: "warning", code: "agent_not_configured", message: "y", step_id: "a" },
      { severity: "error", code: "missing_required_input", message: "z", step_id: "b" },
      { severity: "error", code: "empty_recipe", message: "全局" },
    ];
    expect(issueCountsByStep(issues)).toEqual({
      a: { errors: 1, warnings: 1 },
      b: { errors: 1, warnings: 0 },
    });
  });

  it("端口问题高亮指向该端口的入边", () => {
    const edges = [
      edge("a", "video", "b", "video"),
      edge("a", "subtitle", "b", "subtitle"),
      edge("b", "subtitle", "c", "subtitle"),
    ];
    const issue: ValidationIssue = {
      severity: "error",
      code: "incompatible_port",
      message: "端口不兼容",
      step_id: "b",
      port: "video",
    };
    expect(edgeIdsForIssue(issue, edges)).toEqual([edgeId("a", "video", "b", "video")]);
  });

  it("环问题高亮环上的边（支持闭合与未闭合列表）", () => {
    const edges = [
      edge("a", "subtitle", "b", "subtitle"),
      edge("b", "subtitle", "c", "subtitle"),
      edge("c", "subtitle", "a", "subtitle"),
      edge("a", "subtitle", "x", "subtitle"),
    ];
    const closed: ValidationIssue = {
      severity: "error",
      code: "cycle",
      message: "环",
      data: { cycle: ["a", "b", "c", "a"] },
    };
    expect(edgeIdsForIssue(closed, edges)).toEqual([
      edgeId("a", "subtitle", "b", "subtitle"),
      edgeId("b", "subtitle", "c", "subtitle"),
      edgeId("c", "subtitle", "a", "subtitle"),
    ]);

    const open: ValidationIssue = {
      severity: "error",
      code: "cycle",
      message: "环",
      data: { cycle: ["a", "b", "c"] },
    };
    expect(edgeIdsForIssue(open, edges)).toHaveLength(3);
  });

  it("其他问题返回空数组", () => {
    const issue: ValidationIssue = {
      severity: "error",
      code: "unknown_step",
      message: "未知步骤",
      step_id: "a",
    };
    expect(edgeIdsForIssue(issue, [edge("a", "video", "b", "video")])).toEqual([]);
  });
});

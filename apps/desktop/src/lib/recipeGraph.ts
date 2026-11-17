/**
 * 配方（Recipe）与 React Flow 画布之间的互转、自动布局与校验辅助。
 *
 * 画布数据只保存配方语义（`uses` / `options` / `when` / 坐标），
 * 端口名编码在边的 handle 上，`needs` 由边推导，保证与引擎协议一致。
 */

import { graphlib, layout } from "dagre";

import type { EditorEdge, EditorNode } from "./editorTypes";
import { edgeId } from "./editorTypes";
import type {
  JsonSchema,
  RecipeDefinition,
  RecipeInput,
  RecipeOutput,
  RecipeStep,
  StepSpec,
  ValidationIssue,
} from "./models";

/** 画布节点默认尺寸，供布局与 dagre 使用。 */
const NODE_WIDTH = 230;
const NODE_HEIGHT = 100;
const NODE_SEP = 60;
const RANK_SEP = 120;

function asRecord(value: unknown): Record<string, unknown> | null {
  return value !== null && typeof value === "object" && !Array.isArray(value)
    ? (value as Record<string, unknown>)
    : null;
}

/** 深拷贝 JSON 值；undefined 原样返回，避免污染默认值对象。 */
function cloneJson<T>(value: T): T {
  if (value === undefined) {
    return value;
  }
  return JSON.parse(JSON.stringify(value)) as T;
}

/** 解析 `#/$defs/Name` / `#/definitions/Name` 形式的本地引用。 */
function resolveRef(ref: string, root: JsonSchema): JsonSchema | null {
  if (!ref.startsWith("#/")) {
    return null;
  }
  let current: unknown = root;
  for (const rawPart of ref.slice(2).split("/")) {
    const part = rawPart.replace(/~1/g, "/").replace(/~0/g, "~");
    const record = asRecord(current);
    if (!record || !(part in record)) {
      return null;
    }
    current = record[part];
  }
  return asRecord(current);
}

/** 展开 `$ref`；同级的其他键覆盖被引用 schema 的同名字段。 */
function resolveSchema(
  schema: JsonSchema,
  root: JsonSchema,
  seen: Set<string> = new Set(),
): JsonSchema {
  const ref = schema.$ref;
  if (typeof ref !== "string" || seen.has(ref)) {
    return schema;
  }
  const target = resolveRef(ref, root);
  if (!target) {
    return schema;
  }
  const rest: JsonSchema = { ...schema };
  delete rest.$ref;
  const merged: JsonSchema = { ...target, ...rest };
  return resolveSchema(merged, root, new Set([...seen, ref]));
}

/** 从 schema（含 anyOf/oneOf/allOf 分支）中寻找显式默认值。 */
function findDefault(
  schema: JsonSchema,
  root: JsonSchema,
  depth = 0,
): { found: boolean; value?: unknown } {
  if (depth > 8) {
    return { found: false };
  }
  const resolved = resolveSchema(schema, root);
  if (Object.prototype.hasOwnProperty.call(resolved, "default")) {
    return { found: true, value: resolved.default };
  }
  for (const key of ["anyOf", "oneOf", "allOf"]) {
    const branches = resolved[key];
    if (!Array.isArray(branches)) {
      continue;
    }
    for (const branch of branches) {
      const record = asRecord(branch);
      if (!record) {
        continue;
      }
      const result = findDefault(record, root, depth + 1);
      if (result.found) {
        return result;
      }
    }
  }
  return { found: false };
}

/** 从 Pydantic 生成的 JSON Schema 中取属性默认值。 */
export function defaultStepOptions(spec: StepSpec): Record<string, unknown> {
  const root = spec.options_schema ?? {};
  const resolved = resolveSchema(root, root);
  const properties = asRecord(resolved.properties);
  if (!properties) {
    return {};
  }

  const options: Record<string, unknown> = {};
  for (const [key, value] of Object.entries(properties)) {
    const propertySchema = asRecord(value);
    if (!propertySchema) {
      continue;
    }
    const result = findDefault(propertySchema, root);
    if (result.found) {
      options[key] = cloneJson(result.value);
    }
  }
  return options;
}

function sanitizeStepId(raw: string): string {
  const cleaned = raw
    .replace(/[^A-Za-z0-9_]+/g, "_")
    .replace(/^_+/, "")
    .replace(/_+$/, "");
  return cleaned || "step";
}

/** 由 "media.probe" 生成 "probe"，冲突时追加 _2/_3；保证只含 [A-Za-z0-9_]。 */
export function uniqueStepId(uses: string, existing: Iterable<string>): string {
  const segments = uses.split(".").filter((segment) => segment.length > 0);
  const base = sanitizeStepId(segments[segments.length - 1] ?? uses);
  const used = new Set(existing);
  if (!used.has(base)) {
    return base;
  }
  let index = 2;
  while (used.has(`${base}_${index}`)) {
    index += 1;
  }
  return `${base}_${index}`;
}

/** 端口类型兼容：相同 kind，或任意一侧为 "any"。 */
export function portCompatible(outputKind: string, inputKind: string): boolean {
  return outputKind === inputKind || outputKind === "any" || inputKind === "any";
}

/**
 * 根据步骤注册表校验一条连线的端口类型。
 *
 * `specsById` 以画布节点 id 为键（调用方用节点的 `uses` 查注册表后映射）。
 * 缺端口名且该侧只有单个端口时自动采用；无法判断时返回 null（放行）。
 */
export function connectionIssue(
  connection: {
    source: string;
    target: string;
    sourceHandle?: string | null;
    targetHandle?: string | null;
  },
  specsById: Record<string, StepSpec>,
): string | null {
  const { source, target } = connection;
  const sourceSpec: StepSpec | undefined = specsById[source];
  const targetSpec: StepSpec | undefined = specsById[target];

  let sourceName = connection.sourceHandle ?? null;
  let targetName = connection.targetHandle ?? null;

  if (sourceSpec && sourceName === null) {
    const names = Object.keys(sourceSpec.outputs);
    if (names.length === 1) {
      sourceName = names[0];
    }
  }
  if (targetSpec && targetName === null) {
    const names = Object.keys(targetSpec.inputs);
    if (names.length === 1) {
      targetName = names[0];
    }
  }

  if (sourceSpec && sourceName !== null && !sourceSpec.outputs[sourceName]) {
    return `步骤「${source}」没有输出端口「${sourceName}」`;
  }
  if (targetSpec && targetName !== null && !targetSpec.inputs[targetName]) {
    return `步骤「${target}」没有输入端口「${targetName}」`;
  }
  if (!sourceSpec || !targetSpec || sourceName === null || targetName === null) {
    return null;
  }

  const output = sourceSpec.outputs[sourceName];
  const input = targetSpec.inputs[targetName];
  if (!output || !input) {
    return null;
  }
  if (!portCompatible(output.kind, input.kind)) {
    return `端口类型不兼容：「${source}」的 ${sourceName}（${output.kind}）→「${target}」的 ${targetName}（${input.kind}）`;
  }
  return null;
}

function uiPosition(ui: Record<string, unknown> | undefined): { x: number; y: number } | null {
  if (!ui) {
    return null;
  }
  const { x, y } = ui;
  if (typeof x === "number" && Number.isFinite(x) && typeof y === "number" && Number.isFinite(y)) {
    return { x, y };
  }
  return null;
}

/** 在两端步骤之间挑一对类型兼容的端口；无兼容端口时退回名称排序第一项。 */
function choosePorts(
  sourceSpec: StepSpec | undefined,
  targetSpec: StepSpec | undefined,
): { sourceHandle: string | null; targetHandle: string | null; kind: string | null } {
  if (!sourceSpec || !targetSpec) {
    return { sourceHandle: null, targetHandle: null, kind: null };
  }

  const outputs = Object.keys(sourceSpec.outputs).sort();
  const inputs = Object.keys(targetSpec.inputs).sort((left, right) => {
    const leftRequired = targetSpec.inputs[left]?.required ? 0 : 1;
    const rightRequired = targetSpec.inputs[right]?.required ? 0 : 1;
    return leftRequired - rightRequired || left.localeCompare(right);
  });

  for (const inputName of inputs) {
    for (const outputName of outputs) {
      if (portCompatible(sourceSpec.outputs[outputName].kind, targetSpec.inputs[inputName].kind)) {
        return {
          sourceHandle: outputName,
          targetHandle: inputName,
          kind: sourceSpec.outputs[outputName].kind,
        };
      }
    }
  }

  const sourceHandle = outputs[0] ?? null;
  return {
    sourceHandle,
    targetHandle: inputs[0] ?? null,
    kind: sourceHandle ? sourceSpec.outputs[sourceHandle].kind : null,
  };
}

/** 由配方生成画布节点/边；步骤自带 ui.x/ui.y 时采用，否则自动布局。 */
export function nodesAndEdgesFromRecipe(
  recipe: RecipeDefinition,
  specs: StepSpec[],
): { nodes: EditorNode[]; edges: EditorEdge[] } {
  const specByUses = new Map(specs.map((spec) => [spec.id, spec]));
  const stepById = new Map(recipe.steps.map((step) => [step.id, step]));

  const nodes: EditorNode[] = recipe.steps.map((step) => {
    const spec = specByUses.get(step.uses);
    return {
      id: step.id,
      type: "step",
      position: { x: 0, y: 0 },
      data: {
        uses: step.uses,
        title: spec?.title ?? step.uses,
        options: cloneJson(step.with ?? {}),
        when: step.when ?? null,
      },
    };
  });

  const edges: EditorEdge[] = [];
  const emitted = new Set<string>();
  for (const step of recipe.steps) {
    const targetSpec = specByUses.get(step.uses);
    for (const sourceId of new Set(step.needs ?? [])) {
      const sourceStep = stepById.get(sourceId);
      if (!sourceStep) {
        continue;
      }
      const sourceSpec = specByUses.get(sourceStep.uses);
      const ports = choosePorts(sourceSpec, targetSpec);
      const id = edgeId(sourceId, ports.sourceHandle, step.id, ports.targetHandle);
      if (emitted.has(id)) {
        continue;
      }
      emitted.add(id);
      edges.push({
        id,
        source: sourceId,
        target: step.id,
        sourceHandle: ports.sourceHandle,
        targetHandle: ports.targetHandle,
        data: { kind: ports.kind ?? undefined },
      });
    }
  }

  const positioned = layoutGraph(nodes, edges);
  return {
    nodes: nodes.map((node, index) => {
      const position = uiPosition(stepById.get(node.id)?.ui);
      return position ? { ...node, position } : positioned[index];
    }),
    edges,
  };
}

/**
 * 由画布生成配方；needs 从边推导并按拓扑排序。
 *
 * 可选 `specs` 用于为无出边的叶子步骤生成配方输出；省略时 `outputs` 为空。
 * 有环时 `cycle` 为环节点 id 列表（首尾相同），`recipe` 仍按画布顺序返回。
 */
export function recipeFromGraph(
  meta: {
    id: string;
    name: string;
    version: number;
    description: string;
    inputs: RecipeInput[];
    ui?: Record<string, unknown>;
  },
  nodes: EditorNode[],
  edges: EditorEdge[],
  specs?: StepSpec[],
): { recipe: RecipeDefinition; cycle: string[] | null } {
  const nodeById = new Map(nodes.map((node) => [node.id, node]));
  const order = topologicalOrder(nodes, edges);
  const cycle = order ? null : findCycle(nodes, edges);

  const needsByStep = new Map<string, string[]>();
  for (const node of nodes) {
    needsByStep.set(node.id, []);
  }
  for (const edge of edges) {
    if (!nodeById.has(edge.source) || !nodeById.has(edge.target)) {
      continue;
    }
    const needs = needsByStep.get(edge.target);
    if (needs && !needs.includes(edge.source)) {
      needs.push(edge.source);
    }
  }

  if (order) {
    const rank = new Map(order.map((id, index) => [id, index]));
    for (const needs of needsByStep.values()) {
      needs.sort((left, right) => (rank.get(left) ?? 0) - (rank.get(right) ?? 0));
    }
  }

  const orderedNodes = order
    ? order
        .map((id) => nodeById.get(id))
        .filter((node): node is EditorNode => node !== undefined)
    : nodes;

  const steps: RecipeStep[] = orderedNodes.map((node) => ({
    id: node.id,
    uses: node.data.uses,
    needs: [...(needsByStep.get(node.id) ?? [])],
    when: node.data.when ?? null,
    with: cloneJson(node.data.options ?? {}),
    ui: { x: node.position.x, y: node.position.y },
  }));

  const outputs: RecipeOutput[] = [];
  if (specs) {
    const specByUses = new Map(specs.map((spec) => [spec.id, spec]));
    const sources = new Set(edges.map((edge) => edge.source));
    for (const node of orderedNodes) {
      if (sources.has(node.id)) {
        continue;
      }
      const spec = specByUses.get(node.data.uses);
      if (!spec) {
        continue;
      }
      for (const key of Object.keys(spec.outputs).sort()) {
        outputs.push({ from: node.id, key });
      }
    }
  }

  return {
    recipe: {
      id: meta.id,
      name: meta.name,
      version: meta.version,
      description: meta.description,
      builtin: false,
      inputs: cloneJson(meta.inputs),
      steps,
      outputs,
      ui: cloneJson(meta.ui ?? {}),
    },
    cycle,
  };
}

/** dagre 自动布局（默认从左到右），返回带新 position 的节点数组。 */
export function layoutGraph(
  nodes: EditorNode[],
  edges: EditorEdge[],
  direction: "LR" | "TB" = "LR",
): EditorNode[] {
  if (nodes.length === 0) {
    return [];
  }

  const graph = new graphlib.Graph();
  graph.setGraph({
    rankdir: direction,
    nodesep: NODE_SEP,
    ranksep: RANK_SEP,
    marginx: 0,
    marginy: 0,
  });
  graph.setDefaultEdgeLabel(() => ({}));
  for (const node of nodes) {
    graph.setNode(node.id, { width: NODE_WIDTH, height: NODE_HEIGHT });
  }
  for (const edge of edges) {
    if (edge.source === edge.target) {
      continue;
    }
    if (!graph.hasNode(edge.source) || !graph.hasNode(edge.target)) {
      continue;
    }
    graph.setEdge(edge.source, edge.target);
  }

  layout(graph);

  return nodes.map((node) => {
    const point = graph.node(node.id);
    return {
      ...node,
      position: {
        x: point.x - NODE_WIDTH / 2,
        y: point.y - NODE_HEIGHT / 2,
      },
    };
  });
}

/** 拓扑序；有环返回 null。 */
export function topologicalOrder(nodes: EditorNode[], edges: EditorEdge[]): string[] | null {
  const index = new Map<string, number>();
  nodes.forEach((node, position) => {
    if (!index.has(node.id)) {
      index.set(node.id, position);
    }
  });

  const indegree = new Map<string, number>();
  const adjacency = new Map<string, string[]>();
  for (const id of index.keys()) {
    indegree.set(id, 0);
    adjacency.set(id, []);
  }

  const seen = new Set<string>();
  for (const edge of edges) {
    if (!index.has(edge.source) || !index.has(edge.target)) {
      continue;
    }
    const key = `${edge.source}\u0000${edge.target}`;
    if (seen.has(key)) {
      continue;
    }
    seen.add(key);
    adjacency.get(edge.source)?.push(edge.target);
    indegree.set(edge.target, (indegree.get(edge.target) ?? 0) + 1);
  }

  const byIndex = (left: string, right: string): number =>
    (index.get(left) ?? 0) - (index.get(right) ?? 0);

  const ready = [...indegree.entries()]
    .filter(([, degree]) => degree === 0)
    .map(([id]) => id)
    .sort(byIndex);

  const result: string[] = [];
  while (ready.length > 0) {
    const id = ready.shift();
    if (id === undefined) {
      break;
    }
    result.push(id);
    for (const next of adjacency.get(id) ?? []) {
      const degree = (indegree.get(next) ?? 0) - 1;
      indegree.set(next, degree);
      if (degree === 0) {
        let insertAt = ready.length;
        for (let i = 0; i < ready.length; i += 1) {
          if (byIndex(next, ready[i]) < 0) {
            insertAt = i;
            break;
          }
        }
        ready.splice(insertAt, 0, next);
      }
    }
  }

  return result.length === index.size ? result : null;
}

/** 找到一个环（首尾相同，便于高亮环边）；无环返回 null。 */
function findCycle(nodes: EditorNode[], edges: EditorEdge[]): string[] | null {
  const known = new Set(nodes.map((node) => node.id));
  const adjacency = new Map<string, string[]>();
  for (const node of nodes) {
    adjacency.set(node.id, []);
  }
  for (const edge of edges) {
    if (!known.has(edge.source) || !known.has(edge.target)) {
      continue;
    }
    const targets = adjacency.get(edge.source);
    if (targets && !targets.includes(edge.target)) {
      targets.push(edge.target);
    }
  }

  const state = new Map<string, 0 | 1 | 2>();
  const stack: string[] = [];

  const visit = (id: string): string[] | null => {
    state.set(id, 1);
    stack.push(id);
    for (const next of adjacency.get(id) ?? []) {
      const current = state.get(next) ?? 0;
      if (current === 1) {
        return [...stack.slice(stack.indexOf(next)), next];
      }
      if (current === 0) {
        const found = visit(next);
        if (found) {
          return found;
        }
      }
    }
    stack.pop();
    state.set(id, 2);
    return null;
  };

  for (const node of nodes) {
    if ((state.get(node.id) ?? 0) === 0) {
      const found = visit(node.id);
      if (found) {
        return found;
      }
    }
  }
  return null;
}

/**
 * 运行前剥离仅 UI 使用的字段（坐标等）。
 *
 * 返回的对象在运行时不再包含 `ui` 键（顶层与 step 均移除），
 * 但为了保持题面签名仍标注为 `RecipeDefinition`；调用前请勿读取其 `ui`。
 */
export function stripRecipeUi(recipe: RecipeDefinition): RecipeDefinition {
  const steps: Record<string, unknown>[] = recipe.steps.map((step) => ({
    id: step.id,
    uses: step.uses,
    needs: [...step.needs],
    when: step.when,
    with: cloneJson(step.with ?? {}),
  }));

  const stripped: Record<string, unknown> = {
    id: recipe.id,
    name: recipe.name,
    version: recipe.version,
    description: recipe.description,
    builtin: recipe.builtin,
    inputs: cloneJson(recipe.inputs),
    steps,
    outputs: recipe.outputs.map((output) => ({ from: output.from, key: output.key })),
  };
  return stripped as unknown as RecipeDefinition;
}

/** 每个步骤节点上的错误/警告数量，用于画布徽标。 */
export function issueCountsByStep(
  issues: ValidationIssue[],
): Record<string, { errors: number; warnings: number }> {
  const counts: Record<string, { errors: number; warnings: number }> = {};
  for (const issue of issues) {
    const stepId = issue.step_id;
    if (!stepId) {
      continue;
    }
    const entry = counts[stepId] ?? { errors: 0, warnings: 0 };
    if (issue.severity === "warning") {
      entry.warnings += 1;
    } else {
      entry.errors += 1;
    }
    counts[stepId] = entry;
  }
  return counts;
}

/** 某个校验问题应该高亮哪些边（端口问题高亮入边；环高亮环上的边）。 */
export function edgeIdsForIssue(issue: ValidationIssue, edges: EditorEdge[]): string[] {
  if (issue.code === "cycle") {
    const rawCycle = issue.data?.cycle;
    if (!Array.isArray(rawCycle)) {
      return [];
    }
    const cycle = rawCycle.filter((item): item is string => typeof item === "string");
    const pairs = new Set<string>();
    for (let i = 0; i < cycle.length - 1; i += 1) {
      pairs.add(`${cycle[i]}\u0000${cycle[i + 1]}`);
    }
    // 支持未闭合的环节点列表（引擎可能只给不重复节点）。
    if (cycle.length > 2 && cycle[0] !== cycle[cycle.length - 1]) {
      pairs.add(`${cycle[cycle.length - 1]}\u0000${cycle[0]}`);
    }
    return edges
      .filter((edge) => pairs.has(`${edge.source}\u0000${edge.target}`))
      .map((edge) => edge.id);
  }

  if (!issue.step_id || issue.port === null || issue.port === undefined) {
    return [];
  }
  return edges
    .filter((edge) => edge.target === issue.step_id && edge.targetHandle === issue.port)
    .map((edge) => edge.id);
}

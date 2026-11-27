import { useMemo } from "react";
import { CircleAlert, Copy, Plus, Trash2, TriangleAlert, Wrench } from "lucide-react";
import type {
  RecipeInput,
  RecipeInputKind,
  StepSpec,
  ValidationIssue,
} from "../../lib/models";
import { issueCountsByStep } from "../../lib/recipeGraph";
import { useEditorStore } from "../../stores/editorStore";
import { SchemaForm } from "./SchemaForm";

function IssueRow({ issue }: { issue: ValidationIssue }) {
  const Icon = issue.severity === "warning" ? TriangleAlert : CircleAlert;
  return (
    <li
      className={`flex gap-2 rounded-lg px-2 py-1.5 text-xs ${
        issue.severity === "warning"
          ? "bg-amber-50 text-amber-800"
          : "bg-red-50 text-red-700"
      }`}
    >
      <Icon className="mt-0.5 h-3.5 w-3.5 shrink-0" />
      <div className="min-w-0">
        <p className="break-words">{issue.message}</p>
        <p className="mt-0.5 font-mono text-[10px] opacity-70">
          {issue.code}
          {issue.step_id ? ` · ${issue.step_id}` : ""}
          {issue.port ? `.${issue.port}` : ""}
        </p>
      </div>
    </li>
  );
}

const INPUT_KIND_LABELS: Record<RecipeInputKind, string> = {
  file: "单文件",
  files: "多文件",
  folder: "文件夹",
};

function parseAccept(value: string): string[] {
  return value
    .split(/[,\s]+/)
    .map((item) => item.trim())
    .filter(Boolean)
    .map((item) => (item === "*" || item.startsWith(".") ? item : `.${item}`));
}

function InputsEditor() {
  const inputs = useEditorStore((state) => state.inputs);
  const nodes = useEditorStore((state) => state.nodes);
  const specs = useEditorStore((state) => state.specs);
  const setMeta = useEditorStore((state) => state.setMeta);

  const updateInput = (index: number, patch: Partial<RecipeInput>) => {
    setMeta({
      inputs: inputs.map((item, position) =>
        position === index ? { ...item, ...patch } : item,
      ),
    });
  };

  const removeInput = (index: number) => {
    setMeta({ inputs: inputs.filter((_, position) => position !== index) });
  };

  const addInput = () => {
    setMeta({
      inputs: [
        ...inputs,
        {
          name: `input_${inputs.length + 1}`,
          label: "",
          kind: "files",
          accept: [".srt", ".vtt"],
          required: true,
          multiple: true,
          bind: [],
        },
      ],
    });
  };

  const updateBinding = (
    index: number,
    bindIndex: number,
    patch: { step?: string; port?: string },
  ) => {
    const input = inputs[index];
    const bind = [...(input.bind ?? [])];
    bind[bindIndex] = { ...bind[bindIndex], ...patch };
    updateInput(index, { bind });
  };

  const addBinding = (index: number) => {
    const input = inputs[index];
    const firstNode = nodes[0];
    if (!firstNode) return;
    const spec = specs.find((item) => item.id === firstNode.data.uses);
    const port = spec ? Object.keys(spec.inputs)[0] : "";
    updateInput(index, {
      bind: [...(input.bind ?? []), { step: firstNode.id, port: port ?? "" }],
    });
  };

  const removeBinding = (index: number, bindIndex: number) => {
    const input = inputs[index];
    updateInput(index, {
      bind: (input.bind ?? []).filter((_, position) => position !== bindIndex),
    });
  };

  return (
    <div className="space-y-2">
      <div className="flex items-center justify-between">
        <span className="font-medium">配方输入</span>
        <button
          type="button"
          onClick={addInput}
          className="inline-flex items-center gap-1 rounded-lg border border-slate-200 px-2 py-1 text-[11px] text-slate-600 hover:bg-slate-50"
        >
          <Plus className="h-3 w-3" /> 添加输入
        </button>
      </div>
      {inputs.length === 0 ? (
        <p className="rounded-lg bg-slate-50 px-2.5 py-1.5 text-[11px] text-slate-400">
          没有命名输入；运行时可只传路径列表。
        </p>
      ) : null}
      {inputs.map((input, index) => {
        const bindingStepIds = new Set(nodes.map((node) => node.id));
        return (
          <div
            key={`${input.name}-${index}`}
            data-testid={`recipe-input-${index}`}
            className="space-y-2 rounded-lg border border-slate-200 bg-slate-50/60 p-2"
          >
            <div className="flex items-center justify-between text-[11px] text-slate-500">
              <span>输入 {index + 1}</span>
              <button
                type="button"
                title="删除输入"
                onClick={() => removeInput(index)}
                className="rounded p-1 text-slate-400 hover:bg-white hover:text-red-600"
              >
                <Trash2 className="h-3 w-3" />
              </button>
            </div>

            <div className="grid grid-cols-2 gap-2">
              <label className="space-y-1 text-[11px] text-slate-500">
                <span>名称</span>
                <input
                  value={input.name}
                  onChange={(event) => updateInput(index, { name: event.target.value })}
                  className="w-full rounded border border-slate-200 bg-white px-2 py-1 font-mono text-xs text-slate-700 outline-none focus:border-slate-400"
                />
              </label>
              <label className="space-y-1 text-[11px] text-slate-500">
                <span>显示名</span>
                <input
                  value={input.label ?? ""}
                  placeholder={input.name}
                  onChange={(event) => updateInput(index, { label: event.target.value })}
                  className="w-full rounded border border-slate-200 bg-white px-2 py-1 text-xs text-slate-700 outline-none focus:border-slate-400"
                />
              </label>
            </div>

            <div className="grid grid-cols-2 gap-2">
              <label className="space-y-1 text-[11px] text-slate-500">
                <span>类型</span>
                <select
                  value={input.kind}
                  onChange={(event) =>
                    updateInput(index, { kind: event.target.value as RecipeInputKind })
                  }
                  className="w-full rounded border border-slate-200 bg-white px-2 py-1 text-xs text-slate-700 outline-none focus:border-slate-400"
                >
                  {Object.entries(INPUT_KIND_LABELS).map(([kind, label]) => (
                    <option key={kind} value={kind}>
                      {label}
                    </option>
                  ))}
                </select>
              </label>
              <label className="space-y-1 text-[11px] text-slate-500">
                <span>接受扩展名</span>
                <input
                  value={input.accept.join(", ")}
                  placeholder=".srt, .vtt"
                  onChange={(event) =>
                    updateInput(index, { accept: parseAccept(event.target.value) })
                  }
                  className="w-full rounded border border-slate-200 bg-white px-2 py-1 font-mono text-xs text-slate-700 outline-none focus:border-slate-400"
                />
              </label>
            </div>

            <div className="flex flex-wrap items-center gap-3 text-[11px] text-slate-600">
              <label className="inline-flex items-center gap-1">
                <input
                  type="checkbox"
                  checked={input.required}
                  onChange={(event) =>
                    updateInput(index, { required: event.target.checked })
                  }
                  className="h-3.5 w-3.5 rounded border-slate-300"
                />
                必填
              </label>
              <label className="inline-flex items-center gap-1">
                <input
                  type="checkbox"
                  checked={input.multiple === true}
                  onChange={(event) =>
                    updateInput(index, { multiple: event.target.checked })
                  }
                  className="h-3.5 w-3.5 rounded border-slate-300"
                />
                允许多个
              </label>
            </div>

            <div className="space-y-1.5">
              <div className="flex items-center justify-between text-[11px] text-slate-500">
                <span>绑定端口</span>
                <button
                  type="button"
                  disabled={nodes.length === 0}
                  onClick={() => addBinding(index)}
                  className="text-[11px] text-slate-500 hover:text-slate-700 disabled:opacity-40"
                >
                  + 添加绑定
                </button>
              </div>
              {(input.bind ?? []).map((binding, bindIndex) => {
                const node = nodes.find((item) => item.id === binding.step);
                const spec = specs.find((item) => item.id === node?.data.uses);
                const ports = spec ? Object.keys(spec.inputs) : [];
                return (
                  <div
                    key={`${binding.step}-${bindIndex}`}
                    className="flex items-center gap-1.5"
                  >
                    <select
                      value={binding.step}
                      onChange={(event) => {
                        const step = event.target.value;
                        const nextNode = nodes.find((item) => item.id === step);
                        const nextSpec = specs.find(
                          (item) => item.id === nextNode?.data.uses,
                        );
                        const nextPort = nextSpec
                          ? (Object.keys(nextSpec.inputs)[0] ?? "")
                          : "";
                        updateBinding(index, bindIndex, { step, port: nextPort });
                      }}
                      className="min-w-0 flex-1 rounded border border-slate-200 bg-white px-1.5 py-1 text-[11px] text-slate-700"
                    >
                      {!bindingStepIds.has(binding.step) ? (
                        <option value={binding.step}>{binding.step}（缺失）</option>
                      ) : null}
                      {nodes.map((item) => (
                        <option key={item.id} value={item.id}>
                          {item.id} · {item.data.uses}
                        </option>
                      ))}
                    </select>
                    <select
                      value={binding.port}
                      onChange={(event) =>
                        updateBinding(index, bindIndex, { port: event.target.value })
                      }
                      className="min-w-0 flex-1 rounded border border-slate-200 bg-white px-1.5 py-1 text-[11px] text-slate-700"
                    >
                      {binding.port && !ports.includes(binding.port) ? (
                        <option value={binding.port}>{binding.port}（缺失）</option>
                      ) : null}
                      {ports.map((port) => (
                        <option key={port} value={port}>
                          {port}
                        </option>
                      ))}
                    </select>
                    <button
                      type="button"
                      title="删除绑定"
                      onClick={() => removeBinding(index, bindIndex)}
                      className="rounded p-1 text-slate-400 hover:bg-white hover:text-red-600"
                    >
                      <Trash2 className="h-3 w-3" />
                    </button>
                  </div>
                );
              })}
            </div>
          </div>
        );
      })}
    </div>
  );
}

function RecipeMetaForm() {
  const recipeId = useEditorStore((state) => state.recipeId);
  const name = useEditorStore((state) => state.name);
  const description = useEditorStore((state) => state.description);
  const builtin = useEditorStore((state) => state.builtin);
  const inputs = useEditorStore((state) => state.inputs);
  const ui = useEditorStore((state) => state.ui);
  const setMeta = useEditorStore((state) => state.setMeta);
  const issues = useEditorStore((state) => state.issues);
  const validationOk = useEditorStore((state) => state.validationOk);

  const acceptText = inputs.map((item) => item.accept.join(", ")).filter(Boolean).join(", ");
  const uiKind = typeof ui.kind === "string" ? ui.kind : "";
  const uiGroup = typeof ui.group === "string" ? ui.group : "";
  const uiOrder = typeof ui.order === "number" ? ui.order : 100;

  const updateUi = (patch: Record<string, unknown>) => {
    setMeta({ ui: { ...ui, ...patch } });
  };

  return (
    <div className="space-y-4 p-4">
      <div>
        <h3 className="flex items-center gap-2 text-sm font-semibold text-slate-800">
          <Wrench className="h-4 w-4" /> 配方信息
        </h3>
        <p className="mt-1 text-[11px] leading-relaxed text-slate-400">
          点击画布节点可编辑步骤参数。这里修改名称、id、描述、输入与首页展示方式；id
          只能包含字母、数字、_ . -。
        </p>
      </div>

      <label className="block space-y-1 text-xs text-slate-600">
        <span className="font-medium">名称</span>
        <input
          value={name}
          id="recipe-name"
          name="recipe-name"
          onChange={(event) => setMeta({ name: event.target.value })}
          className="w-full rounded-lg border border-slate-200 px-2.5 py-1.5 text-sm text-slate-800 outline-none focus:border-slate-400"
        />
      </label>

      <label className="block space-y-1 text-xs text-slate-600">
        <span className="flex items-center justify-between">
          <span className="font-medium">配方 id</span>
          {builtin ? <span className="text-[11px] text-amber-600">内置配方只读</span> : null}
        </span>
        <input
          value={recipeId}
          id="recipe-id"
          name="recipe-id"
          disabled={builtin}
          onChange={(event) => setMeta({ recipeId: event.target.value })}
          className="w-full rounded-lg border border-slate-200 px-2.5 py-1.5 font-mono text-xs text-slate-800 outline-none focus:border-slate-400 disabled:bg-slate-50 disabled:text-slate-400"
        />
      </label>

      <label className="block space-y-1 text-xs text-slate-600">
        <span className="font-medium">描述</span>
        <textarea
          value={description}
          id="recipe-description"
          name="recipe-description"
          rows={3}
          onChange={(event) => setMeta({ description: event.target.value })}
          className="w-full resize-none rounded-lg border border-slate-200 px-2.5 py-1.5 text-sm text-slate-800 outline-none focus:border-slate-400"
        />
      </label>

      {builtin ? (
        <div className="space-y-1 text-xs text-slate-600">
          <span className="font-medium">输入接受类型</span>
          <p className="rounded-lg bg-slate-50 px-2.5 py-1.5 font-mono text-[11px] text-slate-500">
            {acceptText || "任意文件"}
          </p>
        </div>
      ) : (
        <InputsEditor />
      )}

      <div className="space-y-2 rounded-lg border border-slate-200 p-2.5">
        <div className="text-xs font-semibold text-slate-700">首页任务目录</div>
        <div className="grid grid-cols-2 gap-2">
          <label className="space-y-1 text-[11px] text-slate-500">
            <span>显示为</span>
            <select
              value={uiKind}
              onChange={(event) => updateUi({ kind: event.target.value })}
              className="w-full rounded border border-slate-200 bg-white px-2 py-1 text-xs text-slate-700 outline-none focus:border-slate-400"
            >
              <option value="">不显示</option>
              <option value="workflow">流水线</option>
              <option value="function">单项功能</option>
            </select>
          </label>
          <label className="space-y-1 text-[11px] text-slate-500">
            <span>分组</span>
            <input
              value={uiGroup}
              placeholder="其他"
              onChange={(event) => updateUi({ group: event.target.value })}
              className="w-full rounded border border-slate-200 bg-white px-2 py-1 text-xs text-slate-700 outline-none focus:border-slate-400"
            />
          </label>
        </div>
        <label className="block space-y-1 text-[11px] text-slate-500">
          <span>排序（越小越靠前）</span>
          <input
            type="number"
            value={uiOrder}
            onChange={(event) => updateUi({ order: Number(event.target.value) || 0 })}
            className="w-full rounded border border-slate-200 bg-white px-2 py-1 text-xs text-slate-700 outline-none focus:border-slate-400"
          />
        </label>
      </div>

      <div>
        <h4 className="mb-1.5 text-xs font-semibold text-slate-700">
          校验结果
          {validationOk === true ? (
            <span className="ml-2 font-normal text-emerald-600">通过</span>
          ) : validationOk === false ? (
            <span className="ml-2 font-normal text-red-600">有错误</span>
          ) : (
            <span className="ml-2 font-normal text-slate-400">尚未校验</span>
          )}
        </h4>
        {issues.length === 0 ? (
          <p className="text-xs text-slate-400">点击顶部“校验”检查连线与参数。</p>
        ) : (
          <ul className="space-y-1.5">
            {issues.map((issue, index) => (
              <IssueRow key={`${issue.code}-${issue.step_id ?? ""}-${index}`} issue={issue} />
            ))}
          </ul>
        )}
      </div>
    </div>
  );
}

function NodeInspector({ nodeId }: { nodeId: string }) {
  const node = useEditorStore((state) => state.nodes.find((item) => item.id === nodeId) ?? null);
  const specs = useEditorStore((state) => state.specs);
  const issues = useEditorStore((state) => state.issues);
  const updateNode = useEditorStore((state) => state.updateNode);
  const removeNodes = useEditorStore((state) => state.removeNodes);
  const addStep = useEditorStore((state) => state.addStep);
  const nodes = useEditorStore((state) => state.nodes);

  const spec: StepSpec | undefined = useMemo(
    () => specs.find((item) => item.id === node?.data.uses),
    [specs, node],
  );
  const nodeIssues = useMemo(
    () => issues.filter((issue) => issue.step_id === nodeId),
    [issues, nodeId],
  );

  if (!node) {
    return <p className="p-4 text-xs text-slate-400">节点已删除。</p>;
  }

  return (
    <div className="space-y-4 p-4">
      <div className="flex items-start justify-between gap-2">
        <div className="min-w-0">
          <h3 className="truncate text-sm font-semibold text-slate-800" title={node.data.title}>
            {node.data.title || node.data.uses}
          </h3>
          <p className="truncate font-mono text-[11px] text-slate-400">
            {nodeId} · {node.data.uses}
          </p>
        </div>
        <button
          type="button"
          title="删除节点"
          onClick={() => removeNodes([nodeId])}
          className="rounded-lg border border-slate-200 p-1.5 text-slate-500 hover:border-red-200 hover:bg-red-50 hover:text-red-600"
        >
          <Trash2 className="h-3.5 w-3.5" />
        </button>
      </div>

      {spec?.description ? (
        <p className="rounded-lg bg-slate-50 px-2.5 py-2 text-[11px] leading-relaxed text-slate-500">
          {spec.description}
        </p>
      ) : null}

      <div className="space-y-2">
        <h4 className="text-xs font-semibold text-slate-700">参数</h4>
        {spec ? (
          <SchemaForm
            schema={spec.options_schema}
            value={node.data.options}
            onChange={(options) => updateNode(nodeId, { options })}
          />
        ) : (
          <p className="text-xs text-red-600">未知步骤实现：{node.data.uses}</p>
        )}
      </div>

      <label className="block space-y-1 text-xs text-slate-600">
        <span className="flex items-center justify-between">
          <span className="font-medium">运行条件 when</span>
          {node.data.when ? (
            <button
              type="button"
              onClick={() => updateNode(nodeId, { when: null })}
              className="text-[11px] text-slate-400 hover:text-slate-600"
            >
              清除
            </button>
          ) : null}
        </span>
        <input
          value={node.data.when ?? ""}
          id={`node-when-${nodeId}`}
          name="when"
          placeholder="${options.use_sdh_agent}"
          onChange={(event) => updateNode(nodeId, { when: event.target.value.trim() || null })}
          className="w-full rounded-lg border border-slate-200 px-2.5 py-1.5 font-mono text-xs text-slate-800 outline-none focus:border-slate-400"
        />
      </label>

      <div className="space-y-2">
        <h4 className="text-xs font-semibold text-slate-700">节点问题</h4>
        {nodeIssues.length === 0 ? (
          <p className="text-xs text-slate-400">没有定位到该节点的问题。</p>
        ) : (
          <ul className="space-y-1.5">
            {nodeIssues.map((issue, index) => (
              <IssueRow key={`${issue.code}-${index}`} issue={issue} />
            ))}
          </ul>
        )}
      </div>

      <div>
        <h4 className="mb-1.5 flex items-center gap-1 text-xs font-semibold text-slate-700">
          <Plus className="h-3.5 w-3.5" /> 下游步骤
        </h4>
        <ul className="space-y-1.5">
          {specs
            .filter((item) => !item.id.startsWith("demo."))
            .slice(0, 20)
            .map((item) => (
              <li key={item.id}>
                <button
                  type="button"
                  onClick={() => {
                    const source = nodes.find((entry) => entry.id === nodeId);
                    const position = {
                      x: (source?.position.x ?? 0) + 300,
                      y: source?.position.y ?? 0,
                    };
                    addStep(item, position);
                  }}
                  className="flex w-full items-center justify-between rounded-lg border border-slate-200 px-2 py-1.5 text-left text-[11px] text-slate-600 hover:border-slate-300 hover:bg-slate-50"
                >
                  <span className="flex items-center gap-1.5">
                    <Copy className="h-3 w-3" /> {item.title}
                  </span>
                  <span className="font-mono text-[10px] text-slate-400">{item.id}</span>
                </button>
              </li>
            ))}
        </ul>
      </div>
    </div>
  );
}

export function Inspector() {
  const selection = useEditorStore((state) => state.selection);
  const issues = useEditorStore((state) => state.issues);
  const counts = useMemo(() => issueCountsByStep(issues), [issues]);
  const activeId = selection[selection.length - 1] ?? null;

  return (
    <aside className="flex w-80 shrink-0 flex-col overflow-auto border-l border-slate-200 bg-white">
      {activeId ? (
        <NodeInspector nodeId={activeId} />
      ) : (
        <RecipeMetaForm />
      )}
      {Object.keys(counts).length > 0 ? (
        <div className="mt-auto border-t border-slate-100 px-4 py-2 text-[11px] text-slate-400">
          {Object.keys(counts).length} 个节点存在校验问题
        </div>
      ) : null}
    </aside>
  );
}

import { Handle, Position, type NodeProps } from "@xyflow/react";
import { AlertTriangle, Bot, CircleAlert, Cpu, FileText, Scissors, Sparkles } from "lucide-react";
import type { DisplayNode } from "../../lib/editorTypes";

const ICONS: Array<{ prefix: string; icon: typeof Cpu; tone: string }> = [
  { prefix: "media.", icon: FileText, tone: "bg-sky-100 text-sky-700" },
  { prefix: "sub.", icon: Scissors, tone: "bg-violet-100 text-violet-700" },
  { prefix: "agent.", icon: Bot, tone: "bg-amber-100 text-amber-700" },
  { prefix: "human.", icon: Cpu, tone: "bg-emerald-100 text-emerald-700" },
];

function iconFor(uses: string) {
  const match = ICONS.find((item) => uses.startsWith(item.prefix));
  return match ?? { icon: Sparkles, tone: "bg-slate-100 text-slate-600" };
}

export function StepNode({ data, selected }: NodeProps<DisplayNode>) {
  const { icon: Icon, tone } = iconFor(data.uses);
  const inputs = Object.entries(data.inputs ?? {});
  const outputs = Object.entries(data.outputs ?? {});
  const optionCount = Object.keys(data.options ?? {}).length;

  return (
    <div
      className={`w-60 rounded-xl border bg-white shadow-sm transition-shadow ${
        selected ? "border-slate-900 shadow-md" : "border-slate-200"
      } ${data.errorCount > 0 ? "ring-2 ring-red-300" : ""} ${
        data.errorCount === 0 && data.warningCount > 0 ? "ring-2 ring-amber-200" : ""
      }`}
    >
      {data.runInputCount ? (
        <Handle
          type="target"
          id="__recipe_input__"
          position={Position.Left}
          isConnectable={false}
          style={{ top: 14 }}
          className="!-left-4 !h-2.5 !w-2.5 !border-2 !border-white !bg-sky-500"
        />
      ) : null}

      <div className="flex items-start gap-2 border-b border-slate-100 px-3 py-2.5">
        <span className={`mt-0.5 rounded-lg p-1.5 ${tone}`}>
          <Icon className="h-4 w-4" />
        </span>
        <div className="min-w-0 flex-1">
          <p className="truncate text-sm font-semibold text-slate-800" title={data.title}>
            {data.title || data.uses}
          </p>
          <p className="truncate font-mono text-[11px] text-slate-400">{data.uses}</p>
        </div>
        {data.errorCount > 0 ? (
          <span className="inline-flex items-center gap-0.5 rounded-full bg-red-100 px-1.5 py-0.5 text-[11px] font-medium text-red-700">
            <CircleAlert className="h-3 w-3" />
            {data.errorCount}
          </span>
        ) : data.warningCount > 0 ? (
          <span className="inline-flex items-center gap-0.5 rounded-full bg-amber-100 px-1.5 py-0.5 text-[11px] font-medium text-amber-700">
            <AlertTriangle className="h-3 w-3" />
            {data.warningCount}
          </span>
        ) : null}
      </div>

      <div className="grid grid-cols-2 gap-2 px-3 py-2 text-[11px]">
        <div className="space-y-1.5">
          {inputs.length === 0 ? (
            <span className="block text-slate-400">无输入</span>
          ) : (
            inputs.map(([name, spec]) => (
              <div key={name} className="relative flex items-center gap-1.5">
                <Handle
                  type="target"
                  id={name}
                  position={Position.Left}
                  className="!-left-4 !h-2.5 !w-2.5 !border-2 !border-white !bg-slate-500"
                />
                <span className="truncate text-slate-600" title={`${name} · ${spec.kind}`}>
                  {name}
                </span>
                <span className="shrink-0 text-slate-300">{spec.kind}</span>
              </div>
            ))
          )}
        </div>
        <div className="space-y-1.5 text-right">
          {outputs.length === 0 ? (
            <span className="block text-slate-400">无输出</span>
          ) : (
            outputs.map(([name, spec]) => (
              <div key={name} className="relative flex items-center justify-end gap-1.5">
                <span className="shrink-0 text-slate-300">{spec.kind}</span>
                <span className="truncate text-slate-600" title={`${name} · ${spec.kind}`}>
                  {name}
                </span>
                <Handle
                  type="source"
                  id={name}
                  position={Position.Right}
                  className="!-right-4 !h-2.5 !w-2.5 !border-2 !border-white !bg-sky-500"
                />
              </div>
            ))
          )}
        </div>
      </div>

      <div className="flex items-center justify-between border-t border-slate-100 px-3 py-1.5 text-[11px] text-slate-400">
        <span>{optionCount} 项参数</span>
        <span className="flex items-center gap-1">
          {data.when ? <span className="truncate text-amber-600">when: {data.when}</span> : null}
          {data.requiresAgent ? <span className="text-amber-600">Agent</span> : null}
        </span>
      </div>
    </div>
  );
}

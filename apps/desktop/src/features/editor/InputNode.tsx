import { Handle, Position, type NodeProps } from "@xyflow/react";
import { FolderInput, Upload } from "lucide-react";
import type { InputNode as InputNodeType } from "../../lib/editorTypes";

/** 只读的配方输入节点：展示命名输入及其目标步骤端口。 */
export function InputNode({ data }: NodeProps<InputNodeType>) {
  const Icon = data.kind === "folder" ? FolderInput : Upload;
  const kindText = data.kind === "folder" ? "文件夹" : data.kind === "files" ? "多文件" : "文件";
  const acceptText = data.accept.join(" ");

  return (
    <div className="w-52 rounded-xl border border-dashed border-sky-300 bg-sky-50/90 px-3 py-2 shadow-sm">
      <div className="flex items-start gap-2">
        <span className="mt-0.5 rounded-lg bg-sky-100 p-1.5 text-sky-700">
          <Icon className="h-4 w-4" />
        </span>
        <div className="min-w-0 flex-1">
          <p className="truncate text-sm font-semibold text-slate-800" title={data.label}>
            {data.label}
          </p>
          <p className="truncate font-mono text-[11px] text-sky-700/80">{data.name}</p>
        </div>
        {data.required && (
          <span className="rounded-full bg-sky-100 px-1.5 py-0.5 text-[10px] font-medium text-sky-700">
            必填
          </span>
        )}
      </div>
      <div className="mt-1.5 flex flex-wrap items-center gap-1 text-[10px] text-slate-500">
        <span className="rounded bg-white/70 px-1 py-0.5">{kindText}</span>
        {data.multiple && <span className="rounded bg-white/70 px-1 py-0.5">可多选</span>}
        {acceptText && (
          <span className="truncate font-mono text-slate-400" title={acceptText}>
            {acceptText}
          </span>
        )}
      </div>
      <p className="mt-1 text-[10px] text-slate-400">
        {data.bound ? "配方输入" : "运行时注入"}
      </p>
      <Handle
        type="source"
        id="value"
        position={Position.Right}
        isConnectable={false}
        className="!-right-4 !h-2.5 !w-2.5 !border-2 !border-white !bg-sky-500"
      />
    </div>
  );
}

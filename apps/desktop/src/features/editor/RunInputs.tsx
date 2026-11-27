import { FileUp, FolderOpen, Trash2 } from "lucide-react";
import type { RecipeInput } from "../../lib/models";
import { pickFiles, pickFolder } from "../../lib/rpc";
import { matchesAccept } from "../../lib/tasks";

interface RunInputsProps {
  inputs: RecipeInput[];
  slots: Record<string, string[]>;
  disabled?: boolean;
  onChange: (name: string, paths: string[]) => void;
  onError?: (message: string) => void;
}

function acceptsMany(input: RecipeInput): boolean {
  return input.multiple === true || input.kind === "files";
}

/** 编辑器运行面板：每个配方输入一个槽位，支持多文件与文件夹。 */
export function RunInputs({
  inputs,
  slots,
  disabled = false,
  onChange,
  onError,
}: RunInputsProps) {
  if (inputs.length === 0) {
    return (
      <span className="text-[11px] text-slate-400">此配方不需要输入文件</span>
    );
  }

  const chooseFiles = async (input: RecipeInput) => {
    try {
      const picked = await pickFiles();
      if (picked.length === 0) return;
      const matching = picked.filter((path) => matchesAccept(path, input.accept));
      const chosen = matching.length > 0 ? matching : picked;
      const current = slots[input.name] ?? [];
      const next = acceptsMany(input)
        ? Array.from(new Set([...current, ...chosen]))
        : chosen.slice(-1);
      onChange(input.name, next);
    } catch (error) {
      onError?.(`无法打开文件选择器：${error instanceof Error ? error.message : String(error)}`);
    }
  };

  const chooseFolder = async (input: RecipeInput) => {
    try {
      const folder = await pickFolder();
      if (folder) onChange(input.name, [folder]);
    } catch (error) {
      onError?.(`无法打开文件夹选择器：${error instanceof Error ? error.message : String(error)}`);
    }
  };

  return (
    <div className="flex flex-wrap gap-2">
      {inputs.map((input) => {
        const paths = slots[input.name] ?? [];
        const label = input.label?.trim() || input.name;
        return (
          <div
            key={input.name}
            data-testid={`editor-input-${input.name}`}
            className="min-w-[220px] flex-1 rounded-lg border border-slate-200 bg-white px-2 py-1.5"
          >
            <div className="flex items-center justify-between gap-2">
              <span className="truncate text-[11px] font-medium text-slate-700" title={input.name}>
                {label}
                {input.required ? <span className="ml-1 text-rose-500">*</span> : null}
              </span>
              <span className="shrink-0 font-mono text-[10px] text-slate-400">
                {(input.accept.length > 0 ? input.accept.join(" ") : "任意") +
                  (acceptsMany(input) ? " · 多选" : "")}
              </span>
            </div>
            {paths.length === 0 ? (
              <p className="mt-0.5 truncate text-[11px] text-slate-400">未选择</p>
            ) : (
              <ul className="mt-0.5 space-y-0.5">
                {paths.map((path) => (
                  <li key={path} className="flex items-center gap-1 text-[11px] text-slate-600">
                    <span className="truncate font-mono" title={path}>
                      {path}
                    </span>
                    <button
                      type="button"
                      aria-label={`移除 ${path}`}
                      disabled={disabled}
                      onClick={() =>
                        onChange(
                          input.name,
                          paths.filter((item) => item !== path),
                        )
                      }
                      className="shrink-0 rounded p-0.5 text-slate-400 hover:bg-slate-100 hover:text-slate-700 disabled:opacity-40"
                    >
                      <Trash2 className="h-3 w-3" />
                    </button>
                  </li>
                ))}
              </ul>
            )}
            <div className="mt-1 flex flex-wrap items-center gap-1">
              <button
                type="button"
                disabled={disabled}
                onClick={() => void chooseFiles(input)}
                className="inline-flex items-center gap-1 rounded border border-slate-200 px-1.5 py-0.5 text-[10px] text-slate-600 hover:bg-slate-50 disabled:opacity-40"
              >
                <FileUp className="h-3 w-3" /> 选择文件
              </button>
              <button
                type="button"
                disabled={disabled}
                onClick={() => void chooseFolder(input)}
                className="inline-flex items-center gap-1 rounded border border-slate-200 px-1.5 py-0.5 text-[10px] text-slate-600 hover:bg-slate-50 disabled:opacity-40"
              >
                <FolderOpen className="h-3 w-3" /> 文件夹
              </button>
              <button
                type="button"
                disabled={disabled || paths.length === 0}
                onClick={() => onChange(input.name, [])}
                className="rounded border border-slate-200 px-1.5 py-0.5 text-[10px] text-slate-500 hover:bg-slate-50 disabled:opacity-40"
              >
                清空
              </button>
            </div>
          </div>
        );
      })}
    </div>
  );
}

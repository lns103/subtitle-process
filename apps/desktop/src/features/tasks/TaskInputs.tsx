import { useCallback, useEffect, useRef, useState, type PointerEvent } from "react";
import { getCurrentWebview } from "@tauri-apps/api/webview";
import type { UnlistenFn } from "@tauri-apps/api/event";
import { FileVideo, FolderOpen, Sparkles, Trash2, Upload, Wand2 } from "lucide-react";
import type { RoutingResult } from "../../lib/inputRouting";
import type { TaskInputSpec, TaskSpec } from "../../lib/models";
import { matchesAccept, taskInputLabel } from "../../lib/tasks";
import { pickFiles, pickFolder } from "../../lib/rpc";

interface TaskInputsProps {
  task: TaskSpec;
  slots: Record<string, string[]>;
  autofilled: Record<string, boolean>;
  routing?: RoutingResult | null;
  disabled?: boolean;
  onSet: (taskId: string, inputName: string, paths: string[]) => void;
  onClear: (taskId: string, inputName: string) => void;
  /** 通用槽：按规则自动分发到输入槽。 */
  onRoute: (paths: string[], overwrite: boolean, recursive: boolean) => void;
  /** 拖动改槽：把文件从 fromInput 移到 toInput。 */
  onMove: (taskId: string, fromInput: string, toInput: string, path: string) => void;
  onUndoRouting: () => void;
}

function acceptsMany(input: TaskInputSpec): boolean {
  return input.multiple === true || input.kind === "files";
}

function slotPaths(slots: Record<string, string[]>, input: TaskInputSpec): string[] {
  return slots[input.name] ?? [];
}

/** 原生拖拽事件给的是物理像素，换算成 CSS 像素后再做命中测试。 */
function dropPoint(position?: { x: number; y: number } | null): { x: number; y: number } | null {
  if (!position) return null;
  const ratio = window.devicePixelRatio || 1;
  return { x: position.x / ratio, y: position.y / ratio };
}

function slotAtPoint(point: { x: number; y: number } | null): string | null {
  if (!point) return null;
  const element = document.elementFromPoint(point.x, point.y) as HTMLElement | null;
  return element?.closest<HTMLElement>("[data-input-slot]")?.dataset.inputSlot ?? null;
}

/**
 * 任务输入槽：每个 TaskSpec.inputs 对应一个槽位。
 * 原生拖拽事件只在这里注册一次，按落点槽位 / 扩展名分发到具体槽位。
 */
export function TaskInputs({
  task,
  slots,
  autofilled,
  routing = null,
  disabled = false,
  onSet,
  onClear,
  onRoute,
  onMove,
  onUndoRouting,
}: TaskInputsProps) {
  const [focusedSlot, setFocusedSlot] = useState<string | null>(null);
  const [isOver, setIsOver] = useState(false);
  const [overwrite, setOverwrite] = useState(false);
  const [recursive, setRecursive] = useState(false);
  const [dragOverSlot, setDragOverSlot] = useState<string | null>(null);
  const stateRef = useRef({
    task,
    slots,
    onSet,
    onRoute,
    overwrite,
    recursive,
  });

  useEffect(() => {
    stateRef.current = {
      task,
      slots,
      onSet,
      onRoute,
      overwrite,
      recursive,
    };
  }, [task, slots, onSet, onRoute, overwrite, recursive]);

  const routeDrop = useCallback((paths: string[], targetSlot: string | null) => {
    const {
      task: currentTask,
      slots: currentSlots,
      onSet: apply,
      onRoute: route,
      overwrite: replace,
      recursive: includeChildren,
    } = stateRef.current;
    if (paths.length === 0 || currentTask.inputs.length === 0) return;

    // 只有拖到具体输入槽上才做精确投放；落到通用区则按规则自动分配。
    const target = targetSlot
      ? (currentTask.inputs.find((input) => input.name === targetSlot) ?? null)
      : null;

    if (!target) {
      route(paths, replace, includeChildren);
      return;
    }

    // 显式投放尊重槽位：整批追加/替换，不再回落到其它空槽。
    const matching = paths.filter((path) => matchesAccept(path, target.accept));
    const chosen = matching.length > 0 ? matching : paths;
    const next = acceptsMany(target)
      ? Array.from(new Set([...(currentSlots[target.name] ?? []), ...chosen]))
      : [chosen[chosen.length - 1] ?? paths[0]];
    apply(currentTask.id, target.name, next);
  }, []);

  useEffect(() => {
    let unlisten: UnlistenFn | undefined;
    let disposed = false;

    getCurrentWebview()
      .onDragDropEvent((event) => {
        const payload = event.payload;
        if (payload.type === "over") {
          setIsOver(true);
          setDragOverSlot(slotAtPoint(dropPoint(payload.position)));
        } else if (payload.type === "drop") {
          setIsOver(false);
          const target = slotAtPoint(dropPoint(payload.position));
          setDragOverSlot(null);
          if (payload.paths.length > 0) routeDrop(payload.paths, target);
        } else {
          setIsOver(false);
          setDragOverSlot(null);
        }
      })
      .then((fn) => {
        if (disposed) fn();
        else unlisten = fn;
      })
      .catch((error) => console.error("注册拖拽事件失败", error));

    return () => {
      disposed = true;
      unlisten?.();
    };
  }, [routeDrop]);

  const chooseFiles = useCallback(
    async (input: TaskInputSpec, replace: boolean) => {
      const files = await pickFiles();
      if (files.length === 0) return;
      const next = replace ? files : [...slotPaths(slots, input), ...files];
      onSet(task.id, input.name, acceptsMany(input) ? next : next.slice(-1));
    },
    [onSet, slots, task.id],
  );

  const chooseFolder = useCallback(
    async (input: TaskInputSpec) => {
      const folder = await pickFolder();
      if (!folder) return;
      onSet(task.id, input.name, [folder]);
    },
    [onSet, task.id],
  );

  const chooseUniversalFiles = useCallback(async () => {
    const files = await pickFiles();
    if (files.length > 0) onRoute(files, overwrite, recursive);
  }, [onRoute, overwrite, recursive]);

  const chooseUniversalFolder = useCallback(async () => {
    const folder = await pickFolder();
    if (folder) onRoute([folder], overwrite, recursive);
  }, [onRoute, overwrite, recursive]);

  const beginPathDrag = useCallback(
    (event: PointerEvent<HTMLElement>, inputName: string, path: string) => {
      if (disabled || event.button !== 0) return;
      const targetElement = event.target as HTMLElement;
      if (targetElement.closest("button")) return;
      event.preventDefault();

      const startX = event.clientX;
      const startY = event.clientY;
      let active = false;

      const slotAt = (x: number, y: number): string | null => {
        const element = document.elementFromPoint(x, y) as HTMLElement | null;
        return element?.closest<HTMLElement>("[data-input-slot]")?.dataset.inputSlot ?? null;
      };

      const handleMove = (moveEvent: globalThis.PointerEvent) => {
        if (
          !active &&
          Math.hypot(moveEvent.clientX - startX, moveEvent.clientY - startY) < 5
        ) {
          return;
        }
        active = true;
        moveEvent.preventDefault();
        setDragOverSlot(slotAt(moveEvent.clientX, moveEvent.clientY));
      };

      const finish = (upEvent: globalThis.PointerEvent) => {
        window.removeEventListener("pointermove", handleMove);
        window.removeEventListener("pointerup", finish);
        window.removeEventListener("pointercancel", finish);
        setDragOverSlot(null);
        if (!active) return;
        const toInput = slotAt(upEvent.clientX, upEvent.clientY);
        if (toInput && toInput !== inputName) {
          onMove(task.id, inputName, toInput, path);
          setFocusedSlot(toInput);
        }
      };

      window.addEventListener("pointermove", handleMove, { passive: false });
      window.addEventListener("pointerup", finish);
      window.addEventListener("pointercancel", finish);
    },
    [disabled, onMove, task.id],
  );

  if (task.inputs.length === 0) {
    return (
      <p className="rounded-lg bg-slate-50 px-3 py-2 text-sm text-slate-500">
        此任务不需要输入文件。
      </p>
    );
  }

  return (
    <div
      className={`space-y-3 rounded-xl transition ${
        isOver ? "ring-2 ring-emerald-300 ring-offset-2" : ""
      }`}
      data-testid="task-inputs"
    >
      <div
        role="group"
        aria-label="通用投放"
        data-testid="universal-drop"
        tabIndex={disabled ? -1 : 0}
        onFocus={() => setFocusedSlot(null)}
        onClick={() => setFocusedSlot(null)}
        className={`rounded-xl border-2 border-dashed p-3 transition ${
          focusedSlot === null
            ? "border-emerald-300 bg-emerald-50/50"
            : "border-slate-300 bg-white"
        }`}
      >
        <div className="flex flex-wrap items-center justify-between gap-2">
          <div className="min-w-0">
            <p className="flex items-center gap-1.5 text-sm font-medium text-slate-800">
              <Wand2 className="h-4 w-4 text-emerald-600" /> 通用投放 · 自动分配
            </p>
            <p className="mt-0.5 text-[11px] text-slate-500">
              拖入文件或文件夹，按扩展名、文件名和文件夹名（含“译文”）自动填入下方槽位。
            </p>
          </div>
          <div className="flex flex-wrap items-center gap-1.5">
            <button
              type="button"
              disabled={disabled}
              onClick={(event) => {
                event.stopPropagation();
                setFocusedSlot(null);
                void chooseUniversalFiles();
              }}
              className="inline-flex items-center gap-1 rounded-lg border border-slate-300 bg-white px-2 py-1 text-xs text-slate-700 hover:bg-slate-50 disabled:opacity-50"
            >
              <FileVideo className="h-3.5 w-3.5" /> 选择文件
            </button>
            <button
              type="button"
              disabled={disabled}
              onClick={(event) => {
                event.stopPropagation();
                setFocusedSlot(null);
                void chooseUniversalFolder();
              }}
              className="inline-flex items-center gap-1 rounded-lg border border-slate-300 bg-white px-2 py-1 text-xs text-slate-700 hover:bg-slate-50 disabled:opacity-50"
            >
              <FolderOpen className="h-3.5 w-3.5" /> 选择文件夹
            </button>
            <label className="inline-flex items-center gap-1 text-[11px] text-slate-500">
              <input
                type="checkbox"
                checked={recursive}
                disabled={disabled}
                onChange={(event) => setRecursive(event.target.checked)}
                className="h-3.5 w-3.5 rounded border-slate-300"
              />
              包含子目录
            </label>
            <label className="inline-flex items-center gap-1 text-[11px] text-slate-500">
              <input
                type="checkbox"
                checked={overwrite}
                disabled={disabled}
                onChange={(event) => setOverwrite(event.target.checked)}
                className="h-3.5 w-3.5 rounded border-slate-300"
              />
              覆盖已有
            </label>
          </div>
        </div>

        {routing && (routing.assigned.length > 0 || routing.unassigned.length > 0) && (
          <div className="mt-2 rounded-lg border border-slate-200 bg-white/80 p-2" data-testid="routing-summary">
            <ul className="space-y-0.5 text-[11px] text-slate-600">
              {routing.assigned.flatMap((assignment) => {
                const input = task.inputs.find((item) => item.name === assignment.input);
                return assignment.paths.map((path) => (
                  <li
                    key={`${assignment.input}:${path}`}
                    onPointerDown={(event) => beginPathDrag(event, assignment.input, path)}
                    className="cursor-grab touch-none truncate select-none active:cursor-grabbing"
                    title={path}
                  >
                    <span className="text-emerald-700">
                      → {input ? taskInputLabel(input) : assignment.input}
                    </span>
                    {"  "}
                    <span className="font-mono">{path}</span>
                  </li>
                ));
              })}
              {routing.unassigned.map((item) => (
                <li key={`unassigned:${item.path}`} className="truncate text-amber-700">
                  未分配：<span className="font-mono" title={item.path}>{item.path}</span>（{item.reason}）
                </li>
              ))}
            </ul>
            {routing.ambiguous.length > 0 && (
              <p className="mt-1 text-[11px] text-amber-700">
                有 {routing.ambiguous.length} 个文件无法完全确定归属，请检查下方槽位。
              </p>
            )}
            <p className="mt-1 text-[11px] text-slate-400">
              提示：拖动文件行到下方任意槽位即可改槽。
            </p>
            <button
              type="button"
              onClick={onUndoRouting}
              className="mt-1 text-[11px] text-slate-500 underline-offset-2 hover:text-slate-700 hover:underline"
            >
              撤销本次分配
            </button>
          </div>
        )}
      </div>

      {task.inputs.map((input) => {
        const paths = slotPaths(slots, input);
        const label = taskInputLabel(input);
        const isAuto = autofilled[input.name] === true;
        return (
          <div
            key={input.name}
            role="group"
            aria-label={`${label} 输入槽`}
            data-testid={`input-slot-${input.name}`}
            data-input-slot={input.name}
            tabIndex={disabled ? -1 : 0}
            onFocus={() => setFocusedSlot(input.name)}
            onClick={() => setFocusedSlot(input.name)}
            onKeyDown={(event) => {
              if (event.target !== event.currentTarget) return;
              if (event.key === "Enter" || event.key === " ") {
                event.preventDefault();
                if (!disabled) void chooseFiles(input, false);
              }
            }}
            className={`rounded-xl border p-3 outline-none transition focus:border-emerald-400 focus:ring-2 focus:ring-emerald-100 ${
              dragOverSlot === input.name
                ? "border-emerald-500 bg-emerald-50 ring-2 ring-emerald-200"
                : focusedSlot === input.name
                  ? "border-emerald-300 bg-emerald-50/40"
                  : paths.length > 0
                    ? "border-slate-300 bg-slate-50/60"
                    : "border-dashed border-slate-300 bg-white"
            }`}
          >
            <div className="flex flex-wrap items-start justify-between gap-2">
              <div className="min-w-0">
                <p className="flex flex-wrap items-center gap-1.5 text-sm font-medium text-slate-800">
                  {label}
                  {input.required && (
                    <span className="rounded bg-rose-50 px-1.5 py-0.5 text-[10px] text-rose-600">
                      必填
                    </span>
                  )}
                  {isAuto && (
                    <span className="inline-flex items-center gap-0.5 rounded bg-emerald-100 px-1.5 py-0.5 text-[10px] text-emerald-700">
                      <Sparkles className="h-3 w-3" /> 自动填充
                    </span>
                  )}
                </p>
                <p className="mt-0.5 text-[11px] text-slate-400">
                  {input.accept.length > 0 ? input.accept.join(" · ") : "任意文件或文件夹"}
                  {acceptsMany(input) ? " · 可多选" : ""}
                </p>
              </div>
              <div className="flex flex-wrap items-center gap-1.5">
                {input.kind !== "folder" && (
                  <button
                    type="button"
                    disabled={disabled}
                    onClick={(event) => {
                      event.stopPropagation();
                      setFocusedSlot(input.name);
                      void chooseFiles(input, false);
                    }}
                    className="inline-flex items-center gap-1 rounded-lg border border-slate-300 bg-white px-2 py-1 text-xs text-slate-700 hover:bg-slate-50 disabled:opacity-50"
                  >
                    <FileVideo className="h-3.5 w-3.5" /> 选择文件
                  </button>
                )}
                <button
                  type="button"
                  disabled={disabled}
                  onClick={(event) => {
                    event.stopPropagation();
                    setFocusedSlot(input.name);
                    void chooseFolder(input);
                  }}
                  className="inline-flex items-center gap-1 rounded-lg border border-slate-300 bg-white px-2 py-1 text-xs text-slate-700 hover:bg-slate-50 disabled:opacity-50"
                >
                  <FolderOpen className="h-3.5 w-3.5" /> 选择文件夹
                </button>
                {input.kind !== "folder" && (
                  <button
                    type="button"
                    disabled={disabled}
                    onClick={(event) => {
                      event.stopPropagation();
                      setFocusedSlot(input.name);
                      void chooseFiles(input, true);
                    }}
                    className="inline-flex items-center gap-1 rounded-lg border border-slate-300 bg-white px-2 py-1 text-xs text-slate-700 hover:bg-slate-50 disabled:opacity-50"
                  >
                    <Upload className="h-3.5 w-3.5" /> 替换
                  </button>
                )}
                <button
                  type="button"
                  disabled={disabled || paths.length === 0}
                  onClick={(event) => {
                    event.stopPropagation();
                    onClear(task.id, input.name);
                  }}
                  className="inline-flex items-center gap-1 rounded-lg border border-slate-300 bg-white px-2 py-1 text-xs text-slate-600 hover:bg-slate-50 disabled:opacity-40"
                >
                  <Trash2 className="h-3.5 w-3.5" /> 清空
                </button>
              </div>
            </div>

            {paths.length === 0 ? (
              <p className="mt-2 rounded-lg border border-dashed border-slate-200 px-3 py-2 text-xs text-slate-400">
                拖入文件，或使用上方按钮选择。
              </p>
            ) : (
              <ul className="mt-2 space-y-1">
                {paths.map((path) => (
                  <li
                    key={path}
                    onPointerDown={(event) => beginPathDrag(event, input.name, path)}
                    className="flex cursor-grab touch-none items-center justify-between gap-2 rounded bg-white px-2 py-1 text-xs text-slate-600 select-none active:cursor-grabbing"
                    title={path}
                  >
                    <span className="truncate font-mono" title={path}>
                      {path}
                    </span>
                    <button
                      type="button"
                      aria-label={`移除 ${path}`}
                      disabled={disabled}
                      onClick={(event) => {
                        event.stopPropagation();
                        onSet(
                          task.id,
                          input.name,
                          paths.filter((item) => item !== path),
                        );
                      }}
                      className="shrink-0 rounded px-1 text-slate-400 hover:bg-slate-100 hover:text-slate-600"
                    >
                      ×
                    </button>
                  </li>
                ))}
              </ul>
            )}
          </div>
        );
      })}
    </div>
  );
}

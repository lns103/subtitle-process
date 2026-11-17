import { useEffect, useMemo, useState } from "react";
import { Boxes, Layers, ListChecks, Loader2 } from "lucide-react";
import type { TaskKind, TaskSpec } from "../../lib/models";
import { sortTasks } from "../../lib/tasks";

interface TaskPickerProps {
  tasks: TaskSpec[];
  selectedId: string | null;
  loading?: boolean;
  error?: string | null;
  onSelect: (task: TaskSpec) => void;
}

const TABS: Array<{ kind: TaskKind; label: string; icon: typeof Layers }> = [
  { kind: "workflow", label: "流水线", icon: Layers },
  { kind: "function", label: "单项功能", icon: ListChecks },
];

/** 首页任务选择器：流水线 / 单项功能两个分栏。 */
export function TaskPicker({
  tasks,
  selectedId,
  loading = false,
  error = null,
  onSelect,
}: TaskPickerProps) {
  const [active, setActive] = useState<TaskKind>("workflow");

  const grouped = useMemo(() => {
    const sorted = sortTasks(tasks);
    return {
      workflow: sorted.filter((task) => task.kind !== "function"),
      function: sorted.filter((task) => task.kind === "function"),
    };
  }, [tasks]);

  const visible = grouped[active];

  useEffect(() => {
    const selected = tasks.find((task) => task.id === selectedId);
    if (selected) setActive(selected.kind === "function" ? "function" : "workflow");
  }, [selectedId, tasks]);

  return (
    <section className="rounded-2xl border border-slate-200 bg-white p-5" aria-label="选择任务">      <div className="flex flex-wrap items-center justify-between gap-2">
        <h2 className="flex items-center gap-2 text-base font-semibold text-slate-800">
          <Boxes className="h-4 w-4 text-slate-500" /> 选择要执行的任务
        </h2>
        {loading && (
          <span className="inline-flex items-center gap-1 text-xs text-slate-400">
            <Loader2 className="h-3.5 w-3.5 animate-spin" /> 读取任务目录…
          </span>
        )}
      </div>

      <div role="tablist" aria-label="任务类型" className="mt-4 flex gap-1 rounded-xl bg-slate-100 p-1">
        {TABS.map(({ kind, label, icon: Icon }) => {
          const selected = active === kind;
          return (
            <button
              key={kind}
              type="button"
              role="tab"
              aria-selected={selected}
              data-testid={`task-tab-${kind}`}
              onClick={() => setActive(kind)}
              className={`inline-flex flex-1 items-center justify-center gap-1.5 rounded-lg px-3 py-1.5 text-sm font-medium transition ${
                selected
                  ? "bg-white text-slate-900 shadow-sm"
                  : "text-slate-500 hover:text-slate-700"
              }`}
            >
              <Icon className="h-4 w-4" /> {label}
              <span className="text-[11px] text-slate-400">{grouped[kind].length}</span>
            </button>
          );
        })}
      </div>

      {error && (
        <p role="alert" className="mt-3 rounded-lg bg-red-50 px-3 py-2 text-sm text-red-700">
          任务目录加载失败：{error}
        </p>
      )}

      {visible.length === 0 ? (
        <p className="mt-4 rounded-lg bg-slate-50 px-3 py-4 text-sm text-slate-500">
          {loading ? "正在读取…" : "该分类下暂无任务。"}
        </p>
      ) : (
        <ul className="mt-4 grid gap-2 sm:grid-cols-2">
          {visible.map((task) => {
            const selected = task.id === selectedId;
            return (
              <li key={task.id}>
                <button
                  type="button"
                  data-testid={`task-card-${task.id}`}
                  aria-pressed={selected}
                  onClick={() => onSelect(task)}
                  className={`flex h-full w-full flex-col items-start gap-1 rounded-xl border p-3 text-left transition ${
                    selected
                      ? "border-emerald-400 bg-emerald-50/70 ring-1 ring-emerald-200"
                      : "border-slate-200 bg-white hover:border-slate-300 hover:bg-slate-50"
                  }`}
                >
                  <span className="flex w-full items-center justify-between gap-2">
                    <span className="truncate text-sm font-semibold text-slate-800">
                      {task.title}
                    </span>
                    {selected && (
                      <span className="shrink-0 rounded-full bg-emerald-600 px-2 py-0.5 text-[10px] font-medium text-white">
                        已选择
                      </span>
                    )}
                  </span>
                  <span className="line-clamp-2 text-xs text-slate-500">{task.description}</span>
                  {task.group && (
                    <span className="mt-1 rounded bg-slate-100 px-1.5 py-0.5 text-[10px] text-slate-500">
                      {task.group}
                    </span>
                  )}
                </button>
              </li>
            );
          })}
        </ul>
      )}
    </section>
  );
}

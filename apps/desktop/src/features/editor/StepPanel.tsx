import { useMemo, useState } from "react";
import { Blocks, Bot, FileText, GitBranch, Search, Scissors, Sparkles, TriangleAlert } from "lucide-react";
import type { StepSpec } from "../../lib/models";

export const STEP_DRAG_MIME = "application/x-subtitle-step";

const GROUPS: Array<{ prefix: string; label: string; icon: typeof FileText }> = [
  { prefix: "media.", label: "媒体", icon: FileText },
  { prefix: "sub.", label: "字幕", icon: Scissors },
  { prefix: "human.", label: "人工", icon: GitBranch },
  { prefix: "agent.", label: "Agent", icon: Bot },
  { prefix: "translate.", label: "翻译", icon: Sparkles },
  { prefix: "demo.", label: "演示", icon: Blocks },
];

function groupOf(uses: string): string {
  const match = GROUPS.find((item) => uses.startsWith(item.prefix));
  return match?.prefix ?? "other";
}

interface StepPanelProps {
  specs: StepSpec[];
  onAdd: (spec: StepSpec) => void;
}

export function StepPanel({ specs, onAdd }: StepPanelProps) {
  const [query, setQuery] = useState("");

  const groups = useMemo(() => {
    const keyword = query.trim().toLowerCase();
    const filtered = specs.filter((spec) => {
      if (!keyword) return true;
      return (
        spec.id.toLowerCase().includes(keyword) ||
        spec.title.toLowerCase().includes(keyword) ||
        spec.description.toLowerCase().includes(keyword)
      );
    });
    return GROUPS.map((group) => ({
      ...group,
      items: filtered.filter((spec) => groupOf(spec.id) === group.prefix),
    })).filter((group) => group.items.length > 0);
  }, [specs, query]);

  return (
    <aside className="flex w-64 shrink-0 flex-col border-r border-slate-200 bg-white">
      <div className="space-y-2 border-b border-slate-100 px-3 py-3">
        <h2 className="flex items-center gap-2 text-sm font-semibold text-slate-800">
          <Blocks className="h-4 w-4" /> 步骤面板
        </h2>
        <label className="flex items-center gap-2 rounded-lg border border-slate-200 px-2 py-1.5 text-xs text-slate-500 focus-within:border-slate-400">
          <Search className="h-3.5 w-3.5" />
          <input
            value={query}
            id="step-search"
            name="step-search"
            onChange={(event) => setQuery(event.target.value)}
            placeholder="搜索步骤 / 标题"
            className="w-full bg-transparent text-slate-800 outline-none placeholder:text-slate-400"
          />
        </label>
        <p className="text-[11px] leading-relaxed text-slate-400">拖入画布，或点击添加到中心。</p>
      </div>

      <div className="flex-1 space-y-4 overflow-auto px-3 py-3">
        {groups.length === 0 ? (
          <p className="text-xs text-slate-400">没有匹配的步骤。</p>
        ) : (
          groups.map((group) => {
            const GroupIcon = group.icon;
            return (
              <section key={group.prefix}>
                <h3 className="mb-1.5 flex items-center gap-1.5 text-[11px] font-semibold uppercase tracking-wide text-slate-400">
                  <GroupIcon className="h-3 w-3" /> {group.label}
                </h3>
                <ul className="space-y-1.5">
                  {group.items.map((spec) => (
                    <li key={spec.id}>
                      <button
                        type="button"
                        draggable
                        onDragStart={(event) => {
                          event.dataTransfer.setData(STEP_DRAG_MIME, spec.id);
                          event.dataTransfer.effectAllowed = "move";
                        }}
                        onClick={() => onAdd(spec)}
                        title={spec.description}
                        className="w-full cursor-grab rounded-lg border border-slate-200 bg-white px-2.5 py-2 text-left transition-colors hover:border-slate-300 hover:bg-slate-50 active:cursor-grabbing"
                      >
                        <span className="flex items-center justify-between gap-2">
                          <span className="truncate text-xs font-medium text-slate-700">{spec.title}</span>
                          {spec.requires_agent ? (
                            <TriangleAlert className="h-3 w-3 shrink-0 text-amber-500" />
                          ) : null}
                        </span>
                        <span className="mt-0.5 block truncate font-mono text-[10px] text-slate-400">
                          {spec.id}
                        </span>
                      </button>
                    </li>
                  ))}
                </ul>
              </section>
            );
          })
        )}
      </div>
    </aside>
  );
}

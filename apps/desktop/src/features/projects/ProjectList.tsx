import { FolderClock } from "lucide-react";
import type { ProjectSummary } from "../../lib/models";

const STATUS_TEXT: Record<ProjectSummary["status"], string> = {
  draft: "草稿",
  running: "运行中",
  waiting_review: "等待审核",
  waiting_translation: "等待翻译",
  done: "已完成",
  failed: "失败",
};

const STATUS_TONE: Record<ProjectSummary["status"], string> = {
  draft: "bg-slate-100 text-slate-600",
  running: "bg-sky-100 text-sky-700",
  waiting_review: "bg-amber-100 text-amber-700",
  waiting_translation: "bg-violet-100 text-violet-700",
  done: "bg-emerald-100 text-emerald-700",
  failed: "bg-red-100 text-red-700",
};

interface ProjectListProps {
  projects: ProjectSummary[];
  activeId?: string | null;
  loading?: boolean;
  onSelect: (id: string) => void;
}

function formatTime(value: string): string {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return date.toLocaleString();
}

export function ProjectList({ projects, activeId, loading, onSelect }: ProjectListProps) {
  return (
    <section className="rounded-2xl border border-slate-200 bg-white p-5">
      <div className="flex items-center justify-between">
        <h2 className="flex items-center gap-2 text-base font-semibold text-slate-800">
          <FolderClock className="h-4 w-4" /> 最近项目
        </h2>
        {loading && <span className="text-xs text-slate-400">加载中…</span>}
      </div>

      {projects.length === 0 ? (
        <p className="mt-3 text-sm text-slate-500">还没有项目。拖入视频开始第一个任务。</p>
      ) : (
        <ul className="mt-3 divide-y divide-slate-100">
          {projects.map((project) => (
            <li key={project.id}>
              <button
                type="button"
                onClick={() => onSelect(project.id)}
                className={`flex w-full items-center justify-between gap-3 rounded-lg px-2 py-2.5 text-left hover:bg-slate-50 ${
                  activeId === project.id ? "bg-slate-50" : ""
                }`}
              >
                <div className="min-w-0">
                  <p className="truncate text-sm font-medium text-slate-800">{project.name}</p>
                  <p className="truncate text-xs text-slate-500">
                    {project.media_path || project.workspace}
                  </p>
                </div>
                <div className="flex shrink-0 flex-col items-end gap-1">
                  <span className={`rounded-full px-2 py-0.5 text-xs ${STATUS_TONE[project.status]}`}>
                    {STATUS_TEXT[project.status]}
                  </span>
                  <span className="text-[11px] text-slate-400">
                    {formatTime(project.updated_at)}
                  </span>
                </div>
              </button>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}

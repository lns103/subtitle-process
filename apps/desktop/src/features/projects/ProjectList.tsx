import { confirm } from "@tauri-apps/plugin-dialog";
import { FolderClock, Loader2, Trash2 } from "lucide-react";
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
  /** 可选：不传时删除按钮保持禁用，直至调用方接线。 */
  onDelete?: (id: string) => void;
  /** 正在删除的项目 id；对应行显示加载/禁用态。 */
  deletingId?: string | null;
}

function formatTime(value: string): string {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return date.toLocaleString();
}

export function ProjectList({
  projects,
  activeId,
  loading,
  onSelect,
  onDelete,
  deletingId,
}: ProjectListProps) {
  const requestDelete = async (project: ProjectSummary) => {
    if (!onDelete || project.status === "running" || deletingId === project.id) return;
    try {
      const accepted = await confirm(
        `确定删除项目「${project.name}」吗？\n\n会同时删除项目工作区与已导出的字幕文件，无法恢复。`,
        { title: "删除项目", kind: "warning", okLabel: "删除", cancelLabel: "取消" },
      );
      if (accepted) onDelete(project.id);
    } catch {
      // 用户在对话框层取消或对话框不可用时保持原状。
    }
  };

  const deleteTitle = (project: ProjectSummary): string | undefined => {
    if (project.status === "running") return "运行中的项目无法删除，请先等待或取消运行";
    if (!onDelete) return "删除功能暂不可用";
    return undefined;
  };

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
          {projects.map((project) => {
            const deleting = deletingId === project.id;
            const disabled = project.status === "running" || deleting || !onDelete;
            return (
              <li key={project.id} className="flex items-center gap-1">
                <button
                  type="button"
                  onClick={() => onSelect(project.id)}
                  className={`flex min-w-0 flex-1 items-center justify-between gap-3 rounded-lg px-2 py-2.5 text-left hover:bg-slate-50 ${
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
                    <span
                      className={`rounded-full px-2 py-0.5 text-xs ${STATUS_TONE[project.status]}`}
                    >
                      {STATUS_TEXT[project.status]}
                    </span>
                    <span className="text-[11px] text-slate-400">
                      {formatTime(project.updated_at)}
                    </span>
                  </div>
                </button>
                <button
                  type="button"
                  aria-label={`删除项目 ${project.name}`}
                  title={deleteTitle(project)}
                  data-testid={`delete-project-${project.id}`}
                  disabled={disabled}
                  onClick={(event) => {
                    event.stopPropagation();
                    void requestDelete(project);
                  }}
                  className="shrink-0 rounded-lg p-2 text-slate-400 transition hover:bg-red-50 hover:text-red-600 disabled:cursor-not-allowed disabled:opacity-40 disabled:hover:bg-transparent disabled:hover:text-slate-400"
                >
                  {deleting ? (
                    <Loader2 className="h-4 w-4 animate-spin" aria-hidden="true" />
                  ) : (
                    <Trash2 className="h-4 w-4" aria-hidden="true" />
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

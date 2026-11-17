import { create } from "zustand";
import { getProject, listProjects } from "../lib/api";
import type { Project, ProjectSummary } from "../lib/models";

interface ProjectState {
  projects: ProjectSummary[];
  active: Project | null;
  loading: boolean;
  lastError: string | null;
  /** HandoffCard 引导回首页后，流程 2 预选的项目。 */
  preferredProjectId: string | null;
  refresh: () => Promise<void>;
  select: (id: string) => Promise<void>;
  applyUpdate: (project: Project) => void;
  clearActive: () => void;
  preferProject: (id: string | null) => void;
}

export const useProjectStore = create<ProjectState>((set, get) => ({
  projects: [],
  active: null,
  loading: false,
  lastError: null,
  preferredProjectId: null,

  refresh: async () => {
    set({ loading: true });
    try {
      const projects = await listProjects();
      set({ projects, loading: false, lastError: null });
    } catch (error) {
      set({
        loading: false,
        lastError: error instanceof Error ? error.message : String(error),
      });
    }
  },

  select: async (id) => {
    try {
      const project = await getProject(id);
      set({ active: project, lastError: null });
      set({
        projects: get().projects.map((item) =>
          item.id === project.id
            ? {
                ...item,
                status: project.status,
                updated_at: project.updated_at,
                outputs: project.outputs.map((output) => output.path),
              }
            : item,
        ),
      });
    } catch (error) {
      set({ lastError: error instanceof Error ? error.message : String(error) });
    }
  },

  applyUpdate: (project) => {
    set((state) => ({
      active: state.active?.id === project.id ? project : state.active,
      projects: state.projects.some((item) => item.id === project.id)
        ? state.projects.map((item) =>
            item.id === project.id
              ? {
                  ...item,
                  name: project.name,
                  status: project.status,
                  updated_at: project.updated_at,
                  media_path: project.media?.path ?? item.media_path,
                  workspace: project.workspace,
                  outputs: project.outputs.map((output) => output.path),
                }
              : item,
          )
        : [
            {
              id: project.id,
              name: project.name,
              status: project.status,
              created_at: project.created_at,
              updated_at: project.updated_at,
              media_path: project.media?.path ?? "",
              workspace: project.workspace,
              outputs: project.outputs.map((output) => output.path),
            },
            ...state.projects,
          ],
    }));
  },

  clearActive: () => set({ active: null }),

  preferProject: (id) => set({ preferredProjectId: id }),
}));

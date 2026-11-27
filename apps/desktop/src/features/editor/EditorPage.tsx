import { useCallback, useEffect, useMemo, useState } from "react";
import { useStore } from "zustand";
import { confirm } from "@tauri-apps/plugin-dialog";
import {
  ArrowLeft,
  CheckCircle2,
  Copy,
  LayoutGrid,
  Loader2,
  Play,
  Redo2,
  Save,
  SaveAll,
  Square,
  Trash2,
  Undo2,
  Wand2,
  XCircle,
} from "lucide-react";
import {
  cancelJob,
  createProject,
  deleteRecipe,
  getRecipe,
  listRecipes,
  listSteps,
  runRecipePayload,
  saveRecipe,
  validateRecipePayload,
} from "../../lib/api";
import type { RecipeSummary, StepSpec, ValidationResult } from "../../lib/models";
import { isVideoPath } from "../../lib/models";
import { layoutGraph, stripRecipeUi } from "../../lib/recipeGraph";
import { navigate } from "../../lib/router";
import { isEditorDirty, useEditorStore, type NewRecipeMode } from "../../stores/editorStore";
import { useRunStore } from "../../stores/runStore";
import { FlowCanvas } from "./FlowCanvas";
import { Inspector } from "./Inspector";
import { RunInputs } from "./RunInputs";
import { SaveAsDialog } from "./SaveAsDialog";
import { StepPanel } from "./StepPanel";

interface EditorPageProps {
  initialRecipeId: string | null;
  paths: string[];
}

function fileNameBase(path: string): string {
  const name = path.split(/[\\/]/).pop() ?? "";
  return name.replace(/\.[^.]+$/, "");
}

function projectNameForRun(recipeName: string, paths: string[]): string {
  const fromFile = paths.length > 0 ? fileNameBase(paths[0]) : "";
  return (fromFile || recipeName || "字幕流水线").slice(0, 120);
}

export function EditorPage({ initialRecipeId, paths }: EditorPageProps) {
  const [specs, setSpecs] = useState<StepSpec[]>([]);
  const [recipes, setRecipes] = useState<RecipeSummary[]>([]);
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [slots, setSlots] = useState<Record<string, string[]>>({});
  const [busy, setBusy] = useState(false);
  const [dialog, setDialog] = useState<null | "saveAs" | "duplicate">(null);

  const recipeId = useEditorStore((state) => state.recipeId);
  const name = useEditorStore((state) => state.name);
  const builtin = useEditorStore((state) => state.builtin);
  const inputs = useEditorStore((state) => state.inputs);
  const nodes = useEditorStore((state) => state.nodes);
  const issues = useEditorStore((state) => state.issues);
  const saveState = useEditorStore((state) => state.saveState);
  const savedAt = useEditorStore((state) => state.savedAt);
  const loadRecipe = useEditorStore((state) => state.loadRecipe);
  const newRecipe = useEditorStore((state) => state.newRecipe);
  const setMeta = useEditorStore((state) => state.setMeta);
  const setIssues = useEditorStore((state) => state.setIssues);
  const setSaveState = useEditorStore((state) => state.setSaveState);
  const markSaved = useEditorStore((state) => state.markSaved);
  const replaceNodes = useEditorStore((state) => state.replaceNodes);
  const toRecipe = useEditorStore((state) => state.toRecipe);

  const dirty = useEditorStore(isEditorDirty);
  const canUndo = useStore(useEditorStore.temporal, (state) => state.pastStates.length > 0);
  const canRedo = useStore(useEditorStore.temporal, (state) => state.futureStates.length > 0);

  const runStatus = useRunStore((state) => state.status);
  const runProgress = useRunStore((state) => state.progress);
  const runError = useRunStore((state) => state.lastError);
  const logs = useRunStore((state) => state.logs);
  const running = runStatus === "running";

  const refreshRecipes = useCallback(async () => {
    try {
      setRecipes(await listRecipes());
    } catch (error) {
      setNotice(error instanceof Error ? error.message : String(error));
    }
  }, []);

  useEffect(() => {
    let disposed = false;
    setLoading(true);
    setLoadError(null);
    void (async () => {
      try {
        const [stepList, recipeList] = await Promise.all([listSteps(), listRecipes()]);
        if (disposed) return;
        setSpecs(stepList);
        setRecipes(recipeList);
        if (initialRecipeId) {
          const recipe = await getRecipe(initialRecipeId);
          if (!disposed) loadRecipe(recipe, stepList);
        } else {
          newRecipe(stepList, "未命名配方");
        }
      } catch (error) {
        if (!disposed) {
          setLoadError(error instanceof Error ? error.message : String(error));
        }
      } finally {
        if (!disposed) setLoading(false);
      }
    })();
    return () => {
      disposed = true;
    };
  }, [initialRecipeId, loadRecipe, newRecipe]);

  useEffect(() => {
    const firstName = inputs[0]?.name;
    if (!firstName || paths.length === 0) return;
    setSlots((current) =>
      current[firstName]?.length ? current : { ...current, [firstName]: paths },
    );
  }, [inputs, paths]);

  const showNotice = useCallback((message: string | null) => {
    setNotice(message);
    if (message) window.setTimeout(() => setNotice(null), 6000);
  }, []);

  const validateNow = useCallback(async (): Promise<ValidationResult | null> => {
    try {
      const { recipe } = toRecipe();
      const result = await validateRecipePayload(recipe);
      setIssues([...result.errors, ...result.warnings], result.ok);
      if (!result.ok) {
        showNotice(`校验失败：${result.errors.length} 个错误（已在画布高亮）`);
      }
      return result;
    } catch (error) {
      showNotice(error instanceof Error ? error.message : String(error));
      return null;
    }
  }, [setIssues, showNotice, toRecipe]);

  const persist = useCallback(
    async (targetId?: string, targetName?: string) => {
      setBusy(true);
      try {
        if (targetId) setMeta({ recipeId: targetId, ...(targetName ? { name: targetName } : {}) });
        const result = await validateNow();
        if (!result?.ok) return;
        const { recipe } = toRecipe();
        if (recipe.builtin) {
          showNotice("内置配方只读，请使用“另存为”");
          return;
        }
        if (!recipe.id || recipe.id === "untitled") {
          showNotice("请先填写有效的配方 id（另存为）");
          setDialog("saveAs");
          return;
        }
        setSaveState("saving");
        const saved = await saveRecipe(recipe);
        markSaved(saved);
        await refreshRecipes();
        showNotice(`已保存配方 ${saved.id}`);
      } catch (error) {
        setSaveState("idle", error instanceof Error ? error.message : String(error));
        showNotice(error instanceof Error ? error.message : String(error));
      } finally {
        setBusy(false);
      }
    },
    [markSaved, refreshRecipes, setMeta, setSaveState, showNotice, toRecipe, validateNow],
  );

  const handleSave = useCallback(() => {
    if (builtin) {
      setDialog("saveAs");
      return;
    }
    if (!recipeId || recipeId === "untitled") {
      setDialog("saveAs");
      return;
    }
    void persist();
  }, [builtin, persist, recipeId]);

  const handleDelete = useCallback(async () => {
    if (builtin || !recipeId || recipeId === "untitled") return;
    const label = name.trim() || recipeId;
    try {
      const accepted = await confirm(
        `确定删除自定义配方「${label}」吗？\n\n只会删除该配方，已生成的字幕与项目不会受影响，删除后无法恢复。`,
        { title: "删除配方", kind: "warning", okLabel: "删除", cancelLabel: "取消" },
      );
      if (!accepted) return;
      setBusy(true);
      await deleteRecipe(recipeId);
      await refreshRecipes();
      newRecipe(specs, "未命名配方");
      navigate({ name: "editor", recipeId: null });
      showNotice(`已删除配方「${label}」`);
    } catch (error) {
      showNotice(error instanceof Error ? error.message : String(error));
    } finally {
      setBusy(false);
    }
  }, [builtin, name, newRecipe, recipeId, refreshRecipes, showNotice, specs]);

  const handleRun = useCallback(async () => {
    const missing = inputs.filter(
      (input) => input.required && (slots[input.name]?.length ?? 0) === 0,
    );
    if (missing.length > 0) {
      showNotice(
        `请先填写必填输入：${missing
          .map((input) => input.label?.trim() || input.name)
          .join("、")}`,
      );
      return;
    }
    const result = await validateNow();
    if (!result?.ok) return;
    setBusy(true);
    try {
      const { recipe } = toRecipe();
      setSaveState("saving");
      const inputsByName: Record<string, string[]> = {};
      for (const input of inputs) {
        const values = slots[input.name] ?? [];
        if (values.length > 0) inputsByName[input.name] = values;
      }
      const allPaths = Array.from(new Set(Object.values(inputsByName).flat()));
      const single = allPaths.length === 1 ? allPaths[0] : null;
      const project =
        single && isVideoPath(single)
          ? await createProject({ media_path: single })
          : await createProject({ name: projectNameForRun(name, allPaths) });
      const started = await runRecipePayload({
        recipe: stripRecipeUi(recipe),
        inputs: allPaths,
        inputsByName,
        projectId: project.id,
      });
      useRunStore.getState().begin(started.run_id, project.id);
      setSaveState(dirty ? "dirty" : "saved");
      showNotice(`已启动运行 ${started.run_id}`);
    } catch (error) {
      setSaveState(dirty ? "dirty" : "idle");
      showNotice(error instanceof Error ? error.message : String(error));
    } finally {
      setBusy(false);
    }
  }, [
    dirty,
    inputs,
    name,
    setSaveState,
    showNotice,
    slots,
    toRecipe,
    validateNow,
  ]);

  const handleSelect = useCallback(
    async (nextId: string, mode?: NewRecipeMode) => {
      if (!nextId) return;
      if (nextId === "__new__" || nextId === "__new_subtitle__") {
        const subtitle = nextId === "__new_subtitle__" || mode === "subtitle";
        newRecipe(
          specs,
          subtitle ? "未命名纯字幕流水线" : "未命名配方",
          subtitle ? "subtitle" : "video",
        );
        navigate({ name: "editor", recipeId: null });
        return;
      }
      try {
        const recipe = await getRecipe(nextId);
        loadRecipe(recipe, specs);
        navigate({ name: "editor", recipeId: nextId });
      } catch (error) {
        showNotice(error instanceof Error ? error.message : String(error));
      }
    },
    [loadRecipe, newRecipe, showNotice, specs],
  );

  const dialogDefaults = useMemo(() => {
    if (dialog === "duplicate") {
      const base = recipeId === "untitled" ? "my_pipeline" : `${recipeId}_copy`;
      return { id: base, name: `${name} 副本`, title: "复制预设" };
    }
    return {
      id: recipeId === "untitled" ? "my_pipeline" : `${recipeId}_copy`,
      name: name === "未命名配方" ? "我的流水线" : name,
      title: "另存为",
    };
  }, [dialog, name, recipeId]);

  useEffect(() => {
    const onKeyDown = (event: KeyboardEvent) => {
      const target = event.target as HTMLElement | null;
      const typing =
        target?.tagName === "INPUT" || target?.tagName === "TEXTAREA" || target?.isContentEditable;
      const mod = event.ctrlKey || event.metaKey;
      if (mod && event.key.toLowerCase() === "s") {
        event.preventDefault();
        handleSave();
        return;
      }
      if (!mod || typing) return;
      if (event.key.toLowerCase() === "z") {
        event.preventDefault();
        if (event.shiftKey) useEditorStore.temporal.getState().redo();
        else useEditorStore.temporal.getState().undo();
      } else if (event.key.toLowerCase() === "y") {
        event.preventDefault();
        useEditorStore.temporal.getState().redo();
      }
    };
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [handleSave]);

  const unsavedRecipe = !recipeId || recipeId === "untitled";
  const missingRequired = inputs.some(
    (input) => input.required && (slots[input.name]?.length ?? 0) === 0,
  );
  const statusText = unsavedRecipe
    ? "未保存的新配方"
    : saveState === "saving"
      ? "保存中…"
      : dirty
        ? "有未保存修改"
        : savedAt
          ? `已保存 ${new Date(savedAt).toLocaleTimeString()}`
          : builtin
            ? "内置配方只读"
            : "已保存";

  return (
    <div className="flex h-screen flex-col bg-slate-100 text-slate-900">
      <header className="flex flex-wrap items-center gap-2 border-b border-slate-200 bg-white px-3 py-2">
        <button
          type="button"
          onClick={() => navigate({ name: "home" })}
          className="inline-flex items-center gap-1 rounded-lg px-2 py-1.5 text-xs text-slate-600 hover:bg-slate-50"
        >
          <ArrowLeft className="h-3.5 w-3.5" /> 返回
        </button>

        <span className="flex items-center gap-1.5 text-sm font-semibold text-slate-800">
          流水线编辑器
          {builtin ? (
            <span className="rounded-full bg-amber-100 px-1.5 py-0.5 text-[10px] text-amber-700">
              内置 · 只读
            </span>
          ) : null}
        </span>

        <select
          value={recipeId}
          id="recipe-select"
          name="recipe-select"
          onChange={(event) => void handleSelect(event.target.value)}
          className="max-w-64 rounded-lg border border-slate-200 bg-white px-2 py-1.5 text-xs text-slate-700 outline-none focus:border-slate-400"
        >
          {recipeId === "untitled" ? <option value="untitled">{name}（未保存）</option> : null}
          {recipes.map((item) => (
            <option key={item.id} value={item.id}>
              {item.name} · {item.id}
              {item.builtin ? "（内置）" : ""}
            </option>
          ))}
          <option value="__new__">＋ 新建空白配方</option>
          <option value="__new_subtitle__">＋ 新建纯字幕流水线</option>
        </select>

        <span
          className={`inline-flex items-center gap-1 rounded-full px-2 py-1 text-[11px] ${
            dirty || unsavedRecipe ? "bg-amber-50 text-amber-700" : "bg-emerald-50 text-emerald-700"
          }`}
        >
          {dirty || unsavedRecipe ? <XCircle className="h-3 w-3" /> : <CheckCircle2 className="h-3 w-3" />}
          {statusText}
        </span>

        <div className="ml-auto flex flex-wrap items-center gap-1.5">
          <button
            type="button"
            title="撤销 (Ctrl+Z)"
            disabled={!canUndo}
            onClick={() => useEditorStore.temporal.getState().undo()}
            className="rounded-lg border border-slate-200 p-1.5 text-slate-600 hover:bg-slate-50 disabled:opacity-40"
          >
            <Undo2 className="h-3.5 w-3.5" />
          </button>
          <button
            type="button"
            title="重做 (Ctrl+Y)"
            disabled={!canRedo}
            onClick={() => useEditorStore.temporal.getState().redo()}
            className="rounded-lg border border-slate-200 p-1.5 text-slate-600 hover:bg-slate-50 disabled:opacity-40"
          >
            <Redo2 className="h-3.5 w-3.5" />
          </button>
          <button
            type="button"
            onClick={() => {
              const state = useEditorStore.getState();
              replaceNodes(layoutGraph(state.nodes, state.edges));
            }}
            className="inline-flex items-center gap-1 rounded-lg border border-slate-200 px-2 py-1.5 text-xs text-slate-600 hover:bg-slate-50"
          >
            <LayoutGrid className="h-3.5 w-3.5" /> 自动布局
          </button>
          <button
            type="button"
            onClick={() => void validateNow()}
            className="inline-flex items-center gap-1 rounded-lg border border-slate-200 px-2 py-1.5 text-xs text-slate-600 hover:bg-slate-50"
          >
            <Wand2 className="h-3.5 w-3.5" /> 校验
            {issues.length > 0 ? (
              <span className="rounded-full bg-red-100 px-1 text-[10px] text-red-700">{issues.length}</span>
            ) : null}
          </button>
          <button
            type="button"
            disabled={busy}
            onClick={() => setDialog("duplicate")}
            className="inline-flex items-center gap-1 rounded-lg border border-slate-200 px-2 py-1.5 text-xs text-slate-600 hover:bg-slate-50 disabled:opacity-40"
          >
            <Copy className="h-3.5 w-3.5" /> 复制预设
          </button>
          <button
            type="button"
            data-testid="delete-recipe"
            title={
              builtin
                ? "内置配方不能删除"
                : !recipeId || recipeId === "untitled"
                  ? "未保存的配方无需删除"
                  : "删除当前自定义配方"
            }
            disabled={busy || builtin || !recipeId || recipeId === "untitled"}
            onClick={() => void handleDelete()}
            className="inline-flex items-center gap-1 rounded-lg border border-slate-200 px-2 py-1.5 text-xs text-red-600 hover:bg-red-50 disabled:opacity-40"
          >
            <Trash2 className="h-3.5 w-3.5" /> 删除
          </button>
          <button
            type="button"
            disabled={busy || builtin}
            onClick={handleSave}
            className="inline-flex items-center gap-1 rounded-lg border border-slate-200 px-2 py-1.5 text-xs text-slate-600 hover:bg-slate-50 disabled:opacity-40"
          >
            {busy && saveState === "saving" ? (
              <Loader2 className="h-3.5 w-3.5 animate-spin" />
            ) : (
              <Save className="h-3.5 w-3.5" />
            )}
            保存
          </button>
          <button
            type="button"
            disabled={busy}
            onClick={() => setDialog("saveAs")}
            className="inline-flex items-center gap-1 rounded-lg border border-slate-200 px-2 py-1.5 text-xs text-slate-600 hover:bg-slate-50 disabled:opacity-40"
          >
            <SaveAll className="h-3.5 w-3.5" /> 另存为
          </button>
        </div>
      </header>

      {loadError ? (
        <div className="m-4 rounded-xl border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700">
          加载编辑器失败：{loadError}
        </div>
      ) : null}

      <div className="flex min-h-0 flex-1">
        <StepPanel specs={specs} onAdd={(spec) => {
          const state = useEditorStore.getState();
          const offset = state.nodes.length * 40;
          state.addStep(spec, { x: 80 + offset, y: 80 + offset });
        }} />
        <main className="relative min-w-0 flex-1">
          {loading ? (
            <div className="flex h-full items-center justify-center text-sm text-slate-500">
              <Loader2 className="mr-2 h-4 w-4 animate-spin" /> 正在加载步骤与配方…
            </div>
          ) : (
            <FlowCanvas />
          )}
          <div className="absolute bottom-3 left-3 z-10 flex w-[min(42rem,calc(100%-1.5rem))] flex-col gap-2 rounded-xl border border-slate-200 bg-white/95 px-2.5 py-2 shadow-sm">
            <RunInputs
              inputs={inputs}
              slots={slots}
              disabled={busy || running}
              onChange={(inputName, next) =>
                setSlots((current) => ({ ...current, [inputName]: next }))
              }
              onError={showNotice}
            />
            <div className="flex items-center justify-end gap-2">
              {running ? (
                <button
                  type="button"
                  onClick={() => {
                    const jobId = useRunStore.getState().runId;
                    if (jobId) void cancelJob(jobId).catch((error) => showNotice(String(error)));
                  }}
                  className="inline-flex shrink-0 items-center gap-1 rounded-lg bg-red-600 px-2.5 py-1 text-[11px] font-medium text-white hover:bg-red-500"
                >
                  <Square className="h-3 w-3" /> 取消
                </button>
              ) : (
                <button
                  type="button"
                  disabled={busy || missingRequired || nodes.length === 0}
                  onClick={() => void handleRun()}
                  className="inline-flex shrink-0 items-center gap-1 rounded-lg bg-slate-900 px-2.5 py-1 text-[11px] font-medium text-white hover:bg-slate-800 disabled:cursor-not-allowed disabled:bg-slate-300"
                >
                  <Play className="h-3 w-3" /> 运行
                </button>
              )}
            </div>
          </div>

          {runStatus !== "idle" ? (
            <div className="absolute bottom-3 right-3 z-10 w-72 rounded-xl border border-slate-200 bg-white/95 p-2.5 shadow-sm">
              <div className="flex items-center justify-between text-[11px] text-slate-500">
                <span>
                  {runStatus === "running"
                    ? "运行中…"
                    : runStatus === "done"
                      ? "运行完成"
                      : runStatus === "cancelled"
                        ? "已取消"
                        : "运行失败"}
                </span>
                <span>{Math.round(runProgress * 100)}%</span>
              </div>
              <div className="mt-1 h-1.5 overflow-hidden rounded-full bg-slate-200">
                <div
                  className={`h-full rounded-full ${
                    runStatus === "failed" ? "bg-red-500" : runStatus === "done" ? "bg-emerald-500" : "bg-sky-500"
                  }`}
                  style={{ width: `${Math.round(runProgress * 100)}%` }}
                />
              </div>
              {runError ? <p className="mt-1 line-clamp-3 text-[11px] text-red-600">{runError}</p> : null}
              {logs.length > 0 ? (
                <p className="mt-1 truncate font-mono text-[10px] text-slate-400">
                  {logs[logs.length - 1]?.type}: {logs[logs.length - 1]?.message}
                </p>
              ) : null}
            </div>
          ) : null}
        </main>
        <Inspector />
      </div>

      {notice ? (
        <div className="pointer-events-none fixed left-1/2 top-14 z-40 -translate-x-1/2">
          <p className="rounded-lg border border-slate-200 bg-white px-3 py-1.5 text-xs text-slate-700 shadow-lg">
            {notice}
          </p>
        </div>
      ) : null}

      <SaveAsDialog
        open={dialog !== null}
        title={dialogDefaults.title}
        initialId={dialogDefaults.id}
        initialName={dialogDefaults.name}
        confirmText={dialog === "duplicate" ? "复制并保存" : "保存"}
        onCancel={() => setDialog(null)}
        onConfirm={(id, nextName) => {
          setDialog(null);
          void persist(id, nextName);
        }}
      />
    </div>
  );
}

import { useCallback, useEffect, useMemo, useState } from "react";
import {
  AlertCircle,
  ArrowLeft,
  Check,
  CheckCheck,
  ChevronRight,
  ClipboardCheck,
  FileText,
  Loader2,
  RotateCcw,
  ShieldCheck,
  Sparkles,
  X,
} from "lucide-react";
import { navigate } from "../../lib/router";
import type { ReviewItem } from "../../lib/models";
import { useReviewStore, type DecisionValue } from "../../stores/reviewStore";
import { useRunStore } from "../../stores/runStore";
import { DiffPanel } from "./DiffPanel";

interface ReviewPageProps {
  runId: string;
}

function formatTime(ms: number): string {
  const total = Math.max(0, Math.round(ms));
  const seconds = Math.floor(total / 1000);
  const minutes = Math.floor(seconds / 60);
  const rest = seconds % 60;
  const millis = total % 1000;
  return `${String(minutes).padStart(2, "0")}:${String(rest).padStart(2, "0")}.${String(millis).padStart(3, "0")}`;
}

function decisionLabel(item: ReviewItem, decision: DecisionValue | undefined): string {
  if (decision === "accept") return "已接受";
  if (decision === "reject") return "已拒绝";
  if (item.status === "accepted") return "已接受";
  if (item.status === "rejected") return "已拒绝";
  return "待审";
}

const ACTION_TEXT: Record<ReviewItem["action"], string> = {
  keep: "保留",
  remove: "删除",
  rewrite: "改写",
};

const SOURCE_TEXT: Record<ReviewItem["source"], string> = {
  rules: "规则",
  agent: "Agent",
  human: "人工",
};

export function ReviewPage({ runId }: ReviewPageProps) {
  const items = useReviewStore((state) => state.items);
  const decisions = useReviewStore((state) => state.decisions);
  const afterEdits = useReviewStore((state) => state.afterEdits);
  const loading = useReviewStore((state) => state.loading);
  const submitting = useReviewStore((state) => state.submitting);
  const undoing = useReviewStore((state) => state.undoing);
  const submitted = useReviewStore((state) => state.submitted);
  const undoResult = useReviewStore((state) => state.undoResult);
  const lastError = useReviewStore((state) => state.lastError);
  const load = useReviewStore((state) => state.load);
  const setDecision = useReviewStore((state) => state.setDecision);
  const setAfter = useReviewStore((state) => state.setAfter);
  const acceptHighConfidence = useReviewStore((state) => state.acceptHighConfidence);
  const rejectAll = useReviewStore((state) => state.rejectAll);
  const submit = useReviewStore((state) => state.submit);
  const undo = useReviewStore((state) => state.undo);
  const reset = useReviewStore((state) => state.reset);

  const [selectedId, setSelectedId] = useState<string | null>(null);

  useEffect(() => {
    void load(runId);
    return () => reset();
  }, [runId, load, reset]);

  const sorted = useMemo(
    () =>
      [...items].sort(
        (a, b) => b.confidence - a.confidence || a.segment_index - b.segment_index,
      ),
    [items],
  );

  const selected = useMemo(
    () => sorted.find((item) => item.id === selectedId) ?? sorted[0] ?? null,
    [sorted, selectedId],
  );

  const decidedCount = useMemo(
    () => items.reduce((count, item) => (decisions[item.id] ? count + 1 : count), 0),
    [items, decisions],
  );

  const currentAfter = selected
    ? (afterEdits[selected.id] ?? selected.after)
    : "";

  const move = useCallback(
    (delta: number) => {
      if (sorted.length === 0) return;
      const index = selected ? sorted.findIndex((item) => item.id === selected.id) : -1;
      const next = Math.min(Math.max(index + delta, 0), sorted.length - 1);
      const target = sorted[next];
      if (target) setSelectedId(target.id);
    },
    [selected, sorted],
  );

  const decideSelected = useCallback(
    (value: DecisionValue) => {
      if (!selected) return;
      setDecision(selected.id, value);
      const state = useReviewStore.getState();
      const index = sorted.findIndex((item) => item.id === selected.id);
      const ordered = [...sorted.slice(index + 1), ...sorted.slice(0, index)];
      const next = ordered.find((item) => !state.decisions[item.id]);
      if (next) setSelectedId(next.id);
    },
    [selected, setDecision, sorted],
  );

  const handleSubmit = useCallback(async () => {
    await submit(runId);
    const state = useReviewStore.getState();
    if (state.lastError) return;
    if (useRunStore.getState().runId === runId) {
      useRunStore.setState({ status: "running" });
    }
  }, [runId, submit]);

  const handleUndo = useCallback(async () => {
    await undo(runId);
  }, [runId, undo]);

  useEffect(() => {
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.ctrlKey || event.metaKey || event.altKey) return;
      const target = event.target as HTMLElement | null;
      if (
        target &&
        (target.tagName === "INPUT" ||
          target.tagName === "TEXTAREA" ||
          target.tagName === "SELECT" ||
          target.isContentEditable)
      ) {
        return;
      }
      switch (event.key.toLowerCase()) {
        case "j":
          event.preventDefault();
          move(1);
          break;
        case "k":
          event.preventDefault();
          move(-1);
          break;
        case "a":
          event.preventDefault();
          decideSelected("accept");
          break;
        case "r":
          event.preventDefault();
          decideSelected("reject");
          break;
        default:
          break;
      }
    };
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [decideSelected, move]);

  const progressTotal = items.length;
  const progressDone = submitted ? progressTotal : decidedCount;

  return (
    <div className="min-h-screen bg-slate-100 px-5 py-6 text-slate-900">
      <div className="mx-auto max-w-6xl space-y-5">
        <header className="flex flex-wrap items-center justify-between gap-3">
          <div className="flex items-center gap-3">
            <button
              type="button"
              onClick={() => navigate({ name: "home" })}
              className="inline-flex items-center gap-1.5 rounded-full border border-slate-300 bg-white px-3 py-1.5 text-xs font-medium text-slate-700 hover:bg-slate-50"
            >
              <ArrowLeft className="h-3.5 w-3.5" /> 返回
            </button>
            <div>
              <h1 className="flex items-center gap-2 text-xl font-semibold tracking-tight">
                <ShieldCheck className="h-5 w-5 text-slate-500" /> 人工审核
              </h1>
              <p className="font-mono text-xs text-slate-500" title={runId}>
                run_id: {runId}
              </p>
            </div>
          </div>

          <div className="flex flex-wrap items-center gap-2">
            <span className="inline-flex items-center gap-1.5 rounded-full border border-slate-200 bg-white px-3 py-1.5 text-xs text-slate-600">
              <ClipboardCheck className="h-3.5 w-3.5" />
              进度 {progressDone}/{progressTotal}
            </span>
            <button
              type="button"
              data-testid="submit-review"
              disabled={progressTotal === 0 || submitted || submitting}
              onClick={() => void handleSubmit()}
              className="inline-flex items-center gap-1.5 rounded-lg bg-slate-900 px-4 py-2 text-sm font-medium text-white hover:bg-slate-800 disabled:cursor-not-allowed disabled:bg-slate-300"
            >
              {submitting ? (
                <Loader2 className="h-4 w-4 animate-spin" />
              ) : (
                <CheckCheck className="h-4 w-4" />
              )}
              {submitting ? "提交中…" : "提交审核"}
            </button>
            {submitted && (
              <button
                type="button"
                data-testid="undo-review"
                disabled={undoing}
                onClick={() => void handleUndo()}
                className="inline-flex items-center gap-1.5 rounded-lg border border-amber-300 bg-amber-50 px-3 py-2 text-sm font-medium text-amber-800 hover:bg-amber-100 disabled:opacity-50"
              >
                {undoing ? (
                  <Loader2 className="h-4 w-4 animate-spin" />
                ) : (
                  <RotateCcw className="h-4 w-4" />
                )}
                撤销本次审核
              </button>
            )}
          </div>
        </header>

        {lastError && (
          <div
            role="alert"
            className="flex items-start gap-2 rounded-xl border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700"
          >
            <AlertCircle className="mt-0.5 h-4 w-4 shrink-0" />
            <span>{lastError}</span>
          </div>
        )}

        {submitted && (
          <div className="flex items-start gap-2 rounded-xl border border-emerald-200 bg-emerald-50 px-4 py-3 text-sm text-emerald-800">
            <Check className="mt-0.5 h-4 w-4 shrink-0" />
            <span>审核已提交，引擎将恢复运行。如需回退，可撤销本次审核。</span>
          </div>
        )}

        {undoResult && (
          <section className="rounded-xl border border-amber-200 bg-amber-50/70 px-4 py-3 text-sm text-amber-900">
            <p className="flex items-center gap-2 font-medium">
              <RotateCcw className="h-4 w-4" /> 已撤销审核，产物已恢复
            </p>
            <p className="mt-1 break-all font-mono text-xs text-amber-800">
              审计日志：{undoResult.audit_path}
            </p>
            {undoResult.restored.length > 0 && (
              <ul className="mt-2 space-y-1">
                {undoResult.restored.map((artifact) => (
                  <li key={artifact.path} className="break-all font-mono text-xs text-amber-800">
                    {artifact.path}
                  </li>
                ))}
              </ul>
            )}
          </section>
        )}

        <div className="grid gap-5 lg:grid-cols-[minmax(0,340px)_minmax(0,1fr)]">
          <section className="flex min-h-[420px] flex-col rounded-2xl border border-slate-200 bg-white p-4">
            <div className="flex flex-wrap items-center justify-between gap-2">
              <h2 className="text-sm font-semibold text-slate-800">待审列表</h2>
              <span className="text-xs text-slate-500">按置信度降序</span>
            </div>

            <div className="mt-3 flex flex-wrap gap-2">
              <button
                type="button"
                data-testid="accept-high-confidence"
                disabled={items.length === 0 || submitted}
                onClick={() => acceptHighConfidence(0.8)}
                className="inline-flex items-center gap-1 rounded-lg border border-emerald-200 bg-emerald-50 px-2 py-1 text-[11px] font-medium text-emerald-700 hover:bg-emerald-100 disabled:opacity-40"
              >
                <Sparkles className="h-3 w-3" /> 接受高置信度
              </button>
              <button
                type="button"
                data-testid="reject-all"
                disabled={items.length === 0 || submitted}
                onClick={() => rejectAll()}
                className="inline-flex items-center gap-1 rounded-lg border border-red-200 bg-red-50 px-2 py-1 text-[11px] font-medium text-red-700 hover:bg-red-100 disabled:opacity-40"
              >
                <X className="h-3 w-3" /> 全部拒绝
              </button>
            </div>

            <div className="mt-3 min-h-0 flex-1 space-y-1.5 overflow-auto">
              {loading && items.length === 0 ? (
                <p className="flex items-center justify-center py-8 text-xs text-slate-500">
                  <Loader2 className="mr-2 h-4 w-4 animate-spin" /> 正在加载审核项…
                </p>
              ) : sorted.length === 0 ? (
                <p className="rounded-lg bg-slate-50 px-3 py-6 text-center text-xs text-slate-500">
                  没有待审核项。
                </p>
              ) : (
                sorted.map((item) => {
                  const decision = decisions[item.id];
                  const active = selected?.id === item.id;
                  return (
                    <button
                      key={item.id}
                      type="button"
                      data-testid={`review-item-${item.id}`}
                      onClick={() => setSelectedId(item.id)}
                      className={`w-full rounded-xl border px-3 py-2 text-left transition ${
                        active
                          ? "border-slate-900 bg-slate-50"
                          : "border-slate-200 bg-white hover:bg-slate-50"
                      }`}
                    >
                      <div className="flex items-center justify-between gap-2">
                        <span className="flex items-center gap-1 font-mono text-xs font-medium text-slate-700">
                          <FileText className="h-3 w-3 text-slate-400" />#{item.segment_index}
                        </span>
                        <span
                          className={`rounded-full px-1.5 py-0.5 text-[10px] ${
                            decision === "accept" || (!decision && item.status === "accepted")
                              ? "bg-emerald-100 text-emerald-700"
                              : decision === "reject" || (!decision && item.status === "rejected")
                                ? "bg-red-100 text-red-700"
                                : "bg-slate-100 text-slate-500"
                          }`}
                        >
                          {decisionLabel(item, decision)}
                        </span>
                      </div>
                      <p className="mt-1 truncate text-xs text-slate-600" title={item.reason || item.before}>
                        {item.reason || "无说明"}
                      </p>
                      <div className="mt-1 flex items-center justify-between gap-2">
                        <span className="truncate font-mono text-[11px] text-slate-400" title={item.before}>
                          {item.before || "（空）"}
                        </span>
                        <span className="shrink-0 text-[10px] text-slate-400">
                          {Math.round(item.confidence * 100)}%
                        </span>
                      </div>
                    </button>
                  );
                })
              )}
            </div>
          </section>

          <section className="rounded-2xl border border-slate-200 bg-white p-4">
            {selected ? (
              <div className="space-y-4" data-testid="review-detail">
                <div className="flex flex-wrap items-start justify-between gap-2">
                  <div>
                    <h2 className="text-sm font-semibold text-slate-800">
                      段落 #{selected.segment_index}
                      <span className="ml-2 font-mono text-[11px] font-normal text-slate-400">
                        {formatTime(selected.start_ms)} → {formatTime(selected.end_ms)}
                      </span>
                    </h2>
                    <p className="mt-1 text-xs text-slate-500">
                      {selected.reason || "无说明"}
                    </p>
                  </div>
                  <div className="flex flex-wrap items-center gap-1.5 text-[11px]">
                    <span className="rounded-full bg-slate-100 px-2 py-0.5 text-slate-600">
                      {SOURCE_TEXT[selected.source]}
                    </span>
                    <span className="rounded-full bg-sky-50 px-2 py-0.5 text-sky-700">
                      建议：{ACTION_TEXT[selected.action]}
                    </span>
                    <span className="rounded-full bg-slate-100 px-2 py-0.5 font-mono text-slate-600">
                      置信度 {Math.round(selected.confidence * 100)}%
                    </span>
                  </div>
                </div>

                {selected.reasons.length > 0 && (
                  <div className="flex flex-wrap gap-1.5">
                    {selected.reasons.map((reason) => (
                      <span
                        key={reason}
                        className="rounded-full border border-slate-200 px-2 py-0.5 font-mono text-[10px] text-slate-500"
                      >
                        {reason}
                      </span>
                    ))}
                  </div>
                )}

                <DiffPanel before={selected.before} after={currentAfter} />

                <div>
                  <label
                    htmlFor="review-after-editor"
                    className="text-xs font-medium text-slate-600"
                  >
                    修改后的文本
                  </label>
                  <textarea
                    id="review-after-editor"
                    value={currentAfter}
                    disabled={submitted}
                    onChange={(event) => setAfter(selected.id, event.target.value)}
                    rows={3}
                    className="mt-1 w-full rounded-lg border border-slate-200 bg-white px-3 py-2 font-mono text-xs text-slate-800 outline-none focus:border-slate-400 disabled:bg-slate-50 disabled:text-slate-500"
                  />
                  <p className="mt-1 text-[11px] text-slate-400">
                    编辑后将作为改写结果随决策提交；留空表示删除该段文本。
                  </p>
                </div>

                <div className="flex flex-wrap items-center gap-2 border-t border-slate-100 pt-3">
                  <button
                    type="button"
                    data-testid="accept-current"
                    disabled={submitted}
                    onClick={() => decideSelected("accept")}
                    className="inline-flex items-center gap-1.5 rounded-lg bg-emerald-600 px-3 py-2 text-sm font-medium text-white hover:bg-emerald-500 disabled:bg-slate-300"
                  >
                    <Check className="h-4 w-4" /> 接受
                    <kbd className="ml-1 rounded bg-emerald-700/40 px-1 text-[10px]">A</kbd>
                  </button>
                  <button
                    type="button"
                    data-testid="reject-current"
                    disabled={submitted}
                    onClick={() => decideSelected("reject")}
                    className="inline-flex items-center gap-1.5 rounded-lg border border-red-200 bg-red-50 px-3 py-2 text-sm font-medium text-red-700 hover:bg-red-100 disabled:opacity-40"
                  >
                    <X className="h-4 w-4" /> 拒绝
                    <kbd className="ml-1 rounded bg-red-100 px-1 text-[10px]">R</kbd>
                  </button>
                  <span className="ml-auto text-[11px] text-slate-400">
                    快捷键：J/K 切换 · A 接受 · R 拒绝
                  </span>
                </div>

                {items.length > 1 && (
                  <div className="flex flex-wrap gap-1.5">
                    {sorted.map((item) => (
                      <button
                        key={item.id}
                        type="button"
                        onClick={() => setSelectedId(item.id)}
                        title={`#${item.segment_index} · ${Math.round(item.confidence * 100)}%`}
                        className={`inline-flex items-center rounded px-1.5 py-0.5 font-mono text-[10px] ${
                          item.id === selected.id
                            ? "bg-slate-900 text-white"
                            : decisions[item.id] === "accept"
                              ? "bg-emerald-100 text-emerald-700"
                              : decisions[item.id] === "reject"
                                ? "bg-red-100 text-red-700"
                                : "bg-slate-100 text-slate-500"
                        }`}
                      >
                        {item.segment_index}
                      </button>
                    ))}
                  </div>
                )}
              </div>
            ) : (
              <div className="flex h-full min-h-[320px] flex-col items-center justify-center text-center text-sm text-slate-500">
                {loading ? (
                  <>
                    <Loader2 className="mb-2 h-5 w-5 animate-spin" />
                    正在加载审核项…
                  </>
                ) : (
                  <>
                    <ShieldCheck className="mb-2 h-8 w-8 text-slate-300" />
                    <p>没有需要人工审核的字幕项。</p>
                    <p className="mt-1 text-xs text-slate-400">
                      运行可能尚未到达人工审核步骤，或审核已提交。
                    </p>
                    <button
                      type="button"
                      onClick={() => navigate({ name: "home" })}
                      className="mt-4 inline-flex items-center gap-1 rounded-lg border border-slate-200 px-3 py-1.5 text-xs text-slate-600 hover:bg-slate-50"
                    >
                      回到首页 <ChevronRight className="h-3.5 w-3.5" />
                    </button>
                  </>
                )}
              </div>
            )}
          </section>
        </div>
      </div>
    </div>
  );
}

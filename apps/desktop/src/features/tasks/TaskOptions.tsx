import { useEffect, useMemo, useState } from "react";
import { AlertTriangle, Languages, Loader2 } from "lucide-react";
import { inspectMedia } from "../../lib/api";
import type {
  MediaInfo,
  MediaSubtitleTrack,
  RecipeDefinition,
  StepSpec,
  TaskSpec,
} from "../../lib/models";
import type { TrackSelection } from "../../stores/taskStore";
import { SchemaForm } from "../editor/SchemaForm";

interface TaskOptionsProps {
  task: TaskSpec;
  steps: StepSpec[];
  recipe: RecipeDefinition | null;
  options: Record<string, Record<string, unknown>>;
  selection: TrackSelection | undefined;
  videoPath: string | null;
  disabled?: boolean;
  onOptionsChange: (taskId: string, stepId: string, values: Record<string, unknown>) => void;
  onSelectionChange: (taskId: string, selection: TrackSelection) => void;
}

const LANGUAGE_NAMES: Record<string, string> = {
  zh: "中文",
  chi: "中文",
  zho: "中文",
  en: "英语",
  eng: "英语",
  ja: "日语",
  jpn: "日语",
  ko: "韩语",
  kor: "韩语",
  fr: "法语",
  de: "德语",
  es: "西班牙语",
  ru: "俄语",
};

function languageLabel(language: string): string {
  const code = language.trim().toLowerCase();
  if (!code || code === "und") return "未标注语言";
  const name = LANGUAGE_NAMES[code];
  return name ? `${name} (${language})` : language;
}

function isExtractionTask(task: TaskSpec): boolean {
  return (
    task.id === "video_to_clean_srt" ||
    task.id === "fn_extract_subtitles" ||
    task.recipe_id === "video_to_clean_srt"
  );
}

/** 去掉 media.extract_subtitles 的 tracks 字段：轨道由专用选择器提供。 */
function withoutTracks(schema: Record<string, unknown>): Record<string, unknown> {
  const copy: Record<string, unknown> = { ...schema };
  if (typeof copy.properties === "object" && copy.properties !== null) {
    const properties = { ...(copy.properties as Record<string, unknown>) };
    delete properties.tracks;
    copy.properties = properties;
  }
  if (Array.isArray(copy.required)) {
    copy.required = copy.required.filter((item) => item !== "tracks");
  }
  return copy;
}

function recommendedTrack(info: MediaInfo): MediaSubtitleTrack | null {
  const preferred = info.default_audio_lang?.trim().toLowerCase();
  if (preferred) {
    const match = info.subtitles.find(
      (track) => track.language?.trim().toLowerCase() === preferred,
    );
    if (match) return match;
  }
  return info.subtitles.find((track) => !track.forced) ?? info.subtitles[0] ?? null;
}

function trackLabel(track: MediaSubtitleTrack): string {
  const parts = [languageLabel(track.language)];
  if (track.title?.trim()) parts.push(track.title.trim());
  if (track.default) parts.push("默认");
  if (track.forced) parts.push("强制");
  if (track.hearing_impaired) parts.push("SDH");
  return parts.join(" · ");
}

interface TrackSelectorProps {
  taskId: string;
  videoPath: string;
  selection: TrackSelection | undefined;
  disabled: boolean;
  onSelectionChange: (taskId: string, selection: TrackSelection) => void;
}

function TrackSelector({
  taskId,
  videoPath,
  selection,
  disabled,
  onSelectionChange,
}: TrackSelectorProps) {
  const [info, setInfo] = useState<MediaInfo | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!videoPath) {
      setInfo(null);
      setError(null);
      setLoading(false);
      return;
    }
    let disposed = false;
    setLoading(true);
    setInfo(null);
    setError(null);
    const timer = window.setTimeout(() => {
      void inspectMedia(videoPath)
        .then((result) => {
          if (disposed) return;
          setInfo(result);
          setError(null);
        })
        .catch((reason) => {
          if (disposed) return;
          setInfo(null);
          setError(reason instanceof Error ? reason.message : String(reason));
        })
        .finally(() => {
          if (!disposed) setLoading(false);
        });
    }, 300);

    return () => {
      disposed = true;
      window.clearTimeout(timer);
    };
  }, [videoPath]);

  const tracks = info?.subtitles ?? [];
  const recommended = info ? recommendedTrack(info) : null;

  // 默认采用引擎推荐轨道；用户已明确选择（含自动）后不再覆盖。
  useEffect(() => {
    if (!info || info.subtitles.length === 0) return;
    if (selection !== undefined) return;
    onSelectionChange(taskId, {
      mode: "manual",
      indices: recommended ? [recommended.index] : [],
    });
  }, [info, recommended, selection, taskId, onSelectionChange]);

  // 换视频后旧轨道索引可能不存在，自动回退到新视频的推荐轨道。
  useEffect(() => {
    if (!info || selection?.mode !== "manual") return;
    const valid = new Set(info.subtitles.map((track) => track.index));
    if (selection.indices.every((index) => valid.has(index))) return;
    onSelectionChange(taskId, {
      mode: "manual",
      indices: recommended ? [recommended.index] : [],
    });
  }, [info, recommended, selection, taskId, onSelectionChange]);

  const ensureSelection = (): TrackSelection =>
    selection ?? { mode: "manual", indices: recommended ? [recommended.index] : [] };

  const toggleTrack = (track: MediaSubtitleTrack) => {
    const current = ensureSelection();
    const next = current.indices.includes(track.index)
      ? current.indices.filter((index) => index !== track.index)
      : [...current.indices, track.index];
    onSelectionChange(taskId, { mode: "manual", indices: next });
  };

  return (
    <div className="mt-4 rounded-xl border border-slate-200 bg-slate-50/60 p-3">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <p className="flex items-center gap-1.5 text-xs font-medium text-slate-600">
          <Languages className="h-3.5 w-3.5" /> 字幕轨道
        </p>
        {loading && (
          <span className="inline-flex items-center gap-1 text-[11px] text-slate-400">
            <Loader2 className="h-3 w-3 animate-spin" /> 正在读取媒体信息…
          </span>
        )}
      </div>

      {!videoPath ? (
        <p className="mt-2 text-xs text-slate-400">先选择视频文件后即可检测字幕轨道。</p>
      ) : error ? (
        <p role="alert" className="mt-2 rounded-lg border border-amber-200 bg-amber-50 px-2 py-1.5 text-xs text-amber-800">
          无法读取媒体信息：{error}
        </p>
      ) : info && tracks.length === 0 ? (
        <p className="mt-2 rounded-lg border border-amber-200 bg-amber-50 px-2 py-1.5 text-xs text-amber-800">
          未检测到内嵌字幕轨道；将无法提取字幕。
        </p>
      ) : info ? (
        <div className="mt-2 space-y-2">
          <div role="radiogroup" aria-label="轨道选择方式" className="flex flex-wrap gap-3">
            <label className="inline-flex items-center gap-1.5 text-xs text-slate-700">
              <input
                type="radio"
                name={`tracks-mode-${taskId}`}
                checked={ensureSelection().mode === "auto"}
                disabled={disabled}
                onChange={() => onSelectionChange(taskId, { mode: "auto", indices: [] })}
                className="h-3.5 w-3.5"
              />
              自动选择（使用引擎推荐）
            </label>
            <label className="inline-flex items-center gap-1.5 text-xs text-slate-700">
              <input
                type="radio"
                name={`tracks-mode-${taskId}`}
                checked={ensureSelection().mode === "manual"}
                disabled={disabled}
                onChange={() =>
                  onSelectionChange(taskId, {
                    mode: "manual",
                    indices:
                      ensureSelection().indices.length > 0
                        ? ensureSelection().indices
                        : recommended
                          ? [recommended.index]
                          : [],
                  })
                }
                className="h-3.5 w-3.5"
              />
              手动选择
            </label>
          </div>

          <ul className="space-y-1">
            {tracks.map((track) => {
              const current = ensureSelection();
              const checked =
                current.mode === "manual" && current.indices.includes(track.index);
              const isRecommended = recommended?.index === track.index;
              return (
                <li key={`${track.index}-${track.language}`}>
                  <label className="flex items-start gap-2 rounded-lg bg-white px-2 py-1.5 text-xs text-slate-700">
                    <input
                      type="checkbox"
                      checked={checked}
                      disabled={disabled || current.mode === "auto"}
                      onChange={() => toggleTrack(track)}
                      className="mt-0.5 h-3.5 w-3.5 rounded border-slate-300"
                    />
                    <span className="min-w-0">
                      <span className="flex flex-wrap items-center gap-1">
                        <span className="font-medium">#{track.index}</span>
                        <span>{trackLabel(track)}</span>
                        {isRecommended && (
                          <span className="rounded bg-emerald-100 px-1.5 py-0.5 text-[10px] text-emerald-700">
                            推荐
                          </span>
                        )}
                      </span>
                      {track.codec_name && (
                        <span className="mt-0.5 block font-mono text-[10px] text-slate-400">
                          {track.codec_name}
                        </span>
                      )}
                    </span>
                  </label>
                </li>
              );
            })}
          </ul>

          {ensureSelection().mode === "manual" && ensureSelection().indices.length === 0 && (
            <p className="text-[11px] text-rose-600">请至少选择一条字幕轨道，或切换为自动选择。</p>
          )}
          {info.warnings.length > 0 && (
            <p className="flex items-start gap-1 text-[11px] text-amber-700">
              <AlertTriangle className="mt-0.5 h-3 w-3 shrink-0" />
              {info.warnings.join("；")}
            </p>
          )}
        </div>
      ) : null}
    </div>
  );
}

/** 渲染任务相关步骤的参数；审核步骤不显示，提取步骤额外显示轨道选择器。 */
export function TaskOptions({
  task,
  steps,
  recipe,
  options,
  selection,
  videoPath,
  disabled = false,
  onOptionsChange,
  onSelectionChange,
}: TaskOptionsProps) {
  const extraction = isExtractionTask(task);
  const specById = useMemo(() => new Map(steps.map((step) => [step.id, step])), [steps]);

  const visible = useMemo(
    () =>
      (recipe?.steps ?? []).filter((step) => {
        if (step.uses === "human.review") return false;
        const spec = specById.get(step.uses);
        if (!spec) return false;
        const properties = spec.options_schema.properties;
        return (
          typeof properties === "object" &&
          properties !== null &&
          Object.keys(properties).length > 0
        );
      }),
    [recipe, specById],
  );

  if (!recipe) {
    return <p className="text-sm text-slate-500">正在读取任务配方…</p>;
  }

  if (visible.length === 0 && !extraction) {
    return <p className="text-sm text-slate-500">此任务没有可配置参数。</p>;
  }

  return (
    <div className="space-y-5">
      {visible.map((step) => {
        const spec = specById.get(step.uses);
        if (!spec) return null;
        const isExtractStep = step.uses === "media.extract_subtitles";
        const schema = isExtractStep
          ? withoutTracks(spec.options_schema)
          : spec.options_schema;
        const value = {
          ...step.with,
          ...(options[step.id] ?? {}),
        };
        return (
          <div key={step.id} data-testid={`task-options-${step.id}`}>
            <div className="mb-2 flex items-baseline justify-between gap-2">
              <h4 className="text-sm font-semibold text-slate-800">{spec.title}</h4>
              <span className="font-mono text-[10px] text-slate-400">{spec.id}</span>
            </div>
            {spec.description && (
              <p className="mb-2 text-[11px] text-slate-400">{spec.description}</p>
            )}
            {Object.keys(schema?.properties ?? {}).length === 0 ? (
              <p className="text-xs text-slate-400">无可配置参数。</p>
            ) : (
              <SchemaForm
                schema={schema}
                value={value}
                disabled={disabled}
                onChange={(next) => onOptionsChange(task.id, step.id, next)}
              />
            )}
            {isExtractStep && extraction && (
              <TrackSelector
                taskId={task.id}
                videoPath={videoPath ?? ""}
                selection={selection}
                disabled={disabled}
                onSelectionChange={onSelectionChange}
              />
            )}
          </div>
        );
      })}
    </div>
  );
}

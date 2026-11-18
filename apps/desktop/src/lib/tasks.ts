import type { TaskInputSpec, TaskSpec } from "./models";
import { extensionOf } from "./models";

/** 任务目录排序：先按 order，再按标题（中文按本地化顺序）。 */
export function sortTasks(tasks: TaskSpec[]): TaskSpec[] {
  return [...tasks].sort((left, right) => {
    if (left.order !== right.order) return left.order - right.order;
    return left.title.localeCompare(right.title, "zh-Hans-CN");
  });
}

export function taskInputLabel(input: TaskInputSpec): string {
  return input.label?.trim() || input.name;
}

function normalizeAccept(entry: string): string {
  const value = entry.trim().toLowerCase();
  if (!value) return "";
  return value.startsWith(".") ? value : `.${value}`;
}

/** 根据扩展名判断路径是否匹配某个输入槽的 accept；accept 为空表示全部接受。 */
export function matchesAccept(path: string, accept: string[]): boolean {
  const rules = accept.map(normalizeAccept).filter(Boolean);
  if (rules.length === 0) return true;
  if (rules.includes("*") || rules.includes(".*")) return true;
  return rules.includes(extensionOf(path));
}

/** 双语合并任务：优先按 id / recipe_id，其次按 original 输入识别。 */
export function findBilingualTask(tasks: TaskSpec[]): TaskSpec | null {
  return (
    tasks.find(
      (task) => task.id === "batch_translated_to_bilingual" || task.recipe_id === "batch_translated_to_bilingual",
    ) ??
    tasks.find((task) => task.inputs.some((input) => input.name === "original")) ??
    null
  );
}

/** 从项目产物中选出用于「原版」槽的字幕：优先 .clean.srt，其次最新 .srt。 */
export function pickOriginalSubtitle(paths: string[]): string | null {
  const clean = [...paths].reverse().find((path) => /\.clean\.srt$/i.test(path));
  if (clean) return clean;
  const srt = [...paths].reverse().find((path) => /\.srt$/i.test(path));
  return srt ?? null;
}

/** 批量原版字幕：返回全部 .clean.srt（无则全部 .srt），去重并保持原始顺序。 */
export function pickOriginalSubtitles(paths: string[]): string[] {
  const unique = Array.from(new Set(paths));
  const clean = unique.filter((path) => /\.clean\.srt$/i.test(path));
  if (clean.length > 0) return clean;
  return unique.filter((path) => /\.srt$/i.test(path));
}

import type { TaskInputSpec, TaskSpec } from "./models";
import { extensionOf } from "./models";
import { matchesAccept } from "./tasks";

/**
 * 通用输入分发：把拖入的文件/文件夹按扩展名、槽位语义和文件名线索
 * 自动分配到任务的各个输入槽。纯函数，便于单测。
 */

export type InputRole = "video" | "original" | "translated" | "subtitles" | "any";

export interface RouteAssignment {
  input: string;
  paths: string[];
}

export interface UnassignedPath {
  path: string;
  reason: string;
}

export interface RoutingResult {
  assigned: RouteAssignment[];
  unassigned: UnassignedPath[];
  /** 规则无法完全确定、已按空槽顺序放置的文件。 */
  ambiguous: string[];
}

export interface RouteOptions {
  /** 覆盖已有内容；默认只填空槽。 */
  overwrite?: boolean;
}

const VIDEO_EXTENSIONS = [".mkv", ".mp4", ".mov", ".avi", ".ts"];
const TRANSLATED_FOLDER_RE = /译文|翻译|translat/i;
const LANGUAGE_SUFFIX =
  /[._-](zh(?:[-_](?:cn|tw|hk|sg|hans|hant))?|chi|zho|chs|cht|en(?:[-_](?:us|gb))?|eng|ja|jp|jpn|ko|kor|fr|fra|fre|de|deu|ger|es|spa|ru|rus|pt|por|it|ita|th|tha|vi|vie|id|ind|ms|may|ar|ara|tr|tur|pl|pol|nl|nld|dut|sv|swe|da|dan|fi|fin|no|nor|cs|ces|cze|hu|hun|ro|ron|rum|uk|ukr|el|ell|gre|he|heb|hi|hin|bn|ben|fa|fas|per|ta|tam|te|tel|ml|mal|ur|urd)$/i;
const CLEAN_SUFFIX = /\.(clean|orig)(?:[._-]|$)/i;

export function fileName(path: string): string {
  const parts = path.split(/[\\/]/);
  return parts[parts.length - 1] ?? path;
}

export function folderName(path: string): string {
  const parts = path.split(/[\\/]/).filter(Boolean);
  return parts.length >= 2 ? (parts[parts.length - 2] ?? "") : "";
}

/** 文件夹名（文件取父目录，文件夹取自身）是否包含“译文”等译文提示。 */
export function folderLooksTranslated(path: string): boolean {
  const parts = path.split(/[\\/]/).filter(Boolean);
  return parts.slice(-2).some((part) => TRANSLATED_FOLDER_RE.test(part));
}

/** 文件名是否带语言后缀，例如 EP01.zh-CN.srt。 */
export function hasLanguageSuffix(path: string): boolean {
  const stem = fileName(path).replace(/\.[^.]+$/, "");
  return LANGUAGE_SUFFIX.test(stem);
}

/** 是否是清理后的原版文件，例如 EP01.clean.srt。 */
export function looksCleanOriginal(path: string): boolean {
  return CLEAN_SUFFIX.test(fileName(path)) || /[._-]orig(?:[._-]|$)/i.test(fileName(path));
}

/** 优先用引擎返回的 role；旧数据按输入名/标签推断。 */
export function inferInputRole(input: TaskInputSpec): InputRole {
  const explicit = (input as TaskInputSpec & { role?: string }).role;
  if (
    explicit === "video" ||
    explicit === "original" ||
    explicit === "translated" ||
    explicit === "subtitles" ||
    explicit === "any"
  ) {
    return explicit;
  }
  const key = `${input.name} ${input.label ?? ""}`.toLowerCase();
  if (/video|视频|媒体/.test(key)) return "video";
  if (/original|原版|原文|source/.test(key)) return "original";
  if (/translated|translation|译文|翻译/.test(key)) return "translated";
  if (/subs|subtitle|字幕/.test(key)) return "subtitles";
  return "any";
}

function isSubtitlePath(path: string): boolean {
  return [".srt", ".ass", ".ssa", ".vtt"].includes(extensionOf(path));
}

function isVideoPath(path: string): boolean {
  return VIDEO_EXTENSIONS.includes(extensionOf(path));
}

function acceptsSubtitles(input: TaskInputSpec): boolean {
  if (input.accept.length === 0) return true;
  return input.accept.some((item) => {
    const value = item.trim().toLowerCase();
    const ext = value.startsWith(".") ? value : `.${value}`;
    return [".srt", ".ass", ".ssa", ".vtt", "*", ".*"].includes(ext);
  });
}

function isDirectoryLike(path: string): boolean {
  // 拖拽事件给的是真实路径；没有扩展名且不是已知字幕/视频时按文件夹处理。
  const extension = extensionOf(path);
  return extension === ""
    ? !isVideoPath(path) && !isSubtitlePath(path)
    : false;
}

interface ScoredCandidate {
  input: TaskInputSpec;
  score: number;
}

function scoreCandidate(
  path: string,
  input: TaskInputSpec,
  currentPaths: string[],
): number {
  const role = inferInputRole(input);
  let score = 0;
  const directory = isDirectoryLike(path);
  const translatedHint = folderLooksTranslated(path) || hasLanguageSuffix(path);
  const cleanOriginal = looksCleanOriginal(path);

  if (directory) {
    if (input.kind === "folder") score += 80;
    if (role === "translated" && folderLooksTranslated(path)) score += 70;
    if (role === "subtitles") score += 20;
    return score;
  }

  if (isVideoPath(path)) {
    if (role === "video") score += 100;
    else if (role === "any") score += 10;
    else score -= 50;
  } else if (isSubtitlePath(path)) {
    if (role === "original") score += 20 + (cleanOriginal ? 70 : 0) + (translatedHint ? -35 : 0);
    else if (role === "translated")
      score += 20 + (translatedHint ? 70 : 0) + (cleanOriginal ? -35 : 0);
    else if (role === "subtitles") score += 30;
    else if (role === "any") score += 10;
    else score -= 50;
  } else {
    score += 5;
  }

  // 空槽优先，已有内容的槽默认不参与（覆盖模式在调用方放开）。
  if (currentPaths.length === 0) score += 8;
  return score;
}

export function routePaths(
  task: TaskSpec,
  currentSlots: Record<string, string[]>,
  paths: string[],
  options: RouteOptions = {},
): RoutingResult {
  const overwrite = options.overwrite === true;
  const result: RoutingResult = { assigned: [], unassigned: [], ambiguous: [] };
  const working: Record<string, string[]> = {};
  const slotsOf = (input: TaskInputSpec): string[] =>
    working[input.name] ?? currentSlots[input.name] ?? [];

  const seen = new Set<string>();
  for (const raw of paths) {
    const path = raw.trim();
    if (!path) continue;
    if (seen.has(path)) continue;
    seen.add(path);

    const directory = isDirectoryLike(path);
    const candidates = task.inputs.filter((input) => {
      if (directory) return true;
      return matchesAccept(path, input.accept);
    });

    if (candidates.length === 0) {
      result.unassigned.push({
        path,
        reason: directory ? "文件夹没有匹配的输入槽" : "没有接受该扩展名的输入槽",
      });
      continue;
    }

    // 明确的文件名/目录线索只允许进入对应语义的槽，避免 clean 原版被塞进译文槽。
    let preferred = candidates;
    if (!directory) {
      const originalSlot = candidates.find((input) => inferInputRole(input) === "original");
      const translatedSlot = candidates.find((input) => inferInputRole(input) === "translated");
      if (looksCleanOriginal(path) && originalSlot) {
        preferred = [originalSlot];
      } else if (
        (hasLanguageSuffix(path) || folderLooksTranslated(path)) &&
        translatedSlot
      ) {
        preferred = [translatedSlot];
      }
    }

    const available = preferred.filter((input) => {
      if (overwrite) return true;
      // 可多值槽位：仅当本次投放前为空时整批追加，避免静默覆盖已有内容。
      if (input.multiple === true || input.kind === "files") {
        return (currentSlots[input.name] ?? []).length === 0;
      }
      return slotsOf(input).length === 0;
    });

    if (available.length === 0) {
      result.unassigned.push({
        path,
        reason: "目标槽位已有内容；勾选“覆盖已有”后可替换",
      });
      continue;
    }

    let scored: ScoredCandidate[];
    if (directory) {
      const translatedSlot = available.find((input) => inferInputRole(input) === "translated");
      const folderSlot = available.find((input) => input.kind === "folder");
      const originalSlot = available.find((input) => inferInputRole(input) === "original");
      const subtitleSlot = available.find(
        (input) => inferInputRole(input) === "subtitles" || acceptsSubtitles(input),
      );
      const chosen = folderLooksTranslated(path)
        ? (translatedSlot ?? folderSlot ?? subtitleSlot)
        : (folderSlot ?? originalSlot ?? subtitleSlot ?? (available.length === 1 ? available[0] : undefined));
      if (!chosen) {
        result.unassigned.push({
          path,
          reason: "文件夹无法确定归属，请展开后拖入具体字幕文件",
        });
        continue;
      }
      scored = [{ input: chosen, score: 100 }];
    } else {
      scored = available
        .map((input) => ({
          input,
          score: scoreCandidate(path, input, slotsOf(input)),
        }))
        .sort(
          (left, right) =>
            right.score - left.score || left.input.name.localeCompare(right.input.name),
        );
    }

    const best = scored[0];
    if (!best) continue;
    if (directory) {
      result.ambiguous.push(path);
    } else {
      const tied = scored.filter((item) => item.score === best.score);
      const ambiguousTie =
        tied.length > 1 &&
        tied.some((item) => inferInputRole(item.input) === "original") &&
        tied.some((item) => inferInputRole(item.input) === "translated") &&
        !looksCleanOriginal(path) &&
        !hasLanguageSuffix(path) &&
        !folderLooksTranslated(path);
      if (ambiguousTie) result.ambiguous.push(path);
    }

    const single = best.input.multiple !== true && best.input.kind !== "files";
    const existing = working[best.input.name];
    const base = existing ?? (overwrite ? [] : slotsOf(best.input));
    const next = single
      ? [path]
      : [...base.filter((item) => item !== path), path];
    working[best.input.name] = next;
  }

  for (const input of task.inputs) {
    const values = working[input.name];
    if (values && values.length > 0) {
      result.assigned.push({ input: input.name, paths: values });
    }
  }
  return result;
}

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
const ORIGINAL_FOLDER_RE = /^(clean|extracted)$/i;
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

/** 路径是否位于 clean / extracted 这类原文处理目录中。 */
export function folderLooksOriginal(path: string): boolean {
  const parts = path.split(/[\\/]/).filter(Boolean);
  return parts.slice(-2).some((part) => ORIGINAL_FOLDER_RE.test(part));
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

/** 批量项目名：优先拖入的文件夹名，否则用第一个视频的文件名。 */
export function batchProjectName(paths: string[], directories: string[] = []): string {
  const folder = directories.find((path) => fileName(path).trim().length > 0);
  if (folder) return fileName(folder);
  const first = paths[0] ?? "";
  return fileName(first).replace(/\.[^.]+$/, "") || "未命名项目";
}

/** 只保留确实包含这些文件的文件夹，避免过期的分发记录影响项目命名。 */
export function directoriesForPaths(directories: string[], paths: string[]): string[] {
  const normalize = (path: string) =>
    path.replace(/\\/g, "/").replace(/\/+$/, "").toLowerCase();
  const normalizedPaths = paths.map(normalize);
  return directories.filter((directory) => {
    const base = `${normalize(directory)}/`;
    return normalizedPaths.some((path) => path.startsWith(base));
  });
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

function acceptsMany(input: TaskInputSpec): boolean {
  return input.kind === "files" || input.multiple === true;
}

type PathHint = "original" | "translated" | null;

/** 单个文件的语义线索；无线索时返回 null，由整批 sticky 规则决定槽位。 */
function pathHint(path: string): PathHint {
  if (looksCleanOriginal(path)) return "original";
  if (folderLooksOriginal(path)) return "original";
  if (hasLanguageSuffix(path) || folderLooksTranslated(path)) return "translated";
  return null;
}

interface FileEntry {
  path: string;
  hint: PathHint;
  candidates: TaskInputSpec[];
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
  const written = new Set<string>();

  const slotsOf = (input: TaskInputSpec): string[] =>
    working[input.name] ?? currentSlots[input.name] ?? [];

  const slotAvailable = (input: TaskInputSpec): boolean => {
    if (overwrite) return true;
    // 可多值槽位：仅当本次投放前为空时整批追加，避免静默覆盖已有内容。
    if (acceptsMany(input)) return (currentSlots[input.name] ?? []).length === 0;
    return slotsOf(input).length === 0;
  };

  const assign = (input: TaskInputSpec, path: string): void => {
    const base = written.has(input.name)
      ? (working[input.name] ?? [])
      : overwrite
        ? []
        : slotsOf(input);
    const next = acceptsMany(input) ? [...base, path] : [path];
    working[input.name] = Array.from(new Set(next));
    written.add(input.name);
  };

  const unassigned = (path: string, reason: string): void => {
    result.unassigned.push({ path, reason });
  };

  const seen = new Set<string>();
  const entries: FileEntry[] = [];

  const routeDirectory = (path: string): void => {
    const available = task.inputs.filter(slotAvailable);
    if (available.length === 0) {
      unassigned(path, "目标槽位已有内容；勾选“覆盖已有”后可替换");
      return;
    }
    const translatedSlot = available.find((input) => inferInputRole(input) === "translated");
    const folderSlot = available.find((input) => input.kind === "folder");
    const originalSlot = available.find((input) => inferInputRole(input) === "original");
    const subtitleSlot = available.find(
      (input) => inferInputRole(input) === "subtitles" || acceptsSubtitles(input),
    );
    const chosen = folderLooksTranslated(path)
      ? (translatedSlot ?? folderSlot ?? subtitleSlot)
      : (folderSlot ??
        originalSlot ??
        subtitleSlot ??
        (available.length === 1 ? available[0] : undefined));
    if (!chosen) {
      unassigned(path, "文件夹无法确定归属，请展开后拖入具体字幕文件");
      return;
    }
    assign(chosen, path);
    result.ambiguous.push(path);
  };

  for (const raw of paths) {
    const path = raw.trim();
    if (!path) continue;
    if (seen.has(path)) continue;
    seen.add(path);

    if (isDirectoryLike(path)) {
      routeDirectory(path);
      continue;
    }

    const candidates = task.inputs.filter((input) => matchesAccept(path, input.accept));
    if (candidates.length === 0) {
      unassigned(path, "没有接受该扩展名的输入槽");
      continue;
    }
    entries.push({ path, hint: pathHint(path), candidates });
  }

  // 有明确线索的文件按角色整组进槽，避免同批文件被拆到两个槽位。
  const hinted: Record<"original" | "translated", FileEntry[]> = {
    original: [],
    translated: [],
  };
  const unknownGroups = new Map<string, FileEntry[]>();
  for (const entry of entries) {
    if (entry.hint) {
      hinted[entry.hint].push(entry);
      continue;
    }
    const signature = entry.candidates
      .map((input) => input.name)
      .sort()
      .join("|");
    const group = unknownGroups.get(signature);
    if (group) group.push(entry);
    else unknownGroups.set(signature, [entry]);
  }

  for (const role of ["original", "translated"] as const) {
    const group = hinted[role];
    if (group.length === 0) continue;
    const target = task.inputs.find(
      (input) =>
        inferInputRole(input) === role && group.every((entry) => entry.candidates.includes(input)),
    );
    if (!target) {
      for (const entry of group) unassigned(entry.path, "没有匹配该语义的输入槽");
      continue;
    }
    if (!slotAvailable(target)) {
      for (const entry of group) {
        unassigned(entry.path, "目标槽位已有内容；勾选“覆盖已有”后可替换");
      }
      continue;
    }
    for (const entry of group) assign(target, entry.path);
  }

  const hasOriginalHint = hinted.original.length > 0;
  const hasTranslatedHint = hinted.translated.length > 0;

  for (const group of unknownGroups.values()) {
    const candidates = task.inputs.filter((input) =>
      group.every((entry) => entry.candidates.includes(input)),
    );
    const available = candidates.filter(slotAvailable);
    if (available.length === 0) {
      for (const entry of group) {
        unassigned(entry.path, "目标槽位已有内容；勾选“覆盖已有”后可替换");
      }
      continue;
    }

    // 无线索文件整批只选一次目标槽（sticky），不再逐文件重新打分，
    // 否则空槽加分会让同批字幕在原文/译文之间交替。
    let target: TaskInputSpec | null;
    if (hasTranslatedHint && !hasOriginalHint) {
      target = available.find((input) => inferInputRole(input) === "original") ?? null;
    } else if (hasOriginalHint && !hasTranslatedHint) {
      target = available.find((input) => inferInputRole(input) === "translated") ?? null;
    } else {
      const empty = available.filter((input) => slotsOf(input).length === 0);
      target = empty.length === available.length ? available[0] : (empty[0] ?? available[0]);
    }

    if (!target) {
      for (const entry of group) {
        unassigned(entry.path, "目标槽位已有内容；勾选“覆盖已有”后可替换");
      }
      continue;
    }

    for (const entry of group) assign(target, entry.path);
    if (candidates.length > 1) {
      for (const entry of group) result.ambiguous.push(entry.path);
    }
  }

  for (const input of task.inputs) {
    const values = working[input.name];
    if (values && values.length > 0) {
      result.assigned.push({ input: input.name, paths: values });
    }
  }
  return result;
}

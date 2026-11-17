import { isSubtitlePath, type ProjectSummary } from "./models";

/**
 * 流程 2（译文 → 双语 ASS）的纯逻辑：文件名归一化与项目推荐。
 * 放在这里便于脱离 UI 单测，RunView / HandoffCard 只负责展示。
 */

/** 常见字幕语言后缀（含 LinguaGacha 等工具常用的三位代码）。 */
const LANGUAGE_SUFFIX =
  /[._-](zh(?:[-_](?:cn|tw|hk|sg|hans|hant))?|chi|zho|chs|cht|en(?:[-_](?:us|gb))?|eng|ja|jp|jpn|ko|kor|fr|fra|fre|de|deu|ger|es|spa|ru|rus|pt|por|it|ita|th|tha|vi|vie|id|ind|ms|may|ar|ara|tr|tur|pl|pol|nl|nld|dut|sv|swe|da|dan|fi|fin|no|nor|cs|ces|cze|hu|hun|ro|ron|rum|uk|ukr|el|ell|gre|he|heb|hi|hin|bn|ben|fa|fas|per|ta|tam|te|tel|ml|mal|ur|urd)$/i;

const CLEAN_SUFFIX = /\.(clean|orig)$/i;

function fileName(path: string): string {
  const parts = path.split(/[\\/]/);
  return parts[parts.length - 1] ?? path;
}

/**
 * 从译文字幕路径推断原项目 base 名：
 * 去掉扩展名、末尾的 ``.clean`` / ``.orig`` 以及语言后缀（可叠加）。
 *
 * ``Ep01.zh-CN.clean.srt`` → ``Ep01``
 */
export function subtitleBaseName(path: string): string {
  let base = fileName(path).replace(/\.[^.]+$/, "");
  let previous = "";
  while (base !== previous) {
    previous = base;
    base = base.replace(CLEAN_SUFFIX, "");
    base = base.replace(LANGUAGE_SUFFIX, "");
  }
  return base;
}

/** 只保留字幕文件（拖入目录/混合列表时使用）。 */
export function subtitlePaths(paths: string[]): string[] {
  return paths.filter(isSubtitlePath);
}

/** 拖入内容是否「仅有字幕」：非空且每一项都是 .srt/.ass/.vtt。 */
export function isSubtitleOnly(paths: string[]): boolean {
  return paths.length > 0 && paths.every(isSubtitlePath);
}

function isPrefixMatch(name: string, base: string): boolean {
  return name.startsWith(base) || base.startsWith(name);
}

/** 名称比较时把 ``.`` / ``_`` / ``-`` 与连续空白统一，避免分隔符差异导致漏匹配。 */
function normalizeName(value: string): string {
  return value
    .trim()
    .toLowerCase()
    .replace(/[._-]+/g, " ")
    .replace(/\s+/g, " ")
    .trim();
}

/**
 * 根据译文字幕推荐目标项目。
 *
 * 规则：
 * 1. 项目名与字幕 base 做大小写不敏感的相等/前缀匹配（相等权重更高）；
 * 2. 同等匹配下优先状态为 ``waiting_translation`` 的项目；
 * 3. 没有名称匹配时，退回最近更新的 ``waiting_translation`` 项目；
 * 4. 仍无候选则返回 ``null``，由用户手动选择。
 */
export function pickProjectForSubtitles(
  projects: ProjectSummary[],
  paths: string[],
): ProjectSummary | null {
  if (projects.length === 0) return null;

  const bases = subtitlePaths(paths)
    .map(subtitleBaseName)
    .map(normalizeName)
    .filter(Boolean);
  if (bases.length === 0) return null;

  let best: ProjectSummary | null = null;
  let bestScore = Number.NEGATIVE_INFINITY;

  for (const project of projects) {
    const name = normalizeName(project.name);
    let nameScore = 0;
    for (const base of bases) {
      if (name === base) {
        nameScore = Math.max(nameScore, 3);
      } else if (isPrefixMatch(name, base)) {
        nameScore = Math.max(nameScore, 2);
      }
    }

    const waiting = project.status === "waiting_translation";
    const score = nameScore > 0 ? nameScore * 2 + (waiting ? 1 : 0) : waiting ? 1 : 0;
    if (score === 0) continue;

    if (
      score > bestScore ||
      (score === bestScore &&
        best !== null &&
        Date.parse(project.updated_at) > Date.parse(best.updated_at))
    ) {
      best = project;
      bestScore = score;
    }
  }

  return best;
}

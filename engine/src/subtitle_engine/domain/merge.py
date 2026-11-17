"""双语字幕合并与文件匹配（移植自 ``tools/merge_srt.py``）。

移植原则（TASKBOOK §8 / §19 红线）：

- **重复片段检测算法保持不变**（``find_duplicate_runs`` 的极大匹配 + 贪心选择）。
- 保留精确时间戳匹配与 5 条模糊匹配规则、连通分量合并。
- 去掉文件读写与 ``print``：这里只做纯文本/时间计算，写出由步骤层负责。
- ASS 时间格式与旧实现一致：毫秒**截断**为两位百分秒，而不是四舍五入。
"""

from __future__ import annotations

import os
import re
import unicodedata
from dataclasses import dataclass, field
from datetime import date

from .clean import format_zh_text

_ITALIC_TAG_RE = re.compile(r"</?i>", re.IGNORECASE)

#: 译文与原文连续重复片段的匹配阈值：非数字字符数需超过该值
DUPLICATE_MIN_NON_DIGIT = 5

DEFAULT_L1_STYLE_DEF = (
    "黑体, 60, &H00EEEEEE, &HF0000000, &H00000000, &H32000000, 0, 0, 0, 0, 100, 100, "
    "0, 0, 1, 1.5, 0, 2, 18, 18, 18, 1"
)
DEFAULT_L2_STYLE_DEF = (
    "Arial, 40, &H00EEEEEE, &HF0000000, &H00000000, &H32000000, 0, 0, 0, 0, 100, 100, "
    "0, 0, 1, 1.5, 0, 2, 18, 18, 18, 1"
)

#: 一条待合并字幕：ASS 时间字符串 + 文本
Entry = tuple[str, str, str]

_SRT_TIME_LINE_RE = re.compile(r"(\d+):(\d+):(\d+),(\d+)")


def _strip_ass_markup(text: str) -> tuple[str, list[int]]:
    """去掉 ASS 覆写标签与 ``<i>`` 标记，返回 (清理后文本, 清理后下标 -> 原始下标映射)。"""
    cleaned: list[str] = []
    index_map: list[int] = []
    i = 0
    length = len(text)
    while i < length:
        if text[i] == "{":
            close = text.find("}", i)
            if close != -1:
                i = close + 1
                continue
        match = _ITALIC_TAG_RE.match(text, i)
        if match:
            i = match.end()
            continue
        cleaned.append(text[i])
        index_map.append(i)
        i += 1
    return "".join(cleaned), index_map


def _normalize_for_match(text: str) -> tuple[str, list[int]]:
    """归一化字幕文本用于重复片段检测，返回 (归一化串, 归一化下标 -> 原始下标映射)。

    忽略 ASS 标签、``<i>`` 标记、空白与标点，统一大小写（casefold）并做 NFKC
    规范化，因此对英语之外的泛欧语言（德语 ß、希腊语、西里尔字母等）同样适用。
    """
    cleaned, raw_map = _strip_ass_markup(text)
    chars: list[str] = []
    index_map: list[int] = []
    for cleaned_idx, ch in enumerate(cleaned):
        for normalized in unicodedata.normalize("NFKC", ch):
            for folded in normalized.casefold():
                if not folded.isalnum():
                    continue
                chars.append(folded)
                index_map.append(raw_map[cleaned_idx])
    return "".join(chars), index_map


def _count_non_digit(text: str) -> int:
    return sum(1 for ch in text if not ch.isdigit())


def find_duplicate_runs(
    zh_text: str, eng_text: str, min_non_digit: int = DUPLICATE_MIN_NON_DIGIT
) -> list[tuple[int, int]]:
    """查找译文与原文之间连续重复的片段。

    数字不计入阈值计算，但不会打断片段的连续性。
    返回按译文下标升序排列的 ``(start, end)`` 列表（end 不含）。
    """
    zh_norm, zh_map = _normalize_for_match(zh_text)
    eng_norm, _ = _normalize_for_match(eng_text)
    n, m = len(zh_norm), len(eng_norm)
    if n < min_non_digit or m < min_non_digit:
        return []

    # dp[i][j] = 以 zh_norm[i-1] 与 eng_norm[j-1] 结尾的连续匹配长度
    dp = [[0] * (m + 1) for _ in range(n + 1)]
    candidates: list[tuple[int, int, int]] = []
    for i in range(1, n + 1):
        zh_char = zh_norm[i - 1]
        row = dp[i]
        prev_row = dp[i - 1]
        for j in range(1, m + 1):
            if zh_char != eng_norm[j - 1]:
                continue
            run_len = prev_row[j - 1] + 1
            row[j] = run_len
            # 只收集右侧已无法继续延长的极大匹配片段
            if i < n and j < m and zh_norm[i] == eng_norm[j]:
                continue
            if _count_non_digit(zh_norm[i - run_len : i]) >= min_non_digit:
                candidates.append((i - run_len, i, run_len))

    if not candidates:
        return []

    # 优先保留更长的片段，再按位置排序，最终得到互不重叠的匹配区间
    candidates.sort(key=lambda item: (-item[2], item[0]))
    selected: list[tuple[int, int, int]] = []
    for start, end, _ in candidates:
        if any(start < sel_end and sel_start < end for sel_start, sel_end, _ in selected):
            continue
        selected.append((start, end, end - start))
    selected.sort()

    runs: list[tuple[int, int]] = []
    for start, end, _ in selected:
        zh_start = zh_map[start]
        zh_end = zh_map[end - 1] + 1
        runs.append((zh_start, zh_end))
    return runs


def apply_original_font_to_duplicates(
    zh_text: str,
    eng_text: str,
    base_font: str,
    duplicate_font: str,
    min_non_digit: int = DUPLICATE_MIN_NON_DIGIT,
) -> str:
    """把译文中与原文字符连续重复的片段改用原文字体名渲染。

    只切换 ``\\fn`` 字体名，保留译文样式本身的字号、描边、颜色等属性。
    """
    if not duplicate_font or duplicate_font == base_font:
        return zh_text

    runs = find_duplicate_runs(zh_text, eng_text, min_non_digit=min_non_digit)
    if not runs:
        return zh_text

    for start, end in reversed(runs):
        run_text = zh_text[start:end]
        # 含 ASS 特殊字符的片段不做包装，避免破坏标签语法
        if any(ch in run_text for ch in "\\{}"):
            continue
        replacement = f"{{\\fn{duplicate_font}}}{run_text}"
        if end < len(zh_text):
            replacement += f"{{\\fn{base_font}}}"
        zh_text = zh_text[:start] + replacement + zh_text[end:]
    return zh_text


def _style_font_name(style_def: str) -> str:
    """从 ASS 样式定义中取字体名（第一项）。"""
    if not style_def:
        return ""
    return style_def.split(",", 1)[0].strip()


def convert_time(srt_timestamp: str) -> str:
    """SRT 时间 ``00:00:02,326`` → ASS 时间 ``0:00:02.32``（毫秒截断）。"""
    match = _SRT_TIME_LINE_RE.match(srt_timestamp)
    if not match:
        raise ValueError(f"时间格式不正确: {srt_timestamp}")
    hour, minute, second, ms = match.groups()
    hour = str(int(hour))
    minute = minute.zfill(2)
    second = second.zfill(2)
    # 毫秒转换为两位，直接取前两位（相当于截断，不是四舍五入）
    ms = ms[:2]
    return f"{hour}:{minute}:{second}.{ms}"


def parse_srt_entries(content: str) -> list[Entry]:
    """解析 SRT 文本为 ``(start_ass, end_ass, text)`` 列表。

    与旧实现保持一致：多行字幕用空格合并，缺少时间轴的块跳过。
    """
    text = content.lstrip("\ufeff")
    blocks = re.split(r"\n\s*\n", text.strip())
    entries: list[Entry] = []
    for block in blocks:
        lines = block.splitlines()
        if len(lines) >= 3:
            time_line = lines[1]
            if "-->" not in time_line:
                continue
            start_str, end_str = (part.strip() for part in time_line.split("-->"))
            start_ass = convert_time(start_str)
            end_ass = convert_time(end_str)
            merged_text = " ".join(lines[2:]).strip()
            entries.append((start_ass, end_ass, merged_text))
    return entries


def _get_ms(time_str: str) -> int:
    h, m, s_ms = time_str.split(":")
    s, ms = s_ms.split(".")
    return int(h) * 3600000 + int(m) * 60000 + int(s) * 1000 + int(ms) * 10


@dataclass
class MergeResult:
    """合并结果：ASS 事件列表 + 未匹配原文等警告。"""

    entries: list[Entry] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


def merge_entries(
    eng_entries: list[Entry],
    zh_entries: list[Entry],
    *,
    lang2_style_name: str = "Original",
    lang1_style_def: str = DEFAULT_L1_STYLE_DEF,
    lang2_style_def: str = DEFAULT_L2_STYLE_DEF,
) -> MergeResult:
    """合并原文（英）与译文（中）条目，返回 ASS 事件与警告。

    首先尝试精确时间戳匹配；只要有一个原文时间戳在译文中缺失，就降级为
    模糊匹配（起止 ±500ms、互相包含、重叠 > 50%、孤立节点按最大重叠打捞）。
    """
    l2_font = _style_font_name(lang2_style_def)
    l1_font = _style_font_name(lang1_style_def)
    warnings: list[str] = []

    # 1. 检查是否可以精确匹配（所有英文时间戳在中文里都能找到）
    eng_map = {(start, end): text for start, end, text in eng_entries}
    zh_map = {(start, end): text for start, end, text in zh_entries}

    exact_match_success = True
    for eng_start, eng_end, _ in eng_entries:
        if (eng_start, eng_end) not in zh_map:
            exact_match_success = False
            break

    merged_entries: list[Entry] = []

    if exact_match_success:
        for zh_start, zh_end, zh_text in zh_entries:
            zh_text = format_zh_text(zh_text)
            if (zh_start, zh_end) in eng_map:
                eng_text = eng_map[(zh_start, zh_end)]
                eng_text = eng_text.replace("<i>", "").replace("</i>", "")
                zh_text = apply_original_font_to_duplicates(zh_text, eng_text, l1_font, l2_font)
                merged_text = f"{zh_text}\\N{{\\r{lang2_style_name}}}{eng_text}"
                merged_entries.append((zh_start, zh_end, merged_text))
            else:
                # 中文多出的字幕
                merged_entries.append((zh_start, zh_end, f"{{\\an8}}{zh_text}"))

        merged_entries.sort(key=lambda x: _get_ms(x[0]))
        return MergeResult(entries=merged_entries, warnings=warnings)

    # 2. 精确匹配失败，启用模糊匹配规则
    eng_nodes = [
        {
            "idx": i,
            "start_ms": _get_ms(start),
            "end_ms": _get_ms(end),
            "start_str": start,
            "end_str": end,
            "text": text,
        }
        for i, (start, end, text) in enumerate(eng_entries)
    ]
    zh_nodes = [
        {
            "idx": j,
            "start_ms": _get_ms(start),
            "end_ms": _get_ms(end),
            "start_str": start,
            "end_str": end,
            "text": text,
        }
        for j, (start, end, text) in enumerate(zh_entries)
    ]

    # 构建匹配关系（二分图）
    eng_adj: dict[int, list[int]] = {i: [] for i in range(len(eng_nodes))}
    zh_adj: dict[int, list[int]] = {j: [] for j in range(len(zh_nodes))}

    for i, e in enumerate(eng_nodes):
        for j, z in enumerate(zh_nodes):
            # 规则1：起止时间戳在前后 0.5s 内
            c1 = (
                abs(e["start_ms"] - z["start_ms"]) <= 500
                and abs(e["end_ms"] - z["end_ms"]) <= 500
            )
            # 规则2：翻译完全包含在原始时间戳内
            c2 = z["start_ms"] >= e["start_ms"] and z["end_ms"] <= e["end_ms"]
            # 规则3：一条翻译时间戳包含多个原始（原始被包含在翻译中）
            c3 = e["start_ms"] >= z["start_ms"] and e["end_ms"] <= z["end_ms"]
            # 规则4：某条字幕与另一边的某条字幕时间重叠大于 50%
            overlap_start = max(e["start_ms"], z["start_ms"])
            overlap_end = min(e["end_ms"], z["end_ms"])
            overlap_dur = max(0, overlap_end - overlap_start)
            e_dur = e["end_ms"] - e["start_ms"]
            z_dur = z["end_ms"] - z["start_ms"]
            c4 = (e_dur > 0 and overlap_dur / e_dur > 0.5) or (
                z_dur > 0 and overlap_dur / z_dur > 0.5
            )

            if c1 or c2 or c3 or c4:
                eng_adj[i].append(j)
                zh_adj[j].append(i)

    # 规则5：孤立节点打捞（处理跨界字幕），只连接重叠最多的一条。
    for i in range(len(eng_nodes)):
        if not eng_adj[i]:
            e = eng_nodes[i]
            best_j = -1
            max_overlap = 0
            for j in range(len(zh_nodes)):
                z = zh_nodes[j]
                overlap_start = max(e["start_ms"], z["start_ms"])
                overlap_end = min(e["end_ms"], z["end_ms"])
                overlap_dur = max(0, overlap_end - overlap_start)
                if overlap_dur > max_overlap:
                    max_overlap = overlap_dur
                    best_j = j

            e_dur = e["end_ms"] - e["start_ms"]
            if best_j != -1 and (max_overlap > 0.3 * e_dur or max_overlap > 500):
                eng_adj[i].append(best_j)
                zh_adj[best_j].append(i)

    for j in range(len(zh_nodes)):
        if not zh_adj[j]:
            z = zh_nodes[j]
            best_i = -1
            max_overlap = 0
            for i in range(len(eng_nodes)):
                e = eng_nodes[i]
                overlap_start = max(e["start_ms"], z["start_ms"])
                overlap_end = min(e["end_ms"], z["end_ms"])
                overlap_dur = max(0, overlap_end - overlap_start)
                if overlap_dur > max_overlap:
                    max_overlap = overlap_dur
                    best_i = i

            z_dur = z["end_ms"] - z["start_ms"]
            if best_i != -1 and (max_overlap > 0.3 * z_dur or max_overlap > 500):
                eng_adj[best_i].append(j)
                zh_adj[j].append(best_i)

    # 寻找连通分量，合并匹配项
    visited_eng: set[int] = set()
    visited_zh: set[int] = set()
    components: list[tuple[set[int], set[int]]] = []

    for i in range(len(eng_nodes)):
        if i in visited_eng:
            continue

        comp_eng: set[int] = set()
        comp_zh: set[int] = set()
        q_eng = [i]
        q_zh: list[int] = []

        while q_eng or q_zh:
            while q_eng:
                e_idx = q_eng.pop(0)
                if e_idx in comp_eng:
                    continue
                comp_eng.add(e_idx)
                visited_eng.add(e_idx)
                for z_idx in eng_adj[e_idx]:
                    if z_idx not in comp_zh:
                        q_zh.append(z_idx)
            while q_zh:
                z_idx = q_zh.pop(0)
                if z_idx in comp_zh:
                    continue
                comp_zh.add(z_idx)
                visited_zh.add(z_idx)
                for e_idx in zh_adj[z_idx]:
                    if e_idx not in comp_eng:
                        q_eng.append(e_idx)

        components.append((comp_eng, comp_zh))

    # 找出孤立的中文字幕
    for j in range(len(zh_nodes)):
        if j not in visited_zh:
            components.append((set(), {j}))

    # 生成最终合并结果
    for comp_eng, comp_zh in components:
        e_list = sorted(comp_eng)
        z_list = sorted(comp_zh)

        if len(e_list) == 0 and len(z_list) > 0:
            # 孤立无法匹配的中文行 -> 输出到屏幕顶部
            for z_idx in z_list:
                z = zh_nodes[z_idx]
                zh_text = format_zh_text(z["text"])
                merged_entries.append((z["start_str"], z["end_str"], f"{{\\an8}}{zh_text}"))

        elif len(z_list) == 0 and len(e_list) > 0:
            # 未匹配的原始语言 -> 正常输出并警告
            for e_idx in e_list:
                e = eng_nodes[e_idx]
                warn_msg = (
                    f"警告：未找到匹配的翻译字幕！原始字幕"
                    f"({e['start_str']} --> {e['end_str']})"
                )
                warnings.append(warn_msg)
                eng_clean = e["text"].replace("<i>", "").replace("</i>", "")
                merged_entries.append(
                    (e["start_str"], e["end_str"], f"{{\\r{lang2_style_name}}}{eng_clean}")
                )

        else:
            # 成功匹配的组（可能是 1 对 1、1 对多、多对 1），时间戳取原文首尾
            start_str = eng_nodes[e_list[0]]["start_str"]
            end_str = eng_nodes[e_list[-1]]["end_str"]

            zh_texts = [format_zh_text(zh_nodes[z_idx]["text"]) for z_idx in z_list]
            zh_merged = " ".join(zh_texts)

            eng_texts = [
                eng_nodes[e_idx]["text"].replace("<i>", "").replace("</i>", "")
                for e_idx in e_list
            ]
            eng_merged = " ".join(eng_texts)

            zh_merged = apply_original_font_to_duplicates(
                zh_merged, eng_merged, l1_font, l2_font
            )

            merged_text = f"{zh_merged}\\N{{\\r{lang2_style_name}}}{eng_merged}"
            merged_entries.append((start_str, end_str, merged_text))

    merged_entries.sort(key=lambda x: _get_ms(x[0]))
    return MergeResult(entries=merged_entries, warnings=warnings)


def render_ass(
    merged_entries: list[Entry],
    filename: str,
    *,
    author: str = "lns103",
    comment: str | None = None,
    playresx: int = 1920,
    playresy: int = 1080,
    lang1_style_name: str = "Chinese",
    lang1_style_def: str = DEFAULT_L1_STYLE_DEF,
    lang2_style_name: str = "Original",
    lang2_style_def: str = DEFAULT_L2_STYLE_DEF,
) -> str:
    """把合并结果渲染为完整 ASS 文本（LF，末尾保留一个换行）。"""
    if comment is None:
        comment = f"{date.today().isoformat()} made by my SRT merge script"

    header = (
        "[Script Info]\n"
        f"Title: {filename}\n"
        f"Author: {author}\n"
        f"Comment: {comment}\n"
        "ScriptType: v4.00+\n"
        f"PlayResX: {playresx}\n"
        f"PlayResY: {playresy}\n"
        "Timer: 100.0000\n"
        "WrapStyle: 0\n"
        "YCbCr Matrix: TV.709\n"
        "ScaledBorderAndShadow: yes\n\n"
        "[V4+ Styles]\n"
        "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, "
        "BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, "
        "BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding\n"
        f"Style: {lang1_style_name}, {lang1_style_def}\n"
        f"Style: {lang2_style_name}, {lang2_style_def}\n\n"
        "[Events]\n"
        "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text\n"
    )
    lines = [header]
    for start, end, text in merged_entries:
        lines.append(f"Dialogue: 0,{start},{end},{lang1_style_name},,0,0,0,,{text}\n")
    return "".join(lines)


def parse_patterns(pattern: str | list[str] | None) -> list[str]:
    """解析语言后缀模式，允许用逗号/分号/空格/竖线分隔。"""
    if not pattern:
        return ["zh"]
    if isinstance(pattern, list):
        return [part.strip().lower() for part in pattern if part.strip()]
    raw_parts = re.split(r"[,;\s|]+", str(pattern).strip().lower())
    patterns = [part for part in raw_parts if part]
    return patterns if patterns else ["zh"]


def clean_translated_name(filename: str, patterns: str | list[str] | None = "zh") -> str:
    """去掉译文字幕名里的语言后缀，用于与原文 stem 匹配。"""
    name = os.path.splitext(os.path.basename(filename))[0].lower()
    for pattern in parse_patterns(patterns):
        match = re.search(rf"[._-]{re.escape(pattern)}(?:[-_][a-zA-Z0-9]+)?$", name)
        if match:
            return name[: match.start()]
        if name == pattern:
            return ""
    return name


def classify_and_match_files(
    file_paths: list[str], pattern: str | list[str] = "zh"
) -> tuple[list[dict[str, str]], list[dict[str, str]], list[dict[str, str]]]:
    """按文件名/目录特征配对原文与译文（移植旧 ``classify_and_match_files``）。

    返回 ``(matched_pairs, unmatched_original, unmatched_translated)``。
    """
    patterns = parse_patterns(pattern)

    translated_files: list[str] = []
    original_files: list[str] = []

    # 1. 分类文件
    for path in file_paths:
        if not path.lower().endswith(".srt"):
            continue
        path = os.path.abspath(path)
        filename = os.path.basename(path).lower()

        name_we, _ext = os.path.splitext(filename)
        is_translated = False
        for p in patterns:
            if re.search(rf"(?:[._-]|^){re.escape(p)}(?:[-_][a-zA-Z0-9]+)?$", name_we):
                is_translated = True
                break

        if not is_translated:
            parent_dir = os.path.basename(os.path.dirname(path)).lower()
            for p in patterns:
                if re.search(rf"(?<![a-zA-Z]){re.escape(p)}(?![a-zA-Z])", parent_dir):
                    is_translated = True
                    break

        if is_translated:
            translated_files.append(path)
        else:
            original_files.append(path)

    # 2. 干净的匹配名
    def get_clean_name(filepath: str, is_trans: bool) -> str:
        filename = os.path.basename(filepath)
        name, _ext = os.path.splitext(filename)
        name = name.lower()
        if not is_trans:
            return name
        for p in patterns:
            match = re.search(rf"[._-]{re.escape(p)}(?:[-_][a-zA-Z0-9]+)?$", name)
            if match:
                return name[: match.start()]
            if name == p:
                return ""
        return name

    orig_by_name: dict[str, list[str]] = {}
    for orig in original_files:
        orig_by_name.setdefault(get_clean_name(orig, is_trans=False), []).append(orig)

    trans_by_name: dict[str, list[str]] = {}
    for trans in translated_files:
        trans_by_name.setdefault(get_clean_name(trans, is_trans=True), []).append(trans)

    matched_pairs: list[dict[str, str]] = []
    unmatched_original: list[dict[str, str]] = []
    unmatched_translated: list[dict[str, str]] = []

    def get_clean_dir(filepath: str) -> str:
        dir_path = os.path.dirname(os.path.abspath(filepath))
        norm = dir_path.replace("\\", "/").lower()
        parts = norm.split("/")
        if parts:
            last_part = parts[-1]
            for p in patterns:
                if re.search(rf"(?<![a-zA-Z]){re.escape(p)}(?![a-zA-Z])", last_part):
                    parts = parts[:-1]
                    break
        skip_folders = {
            "en",
            "eng",
            "english",
            "original",
            "orig",
            "org",
            "source",
            "src",
            "en-us",
            "en-gb",
            "us",
            "uk",
        }
        cleaned_parts = [part for part in parts if part not in skip_folders]
        return "/".join(cleaned_parts)

    all_clean_names = set(orig_by_name) | set(trans_by_name)

    for cname in all_clean_names:
        origs = orig_by_name.get(cname, [])
        trans = trans_by_name.get(cname, [])

        if not origs:
            for t in trans:
                unmatched_translated.append({"path": t, "reason": "no_match"})
            continue
        if not trans:
            for o in origs:
                unmatched_original.append({"path": o, "reason": "no_match"})
            continue

        orig_by_dir: dict[str, list[str]] = {}
        for o in origs:
            orig_by_dir.setdefault(get_clean_dir(o), []).append(o)

        trans_by_dir: dict[str, list[str]] = {}
        for t in trans:
            trans_by_dir.setdefault(get_clean_dir(t), []).append(t)

        remaining_origs = list(origs)
        remaining_trans = list(trans)
        all_dirs = set(orig_by_dir) | set(trans_by_dir)

        local_conflict_origs: set[str] = set()
        local_conflict_trans: set[str] = set()

        for directory in all_dirs:
            o_list = orig_by_dir.get(directory, [])
            t_list = trans_by_dir.get(directory, [])
            if len(o_list) == 1 and len(t_list) == 1:
                o_file = o_list[0]
                t_file = t_list[0]
                matched_pairs.append({"original": o_file, "translated": t_file})
                remaining_origs.remove(o_file)
                remaining_trans.remove(t_file)
            else:
                if len(o_list) > 1:
                    local_conflict_origs.update(o_list)
                if len(t_list) > 1:
                    local_conflict_trans.update(t_list)

        # 全局模糊匹配：仅当两侧各剩一个且都不是本地冲突项
        if len(remaining_origs) == 1 and len(remaining_trans) == 1:
            o_file = remaining_origs[0]
            t_file = remaining_trans[0]
            if o_file not in local_conflict_origs and t_file not in local_conflict_trans:
                matched_pairs.append({"original": o_file, "translated": t_file})
                remaining_origs.remove(o_file)
                remaining_trans.remove(t_file)

        for o in remaining_origs:
            reason = (
                "multiple_matches"
                if len(trans) > 1 or o in local_conflict_origs
                else "no_match"
            )
            unmatched_original.append({"path": o, "reason": reason})
        for t in remaining_trans:
            reason = (
                "multiple_matches"
                if len(origs) > 1 or t in local_conflict_trans
                else "no_match"
            )
            unmatched_translated.append({"path": t, "reason": reason})

    matched_pairs.sort(key=lambda x: x["original"].lower())
    unmatched_original.sort(key=lambda x: x["path"].lower())
    unmatched_translated.sort(key=lambda x: x["path"].lower())

    return matched_pairs, unmatched_original, unmatched_translated


__all__ = [
    "DEFAULT_L1_STYLE_DEF",
    "DEFAULT_L2_STYLE_DEF",
    "DUPLICATE_MIN_NON_DIGIT",
    "Entry",
    "MergeResult",
    "apply_original_font_to_duplicates",
    "classify_and_match_files",
    "clean_translated_name",
    "convert_time",
    "find_duplicate_runs",
    "merge_entries",
    "parse_patterns",
    "parse_srt_entries",
    "render_ass",
]

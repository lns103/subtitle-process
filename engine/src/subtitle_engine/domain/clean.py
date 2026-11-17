"""SRT 清理与合并（移植自 ``tools/srt_process.py`` + ``tools/chs_srt_format.py``）。

保持逐字节一致的默认行为，供 golden test 与旧实现对比。所有开关都显式
传入，禁止依赖全局状态；统计信息通过返回值上报，不打印。
"""

from __future__ import annotations

import re
from dataclasses import dataclass

MAX_SUBTITLE_LENGTH = 95  # 合并短句后的最大字符数（与旧实现一致）
IDENTICAL_MERGE_GAP = 1.0  # 相同字幕行合并的最大间隔（秒）

_SPEAKER_PATTERN = re.compile(
    r"(^(\s*-\s*)?|\s+-\s+)"
    r"(?:"
    r"\[[^\]\r\n]{1,40}\]"
    r"|\([^)\r\n]{1,40}\)"
    r"|(?=.*[A-Z])[A-Z0-9\s#\.\-_&'/,\+\u00A0]{1,30}"
    r"|(?!\d+$)[^\s:：]{1,30}"
    r")"
    r"\s*[:：](?!\d|//)\s*"
)

_TS_PATTERN = re.compile(r"(\d{2}):(\d{2}):(\d{2}),(\d{3})")
_UPPERCASE_PUNCT = re.compile(r"[.,\/#!$%\^&\*;:{}=\-_`~()?\"']")


@dataclass
class CleanStats:
    brackets: int = 0
    person_hints: int = 0
    tags: int = 0
    merged: int = 0
    uppercase: int = 0
    identical: int = 0

    def to_dict(self) -> dict[str, int]:
        return {
            "brackets": self.brackets,
            "person_hints": self.person_hints,
            "tags": self.tags,
            "merged": self.merged,
            "uppercase": self.uppercase,
            "identical": self.identical,
        }

    def describe(self) -> str:
        labels = (
            ("brackets", "括号"),
            ("person_hints", "人物"),
            ("tags", "标签"),
            ("merged", "合并"),
            ("identical", "相同行合并"),
            ("uppercase", "大写行"),
        )
        parts = [
            f"{label}-{getattr(self, key)}" for key, label in labels if getattr(self, key) > 0
        ]
        return "、".join(parts)


def _parse_timestamp(timestamp: str) -> float | None:
    match = _TS_PATTERN.search(timestamp)
    if not match:
        return None
    return (
        int(match.group(1)) * 3600
        + int(match.group(2)) * 60
        + int(match.group(3))
        + int(match.group(4)) / 1000
    )


def merge_identical_subtitles(
    blocks: list[tuple[str, str]], max_gap: float = IDENTICAL_MERGE_GAP
) -> tuple[list[tuple[str, str]], int]:
    """合并文本完全相同且间隔不超过 ``max_gap`` 的相邻字幕块。"""
    if not blocks:
        return [], 0

    merged_blocks: list[tuple[str, str]] = []
    merge_count = 0
    current_timestamp, current_text = blocks[0]

    for next_timestamp, next_text in blocks[1:]:
        current_end_time = _parse_timestamp(current_timestamp.split(" --> ")[-1])
        next_start_time = _parse_timestamp(next_timestamp.split(" --> ")[0])

        if (
            current_text.strip() == next_text.strip()
            and current_end_time is not None
            and next_start_time is not None
            and (next_start_time - current_end_time) <= max_gap
        ):
            current_parts = current_timestamp.split()
            next_parts = next_timestamp.split()
            if len(current_parts) >= 3 and len(next_parts) >= 3:
                current_timestamp = f"{current_parts[0]} --> {next_parts[2]}"
            merge_count += 1
        else:
            merged_blocks.append((current_timestamp, current_text))
            current_timestamp, current_text = next_timestamp, next_text

    merged_blocks.append((current_timestamp, current_text))
    return merged_blocks, merge_count


def merge_subtitles(
    blocks: list[tuple[str, str]],
) -> tuple[list[tuple[str, str]], int]:
    """合并被硬断行的短字幕块。"""
    if not blocks:
        return [], 0

    merged_blocks: list[tuple[str, str]] = []
    merge_count = 0
    current_timestamp, current_text = blocks[0]

    for next_timestamp, next_text in blocks[1:]:
        current_text_stripped = current_text.rstrip()
        next_text_stripped = next_text.lstrip()

        if current_text_stripped.endswith("-"):
            current_text_stripped = current_text_stripped[:-1].rstrip()

        proposed_merged_text = current_text_stripped + " " + next_text_stripped

        current_match = _TS_PATTERN.search(current_timestamp.split(" --> ")[1])
        next_match = _TS_PATTERN.search(next_timestamp.split(" --> ")[0])
        if current_match is None or next_match is None:
            merged_blocks.append((current_timestamp, current_text))
            current_timestamp, current_text = next_timestamp, next_text
            continue

        current_end_time = (
            int(current_match.group(1)) * 3600
            + int(current_match.group(2)) * 60
            + int(current_match.group(3))
            + int(current_match.group(4)) / 1000
        )
        next_start_time = (
            int(next_match.group(1)) * 3600
            + int(next_match.group(2)) * 60
            + int(next_match.group(3))
            + int(next_match.group(4)) / 1000
        )

        if (
            current_text
            and (current_text.rstrip()[-1] not in ".!?" or current_text.rstrip().endswith("-"))
            and re.match(r"[a-z0-9]", next_text_stripped)
            and len(proposed_merged_text) < MAX_SUBTITLE_LENGTH
            and (next_start_time - current_end_time) <= 0.6
        ):
            current_text = proposed_merged_text
            current_parts = current_timestamp.split()
            next_parts = next_timestamp.split()
            if len(current_parts) >= 3 and len(next_parts) >= 3:
                current_timestamp = f"{current_parts[0]} --> {next_parts[2]}"
            merge_count += 1
        else:
            merged_blocks.append((current_timestamp, current_text))
            current_timestamp, current_text = next_timestamp, next_text

    merged_blocks.append((current_timestamp, current_text))
    return merged_blocks, merge_count


def _clean_person_in_lines(lines: list[str], stats: CleanStats) -> list[str]:
    result: list[str] = []
    for line in lines:
        stripped = line.strip()
        if not stripped:
            continue
        new_line, count = _SPEAKER_PATTERN.subn(r"\1", stripped)
        if count > 0:
            stats.person_hints += count
            result.append(new_line)
        else:
            result.append(stripped)
    return result


def clean_srt_text(
    content: str,
    *,
    merge_short: bool = True,
    clean_uppercase: bool = False,
    clean_person: bool = True,
    merge_identical: bool = False,
    strip_html: bool = True,
) -> tuple[str, CleanStats]:
    """清理 SRT 内容，返回 ``(清理后的文本, 统计)``。

    默认参数与旧实现 ``process_subtitles_content`` 的默认行为一致。
    """
    blocks = re.split(r"\n\s*\n", content.strip())
    processed_blocks: list[tuple[str, str]] = []
    stats = CleanStats()

    for block in blocks:
        lines = block.splitlines()

        if len(lines) > 0 and "-->" in lines[0]:
            timestamp_line = lines[0]
            text_lines = lines[1:]
        else:
            if len(lines) < 3:
                continue
            timestamp_line = lines[1]
            text_lines = lines[2:]

        if clean_uppercase:
            new_text_lines = []
            for line in text_lines:
                text_without_tags = re.sub(r"\{[^{}]*\}", "", line)
                text_without_tags = re.sub(r"<[^>]*>", "", text_without_tags).strip()
                if text_without_tags.isupper() and not _UPPERCASE_PUNCT.search(
                    text_without_tags
                ):
                    stats.uppercase += 1
                    processed_line = line.replace(text_without_tags, "", 1)
                else:
                    processed_line = line
                new_text_lines.append(processed_line)
            text_lines = new_text_lines

        if clean_person:
            text = "\n".join(_clean_person_in_lines(text_lines, stats))
        else:
            text = "\n".join(text_lines)

        if strip_html:
            text, n1 = re.subn(r"\(.*?\)", "", text, flags=re.DOTALL)
            text, n2 = re.subn(r"\[.*?\]", "", text, flags=re.DOTALL)
            stats.brackets += n1 + n2

        if text.strip() in ("-", "\u2013"):
            continue

        if clean_person:
            cleaned_lines = _clean_person_in_lines(text.split("\n"), stats)
            text = " ".join(cleaned_lines)
        else:
            text = text.replace("\n", " ")

        if text.count("- ") == 1 and text.startswith("- "):
            text = text.replace("- ", "", 1)

        if strip_html:
            text, n1 = re.subn(r"<b>|</b>", "", text)
            text, n2 = re.subn(r"<i>|</i>", "", text)
            text, n3 = re.subn(r"\{\\an2\}", "", text)
            stats.tags += n1 + n2 + n3

        text = re.sub(r"\s+", " ", text).strip()

        final_stripped = re.sub(r"\{[^{}]*\}", "", text)
        final_stripped = re.sub(r"<[^>]*>", "", final_stripped).strip()
        if not final_stripped:
            continue

        if text:
            processed_blocks.append((timestamp_line, text))

    if merge_short:
        merged_blocks, merged_count = merge_subtitles(processed_blocks)
        stats.merged = merged_count
    else:
        merged_blocks = processed_blocks

    if merge_identical:
        merged_blocks, identical_count = merge_identical_subtitles(merged_blocks)
        stats.identical = identical_count

    output_lines: list[str] = []
    for number, (timestamp, text) in enumerate(merged_blocks, start=1):
        output_lines.append(str(number))
        output_lines.append(timestamp)
        output_lines.append(text)
        output_lines.append("")

    return "\n".join(output_lines).strip(), stats


def format_zh_text(zh_text: str) -> str:
    """中文字幕标点规范化（移植自 ``chs_srt_format.format_zh_text``）。"""
    zh_text = zh_text.replace("，", " ")
    zh_text = zh_text.replace("。", " ")
    zh_text = zh_text.replace("！", "! ")
    zh_text = zh_text.replace("？", "? ")
    zh_text = zh_text.replace("、", " ")
    zh_text = zh_text.replace("；", "; ")
    zh_text = zh_text.replace("：", ": ")
    zh_text = zh_text.replace("（", "(")
    zh_text = zh_text.replace("）", ")")
    zh_text = zh_text.replace("【", "[")
    zh_text = zh_text.replace("】", "]")
    zh_text = zh_text.replace("“", '"')
    zh_text = zh_text.replace("”", '"')
    zh_text = zh_text.replace("‘", "'")
    zh_text = zh_text.replace("’", "'")
    zh_text = zh_text.replace("——", " ")
    zh_text = zh_text.replace("「", '"')
    zh_text = zh_text.replace("」", '"')
    zh_text = zh_text.replace("- ", "-")
    zh_text = zh_text.replace("  ", " ")

    zh_text = re.sub(r"\s+\"", '"', zh_text)
    zh_text = re.sub(r"\s+'", "'", zh_text)
    zh_text = re.sub(r"\s+」", "」", zh_text)
    zh_text = re.sub(r"\s+》", "》", zh_text)
    zh_text = re.sub(r"\s+”", "”", zh_text)
    return zh_text.strip()


def format_zh_srt_text(content: str) -> str:
    """逐行处理 SRT：序号/时间轴原样保留，其余行做中文标点格式化。"""
    formatted_lines: list[str] = []
    for line in content.splitlines(keepends=True):
        stripped = line.strip()
        if re.match(r"^\d+$", stripped) or re.match(r"^\d{2}:\d{2}:\d{2},\d{3}", stripped):
            formatted_lines.append(line)
        else:
            formatted_lines.append(format_zh_text(line) + "\n")
    return "".join(formatted_lines)


__all__ = [
    "CleanStats",
    "clean_srt_text",
    "format_zh_srt_text",
    "format_zh_text",
    "merge_identical_subtitles",
    "merge_subtitles",
]

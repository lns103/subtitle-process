"""M2 Golden Test：领域算法与旧实现逐字节一致。

旧实现冻结在 ``engine/tests/legacy_reference/``（v1 工具箱存档分支
``archive/legacy-toolbox``），作为迁移期间唯一对比基准。这里直接导入旧函数，
避免复制一份“预期输出”导致测试与实现一起漂移。
"""

from __future__ import annotations

from pathlib import Path

import pytest
from legacy_reference import chs_srt_format, srt_process

from subtitle_engine.domain.clean import clean_srt_text, format_zh_srt_text  # noqa: E402

CASES = {
    "tags_brackets_person": """1
00:00:01,000 --> 00:00:03,000
[BEN]: (laughs) Hello <b>there</b>

2
00:00:03,100 --> 00:00:05,000
<i>Second</i> line
""",
    "merge_short": """1
00:00:01,000 --> 00:00:02,000
I think this

2
00:00:02,300 --> 00:00:04,000
sentence is split
""",
    "merge_identical": """1
00:00:01,000 --> 00:00:02,000
Same line

2
00:00:02,500 --> 00:00:04,000
Same line

3
00:00:05,000 --> 00:00:06,000
Other
""",
    "uppercase_and_speaker": """1
00:00:01,000 --> 00:00:02,000
WARNING SIGNAL

2
00:00:02,100 --> 00:00:03,000
MAN (on TV): Run!
""",
    "empty_after_cleanup": """1
00:00:01,000 --> 00:00:02,000
(music)

2
00:00:02,100 --> 00:00:03,000
Real text
""",
    "chinese_punctuation": """1
00:00:01,000 --> 00:00:02,000
你好，世界。

2
00:00:02,100 --> 00:00:03,000
「测试」 文本！
""",
}


@pytest.mark.parametrize("name", sorted(CASES))
def test_clean_srt_text_matches_legacy(name: str) -> None:
    content = CASES[name]
    expected, expected_stats = srt_process.process_subtitles_content(content)
    actual, actual_stats = clean_srt_text(content)
    assert actual == expected
    assert actual_stats.to_dict() == expected_stats


@pytest.mark.parametrize("name", sorted(CASES))
def test_clean_srt_text_switches_match_legacy(name: str) -> None:
    content = CASES[name]
    expected, expected_stats = srt_process.process_subtitles_content(
        content,
        skip_merge=True,
        clean_uppercase=True,
        clean_person=False,
        merge_identical=True,
    )
    actual, actual_stats = clean_srt_text(
        content,
        merge_short=False,
        clean_uppercase=True,
        clean_person=False,
        merge_identical=True,
    )
    assert actual == expected
    assert actual_stats.to_dict() == expected_stats


@pytest.mark.parametrize("name", sorted(CASES))
def test_zh_punctuation_matches_legacy(name: str, tmp_path: Path) -> None:
    content = CASES[name]
    source = tmp_path / "input.srt"
    target = tmp_path / "output.srt"
    source.write_text(content, encoding="utf-8")
    chs_srt_format.process_srt(str(source), str(target))

    expected = target.read_text(encoding="utf-8")
    assert format_zh_srt_text(content) == expected

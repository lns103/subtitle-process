"""M7 合并步骤：``sub.match_project`` 与 ``sub.merge_bilingual``。

``sub.match_project`` 把拖回的译文字幕与原项目的原文 SRT 配对，输出带
``role`` / ``pair_id`` 元数据的成对产物；``sub.merge_bilingual`` 按 pair 分组，
调用 :mod:`subtitle_engine.domain.merge` 生成双语 ASS。算法层与旧
``tools/merge_srt.py`` 逐字节一致（见 ``tests/test_merge_steps.py``）。
"""

from __future__ import annotations

import asyncio
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, Field

from ..core.models import Artifact, PortSpec
from ..core.registry import register_step
from ..core.step import Step, StepContext
from ..domain.merge import (
    DEFAULT_L1_STYLE_DEF,
    DEFAULT_L2_STYLE_DEF,
    clean_translated_name,
    merge_entries,
    parse_patterns,
    parse_srt_entries,
    render_ass,
)
from ..domain.srt import parse_srt
from ..rpc.errors import INVALID_PARAMS, STEP_FAILED, JsonRpcError
from ._support import artifact_meta, artifact_stem, ingest_run_inputs, read_text

_SRT_SUFFIXES = (".srt",)
_ORIGINAL_HINTS = ("clean", "output", "extracted")
_BASE_STRIP_SUFFIXES = (".clean", ".orig", ".normalized", ".fps", ".shifted", ".scaled")


def _base_stem(path: str | Path, pattern: str | list[str]) -> str:
    """取用于配对/命名的干净 stem：去掉语言后缀与已知处理后缀，保留原始大小写。"""
    stem = Path(str(path)).stem
    for part in parse_patterns(pattern):
        match = re.search(
            rf"[._-]{re.escape(part)}(?:[-_][a-zA-Z0-9]+)?$", stem, re.IGNORECASE
        )
        if match:
            stem = stem[: match.start()]
            break
        if stem.lower() == part:
            stem = ""
            break
    for suffix in _BASE_STRIP_SUFFIXES:
        if stem.lower().endswith(suffix) and len(stem) > len(suffix):
            stem = stem[: -len(suffix)]
    return stem.strip("._- ")


def _timeline_stats(text: str) -> dict[str, float]:
    doc = parse_srt(text)
    if not doc.cues:
        return {"count": 0, "first_start": 0.0, "last_end": 0.0}
    return {
        "count": float(len(doc.cues)),
        "first_start": doc.cues[0].start,
        "last_end": doc.cues[-1].end,
    }


def _timeline_match(
    translated: dict[str, float],
    original: dict[str, float],
    *,
    min_cue_ratio: float,
    max_edge_diff_s: float,
) -> dict[str, Any]:
    t_count = translated["count"]
    o_count = original["count"]
    if t_count <= 0 or o_count <= 0:
        return {"similar": False, "ratio": 0.0, "edge_diff_s": float("inf")}
    ratio = min(t_count, o_count) / max(t_count, o_count)
    edge_diff = max(
        abs(translated["first_start"] - original["first_start"]),
        abs(translated["last_end"] - original["last_end"]),
    )
    return {
        "similar": ratio >= min_cue_ratio and edge_diff <= max_edge_diff_s,
        "ratio": round(ratio, 4),
        "edge_diff_s": round(edge_diff, 3),
    }


def _candidate_priority(path: str) -> tuple[int, str]:
    """原文候选优先级：clean 优先，其次 output / extracted。"""
    normalized = path.replace("\\", "/").lower()
    for rank, hint in enumerate(_ORIGINAL_HINTS):
        if f"/{hint}/" in normalized:
            return (rank, normalized)
    return (len(_ORIGINAL_HINTS), normalized)


def _project_candidate_paths(project: Any) -> list[str]:
    paths: list[str] = []
    outputs = getattr(project, "outputs", None) or []
    for output in outputs:
        raw = getattr(output, "path", output)
        if str(raw).lower().endswith(_SRT_SUFFIXES):
            paths.append(str(raw))
    workspace_raw = getattr(project, "workspace", "") or ""
    if workspace_raw:
        workspace = Path(workspace_raw)
        for hint in _ORIGINAL_HINTS:
            folder = workspace / hint
            if folder.is_dir():
                paths.extend(str(item) for item in sorted(folder.glob("*.srt")))
    return paths


def _sibling_candidate_paths(translated_paths: list[str], pattern: str | list[str]) -> list[str]:
    """译文字幕同目录下的原文候选（不含带语言后缀的译文）。"""
    paths: list[str] = []
    for raw in translated_paths:
        folder = Path(raw).parent
        if not folder.is_dir():
            continue
        for item in sorted(folder.glob("*.srt")):
            name = item.name.lower()
            if clean_translated_name(name, pattern) != Path(name).stem:
                continue
            paths.append(str(item))
    return paths


def _dedupe(paths: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for path in paths:
        key = str(Path(path).resolve()).lower()
        if key in seen:
            continue
        seen.add(key)
        result.append(path)
    return result


class MatchProjectOptions(BaseModel):
    strategy: Literal["stem_then_timeline", "stem", "timeline"] = Field(
        default="stem_then_timeline", description="译文与项目的匹配策略"
    )
    pattern: str = Field(default="zh", description="译文语言后缀特征，如 zh / zh-CN")
    min_cue_ratio: float = Field(
        default=0.9, gt=0, le=1, description="段落数相似度下限（差异 < 10%）"
    )
    max_edge_diff_s: float = Field(
        default=1.0, ge=0, description="首尾时间轴允许误差（秒）"
    )
    project_id: str = Field(default="", description="指定项目 id；留空使用当前运行项目")


@register_step
class MatchProject(Step):
    id = "sub.match_project"
    title = "匹配原项目"
    description = "按文件名与时间轴相似度为译文匹配原项目，输出带角色标记的成对字幕。"
    inputs: dict[str, PortSpec] = {
        "subs": PortSpec(kind="srt", required=False, multiple=True)
    }
    outputs: dict[str, PortSpec] = {"subs": PortSpec(kind="srt", multiple=True)}
    Options = MatchProjectOptions
    requires_agent = False
    deterministic = True

    async def run(self, ctx: StepContext, inputs: dict) -> dict:
        options: MatchProjectOptions = ctx.options  # type: ignore[assignment]
        sources: list[Artifact] = inputs.get("subs") or ingest_run_inputs(ctx)

        project = getattr(ctx, "project", None)
        if project is None and options.project_id:
            project = ctx.services.store.get_project(options.project_id)

        translated_paths = [
            str(artifact.meta.get("source_path") or artifact.path) for artifact in sources
        ]
        candidate_paths = _dedupe(
            _project_candidate_paths(project)
            + _sibling_candidate_paths(translated_paths, options.pattern)
        )
        # 译文自身不能作为原文候选
        translated_keys = {str(Path(path).resolve()).lower() for path in translated_paths}
        candidate_paths = [
            path
            for path in candidate_paths
            if str(Path(path).resolve()).lower() not in translated_keys and Path(path).is_file()
        ]

        candidates: list[dict[str, Any]] = []
        for path in candidate_paths:
            try:
                text = Path(path).read_text(encoding="utf-8-sig")
            except (OSError, UnicodeDecodeError) as exc:
                ctx.emit(
                    "step.log",
                    level="warning",
                    message=f"跳过无法读取的原文候选 {Path(path).name}: {exc}",
                )
                continue
            candidates.append(
                {
                    "path": path,
                    "stem": _base_stem(path, options.pattern),
                    "timeline": _timeline_stats(text),
                }
            )

        if not candidates:
            raise JsonRpcError(
                STEP_FAILED,
                "未找到可匹配的原文字幕，请先完成视频清理流程或把原文 SRT 放到同目录",
                {
                    "step": self.id,
                    "translated": [Path(path).name for path in translated_paths],
                    "reason": "no_candidates",
                },
            )

        results: list[Artifact] = []
        used_pair_ids: set[str] = set()

        for position, artifact in enumerate(sources):
            translated_path = translated_paths[position]
            translated_text = read_text(artifact)
            translated_stats = _timeline_stats(translated_text)
            base = _base_stem(translated_path, options.pattern) or artifact_stem(artifact)

            scored: list[dict[str, Any]] = []
            for candidate in candidates:
                stem_match = candidate["stem"] == base
                timeline = _timeline_match(
                    translated_stats,
                    candidate["timeline"],
                    min_cue_ratio=options.min_cue_ratio,
                    max_edge_diff_s=options.max_edge_diff_s,
                )
                scored.append(
                    {
                        "candidate": candidate,
                        "stem_match": stem_match,
                        "timeline": timeline,
                    }
                )

            chosen = self._choose(scored, options.strategy)
            if chosen is None:
                raise JsonRpcError(
                    STEP_FAILED,
                    f"无法为 {Path(translated_path).name} 找到可信的原文匹配，请人工选择",
                    {
                        "step": self.id,
                        "translated": translated_path,
                        "strategy": options.strategy,
                        "reason": "low_confidence",
                        "candidates": [
                            {
                                "path": item["candidate"]["path"],
                                "stem": item["candidate"]["stem"],
                                "stem_match": item["stem_match"],
                                **item["timeline"],
                            }
                            for item in scored
                        ],
                    },
                )

            original_path = chosen["candidate"]["path"]
            pair_id = f"pair_{position:03d}"
            while pair_id in used_pair_ids:
                pair_id = f"{pair_id}_"
            used_pair_ids.add(pair_id)

            original_data = Path(original_path).read_bytes()
            original_stored = ctx.services.store.put_bytes(
                key=f"{base}.orig",
                kind="srt",
                data=original_data,
                suffix=".srt",
                meta={
                    "source_path": original_path,
                    "source_stem": Path(original_path).stem,
                    "output_stem": base,
                    "role": "original",
                    "pair_id": pair_id,
                    "match": {
                        "strategy": options.strategy,
                        "stem_match": chosen["stem_match"],
                        **chosen["timeline"],
                    },
                },
            )
            # 内容寻址存储遇到同哈希会复用旧记录（meta 可能不含角色），
            # 因此这里显式包裹一份带 role/pair_id 的产物视图。
            original_meta = artifact_meta(original_stored)
            original_meta.update(
                {
                    "source_path": original_path,
                    "source_stem": Path(original_path).stem,
                    "output_stem": base,
                    "role": "original",
                    "pair_id": pair_id,
                    "match": {
                        "strategy": options.strategy,
                        "stem_match": chosen["stem_match"],
                        **chosen["timeline"],
                    },
                }
            )
            original = original_stored.model_copy(update={"meta": original_meta})
            translated_meta = artifact_meta(artifact)
            translated_meta.update(
                {
                    "source_path": translated_path,
                    "output_stem": base,
                    "role": "translated",
                    "pair_id": pair_id,
                }
            )
            translated = artifact.model_copy(update={"meta": translated_meta})

            results.extend([original, translated])
            ctx.emit(
                "step.log",
                level="info",
                message=(
                    f"已配对 {Path(translated_path).name} → {Path(original_path).name}"
                    f"（stem={'是' if chosen['stem_match'] else '否'}, "
                    f"段落相似度={chosen['timeline']['ratio']}）"
                ),
            )
            ctx.progress(
                (position + 1) / len(sources), f"已匹配 {position + 1}/{len(sources)} 条译文"
            )
            if ctx.is_cancelled():
                raise asyncio.CancelledError

        return {"subs": results}

    @staticmethod
    def _choose(scored: list[dict[str, Any]], strategy: str) -> dict[str, Any] | None:
        """按策略选择最佳候选；无可靠候选返回 ``None``。"""
        stem_matches = [item for item in scored if item["stem_match"]]
        timeline_matches = [item for item in scored if item["timeline"]["similar"]]

        if strategy == "stem":
            pool = stem_matches
        elif strategy == "timeline":
            pool = timeline_matches
        else:  # stem_then_timeline
            pool = stem_matches or timeline_matches

        if not pool:
            return None
        pool.sort(
            key=lambda item: (
                not item["stem_match"],
                item["timeline"]["edge_diff_s"],
                -item["timeline"]["ratio"],
                _candidate_priority(item["candidate"]["path"]),
            )
        )
        return pool[0]


class MergeBilingualOptions(BaseModel):
    style_preset: str = Field(default="house_default", description="ASS 样式预设")
    output_suffix: str = Field(default=".zh&en", description="输出文件名后缀")
    pattern: str = Field(default="zh", description="译文语言后缀特征，用于无 pair_id 时分组")
    author: str = Field(default="lns103", description="ASS Author 字段")
    comment: str = Field(
        default="made by subtitle engine", description="ASS Comment 字段（留空使用当前日期）"
    )
    playresx: int = Field(default=1920, gt=0)
    playresy: int = Field(default=1080, gt=0)
    lang1_style_name: str = Field(default="Chinese", description="译文样式名")
    lang1_style_def: str = Field(default=DEFAULT_L1_STYLE_DEF, description="译文样式定义")
    lang2_style_name: str = Field(default="Original", description="原文样式名")
    lang2_style_def: str = Field(default=DEFAULT_L2_STYLE_DEF, description="原文样式定义")


@dataclass
class _Pair:
    original: Artifact
    translated: Artifact
    base: str


@register_step
class MergeBilingual(Step):
    id = "sub.merge_bilingual"
    title = "合并双语 ASS"
    description = "把译文与原字幕按时间轴合并为双行 ASS（保留旧版重复片段字体对齐）。"
    inputs: dict[str, PortSpec] = {
        "subs": PortSpec(kind="srt", required=False, multiple=True),
        "original": PortSpec(kind="srt", required=False, multiple=True),
        "translated": PortSpec(kind="srt", required=False, multiple=True),
    }
    outputs: dict[str, PortSpec] = {"subs": PortSpec(kind="ass", multiple=True)}
    Options = MergeBilingualOptions
    requires_agent = False
    deterministic = True

    async def run(self, ctx: StepContext, inputs: dict) -> dict:
        options: MergeBilingualOptions = ctx.options  # type: ignore[assignment]
        if options.style_preset != "house_default":
            raise JsonRpcError(
                INVALID_PARAMS,
                f"未知样式预设: {options.style_preset}",
                {"step": self.id, "supported": ["house_default"]},
            )

        # 只有命名输入绑定（meta.input_name）才视为显式原文；旧配方经
        # match/validate 自动流入的产物仍走 _group_pairs 兼容路径。
        originals: list[Artifact] = [
            artifact
            for artifact in inputs.get("original") or []
            if (artifact.meta or {}).get("input_name") == "original"
        ]
        translated_candidates: list[Artifact] = (
            inputs.get("translated") or inputs.get("subs") or []
        )
        translated: list[Artifact] = [
            artifact
            for artifact in translated_candidates
            if (artifact.meta or {}).get("input_name") != "original"
        ]
        artifacts: list[Artifact] = list(translated_candidates)
        if originals:
            pairs = self._pair_explicit(originals, translated, options)
        else:
            if not artifacts:
                raise JsonRpcError(INVALID_PARAMS, "没有可合并的字幕", {"step": self.id})
            pairs = self._group_pairs(artifacts, options)
        results: list[Artifact] = []
        warnings: list[str] = []

        for position, pair in enumerate(pairs):
            eng_entries = parse_srt_entries(read_text(pair.original))
            zh_entries = parse_srt_entries(read_text(pair.translated))
            merged = merge_entries(
                eng_entries,
                zh_entries,
                lang2_style_name=options.lang2_style_name,
                lang1_style_def=options.lang1_style_def,
                lang2_style_def=options.lang2_style_def,
            )
            ass_text = render_ass(
                merged.entries,
                pair.base,
                author=options.author,
                comment=options.comment or None,
                playresx=options.playresx,
                playresy=options.playresy,
                lang1_style_name=options.lang1_style_name,
                lang1_style_def=options.lang1_style_def,
                lang2_style_name=options.lang2_style_name,
                lang2_style_def=options.lang2_style_def,
            )
            key = f"{pair.base}{options.output_suffix}"
            result = ctx.services.store.put_bytes(
                key=key,
                kind="ass",
                data=(ass_text.rstrip("\n") + "\n").encode("utf-8"),
                suffix=".ass",
                meta={
                    "source_hash": pair.translated.hash,
                    "source_stem": pair.base,
                    "output_stem": key,
                    "original_hash": pair.original.hash,
                    "pair_id": pair.translated.meta.get("pair_id", ""),
                    "cue_count": len(merged.entries),
                    "warnings": merged.warnings,
                },
            )
            results.append(result)
            warnings.extend(merged.warnings)

            for warning in merged.warnings:
                ctx.emit("step.log", level="warning", message=f"{pair.base}: {warning}")
            ctx.emit(
                "step.log",
                level="info",
                message=f"已合并 {pair.base} → {key}.ass（{len(merged.entries)} 段）",
            )
            ctx.progress(
                (position + 1) / len(pairs), f"已合并 {position + 1}/{len(pairs)} 对字幕"
            )
            if ctx.is_cancelled():
                raise asyncio.CancelledError

        return {"subs": results}

    @staticmethod
    def _pair_explicit(
        originals: list[Artifact],
        translated: list[Artifact],
        options: MergeBilingualOptions,
    ) -> list[_Pair]:
        """显式原文/译文输入：优先按干净 stem 配对，剩余按顺序配对。"""
        if not translated:
            raise JsonRpcError(
                INVALID_PARAMS,
                "提供了原文字幕但没有译文字幕",
                {"step": "sub.merge_bilingual", "original_count": len(originals)},
            )
        if len(originals) != len(translated):
            raise JsonRpcError(
                INVALID_PARAMS,
                "原文与译文数量不一致，无法配对合并",
                {
                    "step": "sub.merge_bilingual",
                    "original_count": len(originals),
                    "translated_count": len(translated),
                },
            )

        def base_of(artifact: Artifact) -> str:
            source = str((artifact.meta or {}).get("source_path") or artifact.path)
            return _base_stem(source, options.pattern) or artifact_stem(artifact)

        translated_items = sorted(translated, key=lambda item: base_of(item).lower())
        by_base: dict[str, list[Artifact]] = {}
        for item in translated_items:
            by_base.setdefault(base_of(item).lower(), []).append(item)

        used: set[int] = set()
        pairs: list[_Pair] = []
        leftovers: list[Artifact] = []
        for original in sorted(originals, key=lambda item: base_of(item).lower()):
            bucket = by_base.get(base_of(original).lower(), [])
            match = next(
                (item for item in bucket if id(item) not in used),
                None,
            )
            if match is None:
                leftovers.append(original)
                continue
            used.add(id(match))
            pairs.append(_Pair(original, match, base_of(match)))

        remaining = [item for item in translated_items if id(item) not in used]
        if len(remaining) != len(leftovers):
            raise JsonRpcError(
                INVALID_PARAMS,
                "原文与译文无法一一配对",
                {
                    "step": "sub.merge_bilingual",
                    "unpaired_original": [base_of(item) for item in leftovers],
                    "unpaired_translated": [base_of(item) for item in remaining],
                },
            )
        for original, item in zip(leftovers, remaining, strict=True):
            pairs.append(_Pair(original, item, base_of(item)))

        pairs.sort(key=lambda pair: pair.base.lower())
        return pairs

    @staticmethod
    def _group_pairs(artifacts: list[Artifact], options: MergeBilingualOptions) -> list[_Pair]:
        """优先按 ``pair_id`` 分组，其次按干净 stem + 角色分组。"""
        by_pair: dict[str, dict[str, Artifact]] = {}
        leftovers: list[Artifact] = []
        for artifact in artifacts:
            meta = artifact.meta or {}
            pair_id = str(meta.get("pair_id") or "")
            role = str(meta.get("role") or "")
            if pair_id and role in ("original", "translated"):
                by_pair.setdefault(pair_id, {})[role] = artifact
            else:
                leftovers.append(artifact)

        pairs: list[_Pair] = []
        for group in by_pair.values():
            if "original" not in group or "translated" not in group:
                continue
            translated = group["translated"]
            base = str(translated.meta.get("output_stem") or artifact_stem(translated))
            pairs.append(_Pair(group["original"], translated, base))

        # 无 pair_id 的输入：按干净 stem 分组并推断角色
        by_base: dict[str, list[Artifact]] = {}
        for artifact in leftovers:
            source = str((artifact.meta or {}).get("source_path") or artifact.path)
            base = _base_stem(source, options.pattern) or artifact_stem(artifact)
            by_base.setdefault(base, []).append(artifact)

        for base, group in by_base.items():
            if len(group) < 2:
                continue
            originals = [
                item
                for item in group
                if str((item.meta or {}).get("role") or "") == "original"
            ]
            translated = [
                item
                for item in group
                if str((item.meta or {}).get("role") or "") == "translated"
            ]
            if originals and translated:
                pairs.append(_Pair(originals[0], translated[0], base))
            elif len(group) == 2:
                # 未标注角色时约定：第一条为原文，第二条为译文
                pairs.append(_Pair(group[0], group[1], base))

        if not pairs:
            raise JsonRpcError(
                INVALID_PARAMS,
                "无法组成原文/译文配对，请先运行 sub.match_project 或成对连接字幕",
                {"step": "sub.merge_bilingual", "count": len(artifacts)},
            )
        pairs.sort(key=lambda pair: pair.base.lower())
        return pairs


__all__ = [
    "MatchProject",
    "MatchProjectOptions",
    "MergeBilingual",
    "MergeBilingualOptions",
]

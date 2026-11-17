"""审核审计 JSONL（TASKBOOK §11.6 / M5）。

文件格式：第一行 header，其后每行一条已应用的修改。审计文件既用于追责，
也是 ``review.undo`` 恢复原文的依据。
"""

from __future__ import annotations

import json
import logging
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .store import Store

logger = logging.getLogger(__name__)


def _now() -> str:
    return datetime.now(UTC).isoformat()


def write_audit(
    path: Path,
    *,
    run_id: str,
    review_id: str,
    step_id: str,
    entries: list[dict[str, Any]],
) -> Path:
    """覆盖写审计文件；``entries`` 只包含实际应用的修改。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        json.dumps(
            {
                "type": "review",
                "run_id": run_id,
                "review_id": review_id,
                "step": step_id,
                "ts": _now(),
            },
            ensure_ascii=False,
        )
    ]
    for entry in entries:
        payload = {"type": "decision", **entry}
        payload.setdefault("ts", _now())
        lines.append(json.dumps(payload, ensure_ascii=False))
    text = "\n".join(lines) + "\n"
    path.write_text(text, encoding="utf-8", newline="\n")
    return path


def read_audit(path: str | Path) -> list[dict[str, Any]]:
    """读取审计 JSONL；非法行记录 warning 后跳过（不静默）。"""
    file_path = Path(path)
    if not file_path.is_file():
        return []
    records: list[dict[str, Any]] = []
    for number, line in enumerate(
        file_path.read_text(encoding="utf-8").splitlines(), start=1
    ):
        if not line.strip():
            continue
        try:
            payload = json.loads(line)
        except json.JSONDecodeError:
            logger.warning("审计文件第 %s 行不是合法 JSON: %s", number, file_path)
            continue
        if isinstance(payload, dict):
            records.append(payload)
    return records


def restore_from_audit(store: Store, path: str | Path) -> list[dict[str, str]]:
    """按审计文件恢复 ``before`` 文本，返回新产物列表。

    恢复只重建字幕内容，不修改原内容寻址产物；新产物使用 ``.undo`` 后缀。
    """
    from ..domain.sdh import apply_text_edits
    from ..domain.srt import parse_srt, serialize_srt

    grouped: dict[str, list[dict[str, Any]]] = {}
    for record in read_audit(path):
        if record.get("type") != "decision":
            continue
        artifact_hash = str(record.get("artifact_hash") or "")
        if not artifact_hash:
            continue
        grouped.setdefault(artifact_hash, []).append(record)

    restored: list[dict[str, str]] = []
    for artifact_hash, records in grouped.items():
        source = store.get_artifact(artifact_hash)
        if source is None or not store.ensure_artifact(source):
            raise RuntimeError(f"审计引用的产物不存在或已损坏: {artifact_hash}")
        text = Path(source.path).read_text(encoding="utf-8-sig")
        doc = parse_srt(text)
        edits = {
            int(record["segment_index"]): str(record.get("before", ""))
            for record in records
            if "segment_index" in record
        }
        restored_text = serialize_srt(apply_text_edits(doc.cues, edits))
        data = (restored_text.rstrip("\n") + "\n").encode("utf-8")
        stem = (
            source.meta.get("output_stem")
            or source.meta.get("source_stem")
            or Path(source.path).stem
        )
        artifact = store.put_bytes(
            key=f"{stem}.undo",
            kind="srt",
            data=data,
            suffix=".srt",
            meta={
                "source_hash": source.hash,
                "source_stem": stem,
                "output_stem": f"{stem}.undo",
                "undo_of": artifact_hash,
            },
        )
        restored.append({"path": artifact.path, "hash": artifact.hash})
    return restored


__all__ = ["read_audit", "restore_from_audit", "write_audit"]

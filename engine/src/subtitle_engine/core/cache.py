"""步骤级结果缓存（TASKBOOK 10.2）。

缓存键由 ``step_id``、``engine_version``、规范化 ``options``、输入产物哈希与
额外标记共同决定；缓存负载只保存端口到产物哈希的映射，产物的存在性与内容
校验全部委托 :class:`~subtitle_engine.core.store.Store`，本模块不做文件 IO。
"""

from __future__ import annotations

import hashlib
import json
import logging
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from .models import Artifact
    from .store import Store

logger = logging.getLogger(__name__)

# 字段分隔符选用 ASCII 单元分隔符，避免普通文本拼接产生歧义。
_SEP = "\x1f"


class StepCache:
    """基于 :class:`Store` 的步骤结果缓存。

    只负责键计算与缓存负载的校验；哈希不一致、文件缺失或负载损坏均按
    未命中处理，并顺带清理失效的缓存项。``Store`` 抛出的数据库错误不会被
    捕获，交由调用方处理。
    """

    def __init__(self, store: Store, *, engine_version: str) -> None:
        self._store = store
        self._engine_version = engine_version

    def compute_key(
        self,
        *,
        step_id: str,
        options: dict[str, Any],
        inputs: dict[str, Artifact],
        extra: str = "",
    ) -> str:
        """计算缓存键：各字段以 ``\\x1f`` 分隔后取 sha256 十六进制。"""
        canonical_options = json.dumps(
            options,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        )
        input_hashes = sorted(artifact.hash for artifact in inputs.values())
        material = _SEP.join(
            [
                step_id,
                self._engine_version,
                canonical_options,
                _SEP.join(input_hashes),
                extra,
            ]
        )
        return hashlib.sha256(material.encode("utf-8")).hexdigest()

    def get(self, key: str) -> dict[str, Artifact] | None:
        """读取缓存；命中返回 ``{port: Artifact}``，否则返回 ``None``。"""
        payload = self._store.get_cache_payload(key)
        if payload is None:
            return None

        try:
            outputs = _parse_payload(payload)
        except (TypeError, ValueError) as exc:
            self._discard(key, f"缓存负载无法解析: {exc}")
            return None

        resolved: dict[str, Artifact] = {}
        for port, artifact_hash in outputs.items():
            artifact = self._store.get_artifact(artifact_hash)
            if artifact is None:
                self._discard(key, f"产物 {artifact_hash} 缺失")
                return None
            if artifact.hash != artifact_hash:
                self._discard(key, f"产物哈希不一致: 期望 {artifact_hash}, 实际 {artifact.hash}")
                return None
            if not self._store.ensure_artifact(artifact):
                self._discard(key, f"产物 {artifact_hash} 校验失败")
                return None
            resolved[port] = artifact
        return resolved

    def put(self, key: str, outputs: dict[str, Artifact]) -> None:
        """写入缓存；``outputs`` 允许为空，用于缓存空结果。"""
        payload = json.dumps(
            {"outputs": {port: artifact.hash for port, artifact in outputs.items()}},
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
        )
        self._store.put_cache_payload(key, payload)

    def _discard(self, key: str, reason: str) -> None:
        """记录失效原因并删除缓存项。"""
        logger.warning("缓存失效 (key=%s): %s", key, reason)
        self._store.delete_cache_entry(key)


def _parse_payload(payload: str) -> dict[str, str]:
    """解析并校验缓存负载，返回 ``{port: artifact_hash}``。

    任何结构不符都抛出 ``TypeError``/``ValueError``，由调用方按未命中处理。
    """
    data = json.loads(payload)
    if not isinstance(data, dict):
        raise TypeError("根节点必须是对象")
    outputs = data.get("outputs")
    if not isinstance(outputs, dict):
        raise TypeError("outputs 必须是对象")
    result: dict[str, str] = {}
    for port, artifact_hash in outputs.items():
        if not isinstance(port, str) or not isinstance(artifact_hash, str):
            raise TypeError("端口与产物哈希必须是字符串")
        result[port] = artifact_hash
    return result

"""``StepCache`` 单元测试（使用 fake store，不依赖真实持久化实现）。"""

from __future__ import annotations

import json
import logging

import pytest

from subtitle_engine.core.cache import StepCache
from subtitle_engine.core.models import Artifact

ENGINE_VERSION = "0.1.0"


class FakeStore:
    """内存版 Store，仅实现 ``StepCache`` 使用的五个方法。"""

    def __init__(self) -> None:
        self.artifacts: dict[str, Artifact] = {}
        self.payloads: dict[str, str] = {}
        self.ensure_result = True

    def add_artifact(self, artifact: Artifact) -> Artifact:
        self.artifacts[artifact.hash] = artifact
        return artifact

    def get_artifact(self, artifact_hash: str) -> Artifact | None:
        return self.artifacts.get(artifact_hash)

    def ensure_artifact(self, artifact: Artifact) -> bool:
        return self.ensure_result

    def get_cache_payload(self, key: str) -> str | None:
        return self.payloads.get(key)

    def put_cache_payload(self, key: str, payload: str) -> None:
        self.payloads[key] = payload

    def delete_cache_entry(self, key: str) -> None:
        self.payloads.pop(key, None)


def make_artifact(name: str) -> Artifact:
    return Artifact(key=name, kind="subtitle", hash=f"hash-{name}", path=f"/tmp/{name}.srt")


@pytest.fixture
def store() -> FakeStore:
    fake = FakeStore()
    for name in ("a", "b", "c"):
        fake.add_artifact(make_artifact(name))
    return fake


@pytest.fixture
def cache(store: FakeStore) -> StepCache:
    return StepCache(store, engine_version=ENGINE_VERSION)


def make_key(
    cache: StepCache,
    *,
    step_id: str = "clean",
    options: dict | None = None,
    inputs: dict[str, Artifact] | None = None,
    extra: str = "",
) -> str:
    return cache.compute_key(
        step_id=step_id,
        options={"crlf": "lf"} if options is None else options,
        inputs={"in": make_artifact("a")} if inputs is None else inputs,
        extra=extra,
    )


def test_same_inputs_same_key(cache: StepCache) -> None:
    assert make_key(cache) == make_key(cache)


def test_options_key_order_irrelevant(cache: StepCache) -> None:
    first = make_key(cache, options={"a": 1, "b": {"x": True, "y": None}})
    second = make_key(cache, options={"b": {"y": None, "x": True}, "a": 1})
    assert first == second


@pytest.mark.parametrize(
    "changed",
    [
        {"step_id": "other"},
        {"options": {"crlf": "crlf"}},
        {"options": {"crlf": "lf", "extra": 1}},
        {"extra": "variant"},
    ],
)
def test_key_changes_with_fields(cache: StepCache, changed: dict) -> None:
    assert make_key(cache) != make_key(cache, **changed)


def test_key_changes_with_input_hash(cache: StepCache) -> None:
    first = make_key(cache, inputs={"in": make_artifact("a")})
    second = make_key(cache, inputs={"in": make_artifact("b")})
    assert first != second


def test_key_ignores_input_port_name(cache: StepCache) -> None:
    first = make_key(cache, inputs={"left": make_artifact("a")})
    second = make_key(cache, inputs={"right": make_artifact("a")})
    assert first == second


def test_key_changes_with_engine_version(store: FakeStore) -> None:
    first = StepCache(store, engine_version="0.1.0").compute_key(
        step_id="clean", options={}, inputs={}
    )
    second = StepCache(store, engine_version="0.2.0").compute_key(
        step_id="clean", options={}, inputs={}
    )
    assert first != second


def test_key_is_sha256_hex(cache: StepCache) -> None:
    key = make_key(cache)
    assert len(key) == 64
    assert all(char in "0123456789abcdef" for char in key)


def test_put_get_roundtrip(cache: StepCache, store: FakeStore) -> None:
    outputs = {"zh": store.artifacts["hash-a"], "en": store.artifacts["hash-b"]}
    key = make_key(cache)
    cache.put(key, outputs)

    assert cache.get(key) == outputs
    assert store.payloads[key] == json.dumps(
        {"outputs": {"en": "hash-b", "zh": "hash-a"}},
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    )


def test_put_get_empty_outputs(cache: StepCache) -> None:
    key = make_key(cache)
    cache.put(key, {})
    assert cache.get(key) == {}


def test_get_missing_key(cache: StepCache) -> None:
    assert cache.get("does-not-exist") is None


def test_get_missing_artifact(cache: StepCache, store: FakeStore) -> None:
    key = make_key(cache)
    cache.put(key, {"zh": make_artifact("a")})
    store.artifacts.clear()

    assert cache.get(key) is None
    assert key not in store.payloads


def test_get_ensure_failure(cache: StepCache, store: FakeStore) -> None:
    key = make_key(cache)
    cache.put(key, {"zh": make_artifact("a")})
    store.ensure_result = False

    assert cache.get(key) is None
    assert key not in store.payloads


def test_get_hash_mismatch(cache: StepCache, store: FakeStore) -> None:
    key = make_key(cache)
    cache.put(key, {"zh": make_artifact("a")})
    store.artifacts["hash-a"] = make_artifact("b")

    assert cache.get(key) is None
    assert key not in store.payloads


def test_corrupt_payload_is_miss(
    cache: StepCache, store: FakeStore, caplog: pytest.LogCaptureFixture
) -> None:
    key = make_key(cache)
    store.payloads[key] = "{not json"

    with caplog.at_level(logging.WARNING, logger="subtitle_engine.core.cache"):
        assert cache.get(key) is None

    assert key not in store.payloads
    assert any("缓存失效" in record.message for record in caplog.records)


def test_invalid_payload_structure_is_miss(
    cache: StepCache, store: FakeStore, caplog: pytest.LogCaptureFixture
) -> None:
    key = make_key(cache)
    store.payloads[key] = json.dumps({"outputs": {"zh": 1}})

    with caplog.at_level(logging.WARNING, logger="subtitle_engine.core.cache"):
        assert cache.get(key) is None

    assert key not in store.payloads
    assert caplog.records

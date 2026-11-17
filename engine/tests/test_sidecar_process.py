"""真实进程集成测试：确保 stdout 只有协议 JSON，日志全在 stderr。"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from typing import Any


def run_sidecar(lines: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], str]:
    payload = "\n".join(json.dumps(line, ensure_ascii=False) for line in lines) + "\n"
    env = os.environ.copy()
    env["PYTHONIOENCODING"] = "utf-8"
    proc = subprocess.run(
        [sys.executable, "-m", "subtitle_engine", "--rpc", "stdio"],
        input=payload,
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=30,
        env=env,
    )
    assert proc.returncode == 0, proc.stderr
    responses = []
    for line in proc.stdout.splitlines():
        assert line.strip(), "stdout 不允许空行"
        responses.append(json.loads(line))  # 非 JSON 行会直接失败
    return responses, proc.stderr


def test_sidecar_handshake_and_clean_stdout() -> None:
    responses, stderr = run_sidecar(
        [
            {"jsonrpc": "2.0", "id": 1, "method": "engine.hello", "params": {}},
            {"jsonrpc": "2.0", "id": 2, "method": "steps.list", "params": {}},
            {"jsonrpc": "2.0", "id": 3, "method": "engine.shutdown", "params": {}},
        ]
    )
    by_id = {item["id"]: item for item in responses}
    assert by_id[1]["result"]["engine"] == "subtitle-engine"
    assert by_id[1]["result"]["python"].startswith("3.15")
    assert any(step["id"] == "demo.tick" for step in by_id[2]["result"])
    assert by_id[3]["result"] == "ok"
    # 启动日志出现在 stderr，而不是 stdout
    assert "subtitle-engine" in stderr
    assert "Traceback" not in stderr


def test_sidecar_prints_version_without_entering_rpc() -> None:
    proc = subprocess.run(
        [sys.executable, "-m", "subtitle_engine", "--version"],
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=30,
    )
    assert proc.returncode == 0
    assert proc.stdout.strip().startswith("subtitle-engine ")
    assert proc.stderr == ""

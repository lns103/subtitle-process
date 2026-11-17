"""共享测试工具。"""

from __future__ import annotations

import json
from typing import Any


def collect_json_lines(raw: str) -> list[dict[str, Any]]:
    return [json.loads(line) for line in raw.splitlines() if line.strip()]

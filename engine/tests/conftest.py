"""共享测试工具。"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

# 旧工具箱冻结副本（golden 对比基准）放在 tests/legacy_reference/ 下，
# 让测试可以直接 `from legacy_reference import ...`。
TESTS_DIR = Path(__file__).resolve().parent
if str(TESTS_DIR) not in sys.path:
    sys.path.insert(0, str(TESTS_DIR))


def collect_json_lines(raw: str) -> list[dict[str, Any]]:
    return [json.loads(line) for line in raw.splitlines() if line.strip()]

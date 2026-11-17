"""引擎入口：``python -m subtitle_engine --rpc stdio``。"""

from __future__ import annotations

import argparse
import asyncio
import logging
import sys
from collections.abc import Sequence

from .version import __version__


def _setup_logging(level: str) -> None:
    # stdout 只允许协议 JSON；所有日志固定走 stderr。
    logging.basicConfig(
        stream=sys.stderr,
        level=getattr(logging, level.upper(), logging.INFO),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="subtitle-engine",
        description="字幕流水线 v2 引擎（JSON-RPC over stdio）",
    )
    parser.add_argument(
        "--rpc",
        choices=["stdio"],
        default=None,
        help="通信模式；stdio 表示 sidecar 模式",
    )
    parser.add_argument("--version", action="store_true", help="打印版本后退出")
    parser.add_argument(
        "--log-level",
        default="INFO",
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
        help="stderr 日志级别（默认 INFO）",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    _setup_logging(args.log_level)

    if args.version:
        sys.stdout.write(f"subtitle-engine {__version__}\n")
        sys.stdout.flush()
        return 0

    if args.rpc != "stdio":
        build_parser().print_help(sys.stderr)
        return 2

    from .rpc.server import serve_stdio

    logging.getLogger(__name__).info(
        "subtitle-engine %s 启动，pid=%s，python=%s",
        __version__,
        __import__("os").getpid(),
        sys.version.split()[0],
    )
    try:
        asyncio.run(serve_stdio())
    except KeyboardInterrupt:
        return 0
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

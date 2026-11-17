"""引擎入口。

用法：
  python -m subtitle_engine --rpc stdio          # sidecar 模式（stdout 只输出协议 JSON）
  python -m subtitle_engine run recipes/demo.yaml --input file.mkv
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
import sys
from collections.abc import Sequence
from typing import Any

from .version import __version__


def _setup_logging(level: str) -> None:
    # stdout 只允许协议 JSON / CLI 结果；所有日志固定走 stderr。
    logging.basicConfig(
        stream=sys.stderr,
        level=getattr(logging, str(level).upper(), logging.INFO),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="subtitle-engine",
        description="字幕流水线 v2 引擎（JSON-RPC over stdio / CLI）",
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

    sub = parser.add_subparsers(dest="command")
    sub.add_parser("rpc", help="启动 JSON-RPC stdio 服务（等同 --rpc stdio）")

    run_p = sub.add_parser("run", help="在 CLI 中运行配方")
    run_p.add_argument("recipe", help="配方文件路径（.yaml/.yml/.json）")
    run_p.add_argument(
        "--input",
        action="append",
        default=[],
        metavar="PATH",
        help="输入路径，可重复",
    )
    run_p.add_argument(
        "--data-dir",
        default=None,
        help="数据目录（默认 %%APPDATA%%/SubtitleProcess）",
    )
    run_p.add_argument("--project-id", default=None, help="关联项目 ID（可选）")
    run_p.add_argument("--max-retries", type=int, default=1, help="可重试错误的最大重试次数")
    run_p.add_argument("--no-cache", action="store_true", help="禁用步骤缓存")
    run_p.add_argument(
        "--continue-on-error",
        action="store_true",
        help="某步失败后继续执行其它分支（下游标记 skipped）",
    )
    run_p.add_argument("--json", action="store_true", help="stdout 输出最终 Run JSON")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    _setup_logging(args.log_level)

    if args.version:
        sys.stdout.write(f"subtitle-engine {__version__}\n")
        sys.stdout.flush()
        return 0

    if args.rpc == "stdio" or args.command == "rpc":
        return _serve_stdio()

    if args.command == "run":
        return asyncio.run(_run_command(args))

    build_parser().print_help(sys.stderr)
    return 2


def _serve_stdio() -> int:
    from .rpc.server import serve_stdio

    logging.getLogger(__name__).info(
        "subtitle-engine %s 启动，pid=%s，python=%s",
        __version__,
        os.getpid(),
        sys.version.split()[0],
    )
    try:
        asyncio.run(serve_stdio())
    except KeyboardInterrupt:
        return 0
    return 0


def _format_event(event) -> str:
    """CLI 日志只输出结构化摘要，绝不打印字幕正文。"""
    etype = getattr(event, "type", "")
    step = getattr(event, "step", None) or "-"
    if etype == "step.progress":
        percent = round(float(getattr(event, "percent", 0.0)) * 100)
        message = getattr(event, "message", "") or ""
        return f"[{step}] {percent:3d}% {message}".rstrip()
    if etype == "step.log":
        level = getattr(event, "level", "info")
        return f"[{step}] {level.upper()}: {getattr(event, 'message', '')}"
    if etype == "step.artifact":
        return f"[{step}] artifact {getattr(event, 'key', '?')} → {getattr(event, 'path', '?')}"
    if etype == "step.failed":
        error = getattr(event, "error", None)
        if isinstance(error, dict):
            detail = str(error.get("message", ""))
        elif error is not None:
            detail = str(getattr(error, "message", error))
        else:
            detail = ""
        return f"[{step}] FAILED: {detail}"
    if etype == "run.finished":
        status = getattr(event, "status", "?")
        duration = getattr(event, "duration_ms", 0)
        return f"run finished: {status} ({duration} ms)"
    return f"{etype} {getattr(event, 'message', '')}".rstrip()


async def _run_command(args: argparse.Namespace) -> int:
    # 导入步骤包，触发 @register_step；缺少这一步 CLI 会看不到任何步骤实现。
    from . import steps as _steps  # noqa: F401
    from .core.cache import StepCache
    from .core.paths import resolve_data_dir
    from .core.pipeline import JobManager
    from .core.recipes import load_recipe_file
    from .core.store import Store
    from .version import __version__ as engine_version

    try:
        recipe = load_recipe_file(args.recipe)
    except Exception as exc:  # noqa: BLE001 - CLI 边界，给出可读信息
        sys.stderr.write(f"无法加载配方: {exc}\n")
        return 2

    data_dir = resolve_data_dir(args.data_dir)
    data_dir.mkdir(parents=True, exist_ok=True)
    workspace = data_dir / "workspace"
    workspace.mkdir(parents=True, exist_ok=True)

    store = Store(data_dir)
    cache = StepCache(store, engine_version=engine_version)

    def sink(event: Any) -> None:
        sys.stderr.write(_format_event(event) + "\n")
        sys.stderr.flush()

    jobs = JobManager(sink, store=store, cache=cache, workspace=workspace)
    try:
        run = jobs.start(
            recipe,
            inputs=list(args.input),
            project_id=args.project_id,
            max_retries=args.max_retries,
            use_cache=not args.no_cache,
            continue_on_error=args.continue_on_error,
        )
        finished = await jobs.wait(run.id)
    finally:
        await jobs.shutdown()
        store.close()

    if args.json:
        sys.stdout.write(
            json.dumps(
                finished.model_dump(mode="json", exclude_none=True), ensure_ascii=False
            )
            + "\n"
        )
    else:
        sys.stdout.write(f"{finished.status}\n")
    sys.stdout.flush()
    return 0 if finished.status == "done" else 1


if __name__ == "__main__":
    raise SystemExit(main())

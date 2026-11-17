# subtitle-engine

字幕流水线 v2 的 headless Python 引擎（Python 3.15）。协议见 `docs/pipeline-v2/PROTOCOL.md`。

## 开发

```powershell
cd engine
uv sync
uv run pytest -q
uv run ruff check .
```

## 运行

### Sidecar（给 Tauri 用）

```powershell
uv run python -m subtitle_engine --rpc stdio
```

`stdout` **只输出** JSON-RPC 消息（一行一个 JSON 对象，UTF-8，LF 结尾）；日志、traceback 全部走 `stderr`。业务代码禁止 `print()`。

### CLI

```powershell
uv run python -m subtitle_engine run recipes/demo.yaml --input video.mkv --json
```

| 参数 | 说明 |
|---|---|
| `--input PATH` | 输入路径，可重复；`media.probe` 默认读取第一个路径 |
| `--data-dir DIR` | 数据目录；默认 `%APPDATA%/SubtitleProcess` |
| `--project-id ID` | 关联项目（同项目并发返回 `1004`） |
| `--max-retries N` | 可重试错误的最大重试次数（默认 1） |
| `--no-cache` | 禁用步骤缓存 |
| `--continue-on-error` | 失败只跳过下游，其它分支继续 |
| `--json` | stdout 输出最终 Run JSON |

退出码：`0` 成功，`1` 运行失败/取消，`2` 配方或参数错误。

## 数据布局

```
<data-dir>/
├─ store.db                 # SQLite：projects/runs/artifacts/reviews/run_state/settings/step_cache
├─ artifacts/<sha256>/      # 内容寻址产物，同哈希复用
└─ workspace/               # 步骤工作目录
```

API Key 不写入 `store.db`：`secrets.set` 使用系统钥匙串（`keyring`，Windows Credential
Manager）。headless/CI 可用 `SUBTITLE_ENGINE_AGENT_API_KEY` 环境变量临时提供 Key。

## 结构

- `core/`：models、registry、pipeline（拓扑/缓存/重试/取消/并发）、store、cache、events、processes、recipes
- `steps/`：步骤实现，`@register_step` 自动注册
  - `demo.*`：M1 演示步骤
  - `media.probe` / `media.extract_subtitles`：ffprobe / ffmpeg / MKVToolNix
  - `sub.normalize` / `sub.validate` / `sub.export`：清理、校验与导出
  - `sub.sdh_scan` / `human.review`：SDH 规则标记、HITL 审核与审计（M5）
  - `agent.sdh_review`：只处理 SDH 候选的 Agent 结构化决策（M6）
  - `sub.match_project` / `sub.merge_bilingual`：译文与原项目匹配、双语 ASS 合并（M7）
  - `sub.fps_convert` / `sub.shift_time` / `sub.rename` / `sub.outline_scale`：时间轴与文件整理（M7）
- `domain/`：纯算法层（SRT 解析、清理、SDH 规则、媒体解析、路径、校验、双语合并、时间轴、重命名、描边缩放），可在无 GUI/子进程环境单测
- `adapters/`：ffmpeg / ffprobe / mkvmerge 子进程封装，缺失依赖抛 `1006`
- `rpc/`：JSONL 分帧、JSON-RPC 服务端、错误码
- `agents/`：OpenAI 兼容客户端、SDH 提示词/结构化决策、设置与钥匙串门面（M6）

## 约定

- 严禁静默吞异常：失败必须抛错或写入步骤错误，并发送 `step.failed`。
- 子进程一律通过 `ctx.services.processes.spawn()` 启动，保证取消时被杀进程树。
- 步骤 Options 用 Pydantic 定义，`steps.list` 自动输出 JSON Schema，前端不得硬编码表单。

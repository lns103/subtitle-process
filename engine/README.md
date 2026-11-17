# subtitle-engine

字幕流水线 v2 的 headless Python 引擎。协议见 `docs/pipeline-v2/PROTOCOL.md`。

```powershell
cd engine
uv sync
uv run python -m subtitle_engine --rpc stdio
uv run pytest -q
```

## 约定

- `stdout` **只输出** JSON-RPC 消息（一行一个 JSON 对象，UTF-8，LF 结尾）。
- 日志、traceback、调试输出一律走 `stderr`。
- 业务代码禁止 `print()`。

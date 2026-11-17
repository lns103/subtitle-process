# 字幕工具箱 · 桌面壳

Tauri v2 + React 19 + TypeScript + Vite + Tailwind。Rust 只负责窗口、拖拽、对话框与 Python sidecar 进程管理，业务逻辑全部在 `engine/`。

## 开发

```powershell
# 1) 先确保引擎可用
cd ../../engine
uv sync

# 2) 启动桌面应用（会自动 spawn `uv run python -m subtitle_engine --rpc stdio`）
cd ../apps/desktop
npm install
npm run tauri dev
```

引擎查找顺序：

1. `SUBTITLE_ENGINE_BIN` 环境变量（完整 exe 路径）
2. 与主程序同目录的 `subtitle-engine.exe`（打包后）
3. 向上查找仓库中的 `engine/pyproject.toml`，用 `uv run` 启动（开发模式）

可通过 `SUBTITLE_ENGINE_DIR` / `SUBTITLE_UV` 覆盖引擎目录和 uv 路径。

## 构建

```powershell
npm run build          # 仅前端（tsc + vite）
npm run tauri build    # 完整桌面打包（M7 接入 sidecar 后）
```

## 调试

设置 `WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS=--remote-debugging-port=9222` 后启动，可用 Chrome DevTools Protocol 检查 UI。

协议见 `docs/pipeline-v2/PROTOCOL.md`。

# Subtitle Process - AI Agent Guidelines (AGENTS.md)

## 1. 项目概览 (Project Overview)
- **技术栈**: Tauri v2 (Rust) / React 19 + TypeScript + Vite / Python 3.15 sidecar / FFmpeg & MKVToolNix
- **目录架构**:
  - `engine/`: headless Python 引擎（独立 uv 项目；`src/subtitle_engine/`）
    - `rpc/`: stdio JSONL + JSON-RPC 2.0
    - `core/`: Runner、注册表、SQLite、缓存、事件、项目与审核
    - `domain/`: 纯算法（清理、SRT/ASS、媒体、SDH、合并、时间轴、重命名）
    - `steps/`: 可编排步骤与注册
    - `tests/`: pytest；`legacy_reference/` 是旧版算法冻结副本，仅用于 golden 对比
  - `apps/desktop/`: Tauri + React 桌面端（`src/` 前端，`src-tauri/` Rust 壳与 sidecar supervisor）
  - `.github/workflows/`: `ci.yml`（引擎/前端/Rust 检查）与 `release.yml`（sidecar + 安装包）
  - `scripts/`: `build-engine.ps1`、`e2e.ps1`
  - `docs/pipeline-v2/`: 任务书与协议文档
- **旧工具箱**: 已从主线删除，完整代码在 `archive/legacy-toolbox` 分支；不要在主线上重新引入 `app_ui.py` / `ui/` / `tools/`。

## 2. 编码与路径规范 (Coding Guidelines)
- **UI 与业务解耦**: UI 通过 JSON-RPC 调用引擎；业务逻辑只能放在 `engine/`，不得依赖 Tauri 或前端。
- **stdout 协议纯净**: 引擎 stdout 只允许输出 JSON-RPC 消息；日志与 traceback 一律走 stderr，禁止 `print()` 到 stdout。
- **路径安全**: Windows 长路径 / 8.3 短路径处理统一复用 `subtitle_engine.domain.paths`。
- **编码处理**: 字幕文件写出统一显式指定 `encoding='utf-8'` 和 LF。
- **子进程**: 一律通过 `ctx.services.processes.spawn()` 启动，确保取消时清理进程树。
- **步骤参数**: 用 Pydantic 定义 Options；前端表单由 `steps.list` 的 JSON Schema 驱动，不得硬编码。

## 3. AI 行为准则 (Guardrails)
- **严禁静默吞异常**: 失败必须抛出结构化错误或写入步骤错误，并发送 `step.failed`。
- **不要修改 golden 基准**: `engine/tests/legacy_reference/` 是冻结的旧实现；算法变化请改 `domain/` 并同步测试，不要改基准来“让测试通过”。
- **尊重拖拽交互**: 谨慎修改 `apps/desktop` 的拖拽区域与 Tauri 事件/权限配置。
- **修改前核对定义**: 修改业务正则、时间轴解析或合并算法前，先阅读 `engine/src/subtitle_engine/domain/` 与现有测试。

## 4. 提交规范 (Commit Standard)
- **编写 Changelog**:
  - 每次合并分支代码前，主动更新 `CHANGELOG.md`。
- **Git 提交格式**: 遵循 Conventional Commits（如 `feat: ...`, `fix: ...`, `chore: bump version to X.Y.Z`）。
- **版本发布**: 除非主动要求，否则不要修改 `engine/pyproject.toml`、`tauri.conf.json` 或 `engine/src/subtitle_engine/version.py` 中的版本号。

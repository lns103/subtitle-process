# Subtitle Process - AI Agent Guidelines (AGENTS.md)

> 面向 AI 与人类贡献者的协作规范。协议行为以 `docs/pipeline-v2/PROTOCOL.md` 为准，
> 里程碑/任务范围以 `docs/pipeline-v2/TASKBOOK.md` 为准；本文件负责“怎么改、改完怎么验”。

## 1. 项目定位与边界 (Scope)

- **产品**: 本地字幕处理工作台。两条主流程：视频 → 规范 SRT；译文 → 双语 ASS。
- **技术栈**: Tauri v2 (Rust) / React 19 + TypeScript + Vite / Python 3.15 sidecar / FFmpeg & MKVToolNix。
- **职责分层**:
  - `engine/`: 全部业务逻辑与算法，可脱离 GUI 独立运行。
  - `apps/desktop/src/`: 只做展示、交互与状态编排，不实现字幕算法。
  - `apps/desktop/src-tauri/`: 窗口、文件对话框、sidecar 生命周期与协议转发。
- **非目标**: 不在主线恢复 v1 工具箱（`app_ui.py` / `ui/` / `tools/`）；
  旧实现仅在 `archive/legacy-toolbox` 分支与 `engine/tests/legacy_reference/` 中保留。

## 2. 目录与关键模块 (Layout)

```
engine/
  src/subtitle_engine/
    rpc/       # JSONL 分帧、JSON-RPC server、错误码
    core/      # models, step, registry, pipeline(Runner), store, cache,
               # events, projects, reviews, settings, secrets, processes, paths
    domain/    # 纯算法：clean/srt/validate/media/sdh/merge/timing/rename/outline/paths
    steps/     # 可编排步骤；导入即注册
    recipes/   # 内置只读配方（YAML）
    agents/    # OpenAI 兼容客户端、SDH prompt
  tests/       # pytest；legacy_reference/ 仅用于 golden 对比
apps/desktop/
  src/         # 页面、React Flow 编辑器、审核、设置、Zustand store、lib/api
  src-tauri/   # Rust 壳、sidecar supervisor、capabilities
docs/pipeline-v2/  # PROTOCOL.md（协议唯一事实来源）、TASKBOOK.md
scripts/           # build-engine.ps1、e2e.ps1、打包脚本
```

- `core/paths.py`: 数据目录约定（默认 `%APPDATA%/SubtitleProcess`）。
- `domain/paths.py`: Windows 长路径 / 8.3 短路径 / 引号清理。两者不要混用。
- 术语：`recipe`（配方/DAG）、`run`（一次执行）、`step`（节点）、
  `artifact`（内容寻址产物）、`review`（人工审核项）、`project`（工作区）。

## 3. 常用命令与验收 (Commands)

改动必须通过对应层的检查；CI 会执行引擎、前端、Rust 三层检查（`windows-latest`），E2E 目前仅在本地运行。

### 引擎

```powershell
cd engine
uv sync
uv run ruff check .          # line-length=100；legacy_reference 已排除
uv run pytest -q             # 全量
uv run pytest tests/test_pipeline.py -q          # 单文件
uv run pytest tests/test_pipeline.py -q -k name  # 单用例
```

### 桌面端

```powershell
cd apps/desktop
npm ci
npm test                     # vitest run
npx vitest run src/features/editor/SchemaForm.test.tsx   # 单文件
npm run build                # tsc + vite build
```

### Rust 壳

```powershell
cd apps/desktop/src-tauri
cargo check
cargo test --lib
```

### 端到端 / 本地联调

```powershell
pwsh scripts/e2e.ps1                     # 需要 ffmpeg/ffprobe/mkvextract 在 PATH
cd apps/desktop; npm run tauri dev       # 开发模式默认用 uv 拉起引擎，无需先打包 sidecar
pwsh scripts/build-engine.ps1 -Fallback  # 本地快速验证 sidecar（发布走默认 Nuitka onefile）
```

提交前至少运行受影响层的检查；跨层改动（RPC / 事件 / schema）三层都要跑。

## 4. 编码规范 (Coding Guidelines)

### 通用

- **UI 与业务解耦**: 前端只能通过 JSON-RPC 调用引擎；业务逻辑不得依赖 Tauri 或 React。
- **stdout 协议纯净**: 引擎 stdout 只允许 JSON-RPC 消息；日志/traceback 一律走 stderr，
  禁止 `print()` 到 stdout，使用 `logging`。
- **严禁静默吞异常**: 失败必须抛出结构化错误或写入步骤错误并发出 `step.failed`；
  捕获后必须记录日志并给出可诊断信息。
- **编码与换行**: 字幕写出统一显式 `encoding="utf-8"`，换行统一 `\n`（LF）。
- **不要手改锁文件**: `engine/uv.lock`、`apps/desktop/package-lock.json`、
  `apps/desktop/src-tauri/Cargo.lock` 只通过 `uv` / `npm` / `cargo` 更新
  （升版步骤见 `README.md`「升版与锁文件」）。

### Python 引擎

- 外部命令一律经 `ctx.services.processes.spawn()`（或 `adapters/ffmpeg.py` 的
  `run_capture` / `run_streaming`）启动，保证取消时清理进程树；不要直接 `subprocess.Popen`。
- 长任务要响应取消：检查 `ctx.is_cancelled()`，并避免阻塞事件循环（用 `asyncio.to_thread`）。
- 面向客户端的错误用 `rpc/errors.py` 的 `JsonRpcError` 与既有错误码；
  未知异常交给上层统一包装，不要伪造成功响应。
- 路径统一走 `domain.paths.normalize_path()`；不要自行拼接 `\\?\` 或短路径逻辑。
- 产物通过 `ctx.services.store` 写入（内容寻址），事件只携带元数据，不携带整段字幕文本。
- 算法改动必须同步测试；golden 断言优先复用 `engine/tests/legacy_reference/`。

### 前端

- RPC 调用集中在 `src/lib/api.ts` / `src/lib/rpc.ts`，组件与 store 不直接拼协议 JSON。
- 步骤参数表单由 `steps.list` 的 JSON Schema 驱动（`SchemaForm` + `lib/schema.ts`），
  不得为单个步骤硬编码表单；新增 schema 关键字要补 `schema.ts` 与测试。
- 状态放 Zustand store；组件保持无副作用，异步结果通过 store/事件更新。
- Tauri 权限最小化：新增插件能力或窗口权限时，在 `src-tauri/capabilities/default.json` 显式声明，不要放宽整组默认权限。
- 谨慎修改拖拽区域与 Tauri 事件配置，改动后手动验证单文件、文件夹、拖入槽位改槽。

### Rust 壳

- 保持 supervisor 的启动/健康检查/重启 generation 语义，避免旧进程事件污染新进程。
- 协议解析失败不得 panic 或退出，记录截断后的原始行到日志。

## 5. 步骤与配方开发 (Step Authoring)

新增步骤的最小清单：

1. 在 `engine/src/subtitle_engine/steps/` 实现 `Step` 子类，声明
   `id` / `title` / `description` / `inputs` / `outputs` / `Options` / `deterministic`。
2. `Options` 用 Pydantic `BaseModel` + `Field(description=...)`；描述会直接成为 UI 文案，
   默认值与校验写进模型，前端不重复实现。
3. 用 `@register_step` 注册，并在 `steps/__init__.py` 导入该模块（否则不会注册）。
4. 通过 `ctx.emit("step.log", ...)` / `ctx.progress(...)` 反馈；产物经 store 写入并返回
   `{port: Artifact}`（多产物返回列表）。
5. 非确定步骤（如 Agent）声明 `deterministic=False`；需要 Agent 配置的声明 `requires_agent=True`。
6. 同步配方 YAML：内置配方在 `engine/src/subtitle_engine/recipes/`；用户可编辑副本在数据目录。
7. 补测试：正常路径、边界、失败/取消、缓存键；涉及领域算法时补 golden 对比。
8. 若新增/变更 RPC 方法、事件或配方字段，先更新 `docs/pipeline-v2/PROTOCOL.md`。

## 6. 协议与事件 (Protocol)

- 传输：stdio，UTF-8 无 BOM，一行一个 JSON，单行上限 4 MiB。
- 握手：`engine.hello` 返回版本与 `capabilities`；前端按 capabilities 隐藏入口，不猜版本。
- 事件：`run.started` / `step.started` / `step.progress` / `step.log` /
  `step.artifact` / `step.failed` / `run.finished` / `review.*` / `project.updated`。
- `seq` 在单 run 内从 1 单调递增；前端按 `(run_id, seq)` 去重排序，断线后调用 `job.status` 全量刷新。
- 审核是持久化状态（`waiting_review`），不是长请求；未在 `decisions` 中出现的项默认拒绝。
- 破坏性协议变更必须递增 `engine/src/subtitle_engine/version.py::PROTOCOL_VERSION`，
  并同步 PROTOCOL.md 与前端处理。

## 7. 不要做的事 (Guardrails)

- **不要修改 golden 基准**: `engine/tests/legacy_reference/` 是冻结副本，生产代码不得导入；
  算法变化请改 `domain/` 并同步测试，不要改基准“让测试通过”。
- **不要自行升版本**: 版本号唯一来源是 `engine/src/subtitle_engine/version.py`（引擎）
  与 `apps/desktop/package.json`（桌面端），除非明确要求，不要修改这两个文件；
  `engine/pyproject.toml`、`apps/desktop/src-tauri/tauri.conf.json` 与各 lock 文件中的版本
  由它们派生，不要单独修改。
- **不要提交本地产物**: `binaries/`、`target/`、`dist/`、`build/`、`.venv/`、数据目录、
  `LOCAL_ENV.md` 均已被忽略，不要强制加入 Git。
- **不要绕过工具链**: 不手动复制 sidecar 到安装目录冒充打包结果；发布走 `scripts/`。
- **不要破坏用户数据**: 删除项目/工作区/审核记录属于破坏性操作，必须二次确认并走既有 RPC。

## 8. 提交与文档 (Commits & Docs)

- 遵循 Conventional Commits：`feat: ...`、`fix: ...`、`chore: bump version to X.Y.Z`。
- 合并分支前更新 `CHANGELOG.md`：按「新增 / 修复 / 测试 / 版本」记录用户可感知的变化。
- 架构、命令、目录或约束发生变化时，同步更新本文件与 `README.md`；
  已有测试数量、版本号等易过期信息只在 CHANGELOG 记录，不要写进 AGENTS.md。
- 提交前自查：改动层检查通过、无新增 stdout 输出、无未使用日志、无锁文件手改。

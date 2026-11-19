# Subtitle Process / 字幕工具箱

字幕流水线 v2：一个以 **Tauri v2 + React + Python sidecar** 重写的本地字幕处理工作台。

> 旧的 CustomTkinter 工具箱已从主线移除，完整实现存档在
> `archive/legacy-toolbox` 分支；仅把 golden 对比所需的领域算法冻结在
> `engine/tests/legacy_reference/`。

## 核心流程

1. **视频 → 规范字幕**
   拖入视频 → ffprobe 分析 → 提取内嵌字幕（FFmpeg / MKVToolNix）→ 规范化（去括号/人名/标签、合并短句）→
   SDH 规则扫描 →（可选）AI 审核 → 校验 → 导出 `<stem>.srt`。
2. **译文 → 双语 ASS**
   用 LinguaGacha 等工具人工翻译后，把译文 SRT 拖回 → 按文件名 + 时间轴相似度匹配原项目 →
   校验 → 合并为双行 ASS（保留重复片段字体对齐）→ 导出 `output/<stem>.zh&en.ass`。

流水线本身是**自由连线的 DAG**：内置 4 个只读模板（`batch_video_to_clean_srt`、`batch_translated_to_bilingual`、
`batch_normalize`、`batch_shift_fps`），可在编辑器中复制后任意编排。步骤参数由 Pydantic
`model_json_schema()` 自动生成表单，前端不硬编码。

## 架构

```
Tauri v2 Shell (Rust)
  ├─ 窗口 / 原生拖拽 / 单实例 / 自动更新
  ├─ 文件对话框 / 打开产物
  └─ Sidecar Supervisor（启动、健康检查、崩溃重启、进程树清理）
        ↕ stdin/stdout：JSONL + JSON-RPC 2.0
React 19 前端（React Flow / Zustand / Monaco / Tailwind）
        ↕
Python 3.15 Engine（headless）
  RPC Server → Job Manager → Pipeline Runner → Steps
  Artifact Store / SQLite / Event Bus / Agent Client / ffmpeg·mkv 适配层
```

- **stdout 只输出协议 JSON**，日志与 traceback 全部走 stderr。
- 引擎可脱离 GUI 用 CLI 运行，便于测试与未来 MCP 化。
- API Key 存 Windows 凭据管理器（`keyring`），不写入配置或日志。

## 目录结构

```
engine/                         # Python 引擎（独立 uv 项目）
  src/subtitle_engine/
    rpc/                        # JSON-RPC framing / server / errors
    core/                       # models, step, registry, pipeline, store, cache, events
    domain/                     # 纯算法：srt/clean/validate/media/sdh/merge/timing/rename/outline
    steps/                      # 步骤实现与注册
    recipes/                    # 4 个内置配方
    agents/                     # OpenAI 兼容客户端与 SDH prompt
  tests/                        # pytest（协议、Runner、步骤、golden、E2E）
    legacy_reference/           # 旧工具箱领域算法冻结副本（仅 golden 对比）
apps/desktop/                   # Tauri + React 桌面端
  src/                          # 页面、React Flow 编辑器、审核、设置
  src-tauri/                    # Rust 壳与 sidecar supervisor
scripts/                        # build-engine.ps1 / e2e.ps1
docs/pipeline-v2/               # TASKBOOK.md / PROTOCOL.md
```

## 环境要求

| 工具 | 版本 |
|---|---|
| Python | 3.15 |
| uv | 最新稳定版 |
| Node.js | 22+ |
| Rust | stable（`x86_64-pc-windows-msvc`） |
| FFmpeg | 6+（含 ffprobe） |
| MKVToolNix | 最新稳定版（MKV 字幕回落） |

## 开发

### 引擎

```powershell
cd engine
uv sync
uv run pytest -q                          # 全量测试
uv run python -m subtitle_engine --rpc stdio
uv run python -m subtitle_engine run src/subtitle_engine/recipes/batch_video_to_clean_srt.yaml --input .\demo.mkv
```

### 桌面端

```powershell
cd apps/desktop
npm install
npm run test                              # Vitest
npm run build                             # tsc + vite
npm run tauri dev                         # 开发模式（自动用 uv 拉起引擎）
```

开发模式优先使用 `uv run python -m subtitle_engine --rpc stdio`，无需每次打包 sidecar。
`target/debug/` 同目录下的 `subtitle-engine.exe` 在 dev 构建中会被忽略（避免旧产物
干扰、也省去每次重打包）；确需在 dev 中联调 sidecar 时，设置 `SUBTITLE_ENGINE_BIN`
指向完整可执行文件。

## 打包与发布

1. 构建 sidecar（Nuitka onefile，失败自动回退 PyInstaller onefile）：

   ```powershell
   .\scripts\build-engine.ps1
   ```

   产物会按 Rust target triple 复制为
   `apps/desktop/src-tauri/binaries/subtitle-engine-x86_64-pc-windows-msvc.exe`。

2. 构建安装包（预发布版本只打 NSIS；稳定版默认 MSI + NSIS）：

   ```powershell
   cd apps/desktop
   npm run tauri build -- --bundles nsis
   ```

3. 生成免安装 ZIP：

   ```powershell
   # 仓库根目录
   .\scripts\package-portable.ps1
   ```

   产物：`apps/desktop/src-tauri/target/release/bundle/portable/subtitle-process_<version>_x64-portable.zip`，
   内含 `subtitle-desktop.exe`、`subtitle-engine.exe` 与 `README.txt`。
   NSIS 安装包会重命名为 ASCII 的 `subtitle-process_<version>_x64-setup.exe`，避免 GitHub Release 丢弃中文字符。

4. 自动更新：`tauri.conf.json` 的 `plugins.updater` 已预留 endpoints 与 pubkey 占位，
   发布前用 `tauri signer generate` 生成密钥并替换公钥，同时开启
   `bundle.createUpdaterArtifacts`。单实例与引擎崩溃恢复由 `tauri-plugin-single-instance`
   与 `src-tauri/src/engine/supervisor.rs` 提供。

5. 端到端冒烟：

   ```powershell
   .\scripts\e2e.ps1
   ```

### 版本号来源

引擎与桌面端各保留一个版本号，均只有一处权威来源，其余位置自动派生：

| 位置 | 来源 | 说明 |
|---|---|---|
| Python 引擎 | `engine/src/subtitle_engine/version.py::__version__` | `engine/pyproject.toml` 通过 `[tool.hatch.version]` 读取，不再重复声明 |
| 桌面应用 | `apps/desktop/package.json` 的 `version` | `tauri.conf.json` 的 `version` 指向 `../package.json`；前端构建时由 Vite 注入；打包脚本与 Release 工作流直接读该文件 |

`apps/desktop/src-tauri/Cargo.toml` 的 crate 版本固定为 `0.0.0`，不参与应用版本
（Tauri 以配置文件的 `version` 为准），因此无需随发布号手动同步。

#### 升版与锁文件

1. 桌面端：只改 `apps/desktop/package.json` 的 `version`，然后同步锁文件（禁止手改）：

   ```powershell
   cd apps/desktop
   npm install --package-lock-only      # 刷新 package-lock.json
   cd src-tauri
   cargo check                          # 或 cargo metadata，刷新 Cargo.lock 中的本地 crate 版本
   ```

   `Cargo.toml` 的 crate 版本固定为 `0.0.0`，通常无需改动；只有调整依赖时才由 `cargo` 更新 `Cargo.lock`。

2. 引擎：只改 `engine/src/subtitle_engine/version.py::__version__`，然后刷新 `uv.lock`：

   ```powershell
   cd engine
   uv lock
   ```

3. 提交后按发布流程打标签（如 `v1.0.0-alpha5`）并推送，`.github/workflows/release.yml` 会用
   `package.json` 的版本生成安装包。

## 数据目录

Windows 为 `%APPDATA%/SubtitleProcess`，包含：

```
projects/<project_id>/   # 每个项目的工作区（source/extracted/clean/output/reviews/logs）
recipes/                 # 用户自定义配方
store.db                 # 项目、运行、产物、审核、设置（SQLite）
artifacts/<sha256>/      # 内容寻址产物
```

## 持续集成与发布

| Workflow | 触发 | 内容 |
|---|---|---|
| `.github/workflows/ci.yml` | push / PR 到 `master`、`main` | 引擎 `ruff` + `pytest`、前端 `vitest` + `tsc && vite build`、Rust `cargo check`；push 时额外构建并上传 Windows 安装包 + 免安装 ZIP |
| `.github/workflows/release.yml` | 推送 `v*` 标签 / 手动 | 构建 Python sidecar → Tauri 安装包 + 免安装 ZIP → 附加到 GitHub Release |

CI 成功后可在该次 run 的 **Artifacts** 下载 `subtitle-process-windows-<sha>`，包含 NSIS 安装包和 portable ZIP。

预发布版本（`-alpha` / `-beta` / `-rc`）只生成 NSIS 安装包，因为 WiX/MSI 要求 prerelease 为纯数字；稳定版会同时生成 MSI 与 NSIS。发布前把 Tauri updater 私钥放到仓库 Secrets：`TAURI_SIGNING_PRIVATE_KEY`、
`TAURI_SIGNING_PRIVATE_KEY_PASSWORD`。未配置时 CI 会自动关闭 updater 签名产物并给出警告，
普通安装包仍会照常构建。配置步骤见 `apps/desktop/src-tauri/UPDATER.md`。

## 许可证

MIT License

# 更新日志

所有针对当前软件功能和 UI 界面的重要更改都会记录在此文件中。

## Unreleased — Pipeline v2

### M3 项目与配方

#### 新增
- **项目工作区与状态机**：`core/projects.py` 提供 `ProjectManager`，按 `<data_dir>/projects/<prj_id>/` 创建 `source / extracted / clean / translated / output / artifacts / reviews / logs`；项目元数据（媒体引用、fingerprint、语言对、run 历史、导出产物、状态）持久化到 SQLite `projects` 表。运行结束自动归档 `output/` 产物，`video_to_clean_srt` 成功后置为 `waiting_translation`，`translated_to_bilingual` 成功后置为 `done`，失败为 `failed`。
- **配方库**：`core/recipe_library.py` + 4 个内置只读配方（`video_to_clean_srt`、`translated_to_bilingual`、`batch_normalize`、`batch_shift_fps`）；用户配方存 `<data_dir>/recipes/<id>.json`，内置配方禁止覆盖/删除。M7 步骤（`sub.match_project` / `sub.merge_bilingual` / `sub.fps_convert`）与 `translate.linguagacha` 先提供端口/Schema 占位，执行时返回带 `milestone` 的明确错误。
- **`pipeline.validate`**：`core/validation.py` 校验步骤 id 唯一、依赖存在、无环、未知实现、Options Schema、端口类型兼容、必填输入、when 表达式、导出目录不得越出工作区、导出文件名/路径冲突、配方输出端口与输入名重复；`pipeline.run` 启动前复用同一套规则，失败返回 `1001` + 完整报告。
- **RPC 扩展**：`recipes.list/get/save/delete`、`pipeline.validate`、`project.create/list/get/delete`、`artifact.reveal`；`pipeline.run` 支持 `recipe_id`、按项目工作区运行并接受 `project` 上下文；新增 `project.updated` 事件。
- **流程 1 前端**：拖入视频 → 创建项目 → 校验并运行 `video_to_clean_srt`；新增「最近项目」列表（重启后从 SQLite 恢复）与交接卡片（最新产物、打开所在文件夹、复制路径、提示拖回译文）。`runStore` 按 `run_id` 过滤迟到事件。
- **测试**：新增项目 CRUD/状态机/删除清理、配方库只读与校验、`pipeline.validate` 规则、真实 MKV 的流程 1 端到端与引擎重启持久化测试。引擎测试增至 **164 个**，全部通过；前端 `tsc && vite build` 通过。

### M2 领域步骤

#### 新增
- **领域层（纯函数）**：`domain/clean.py` 移植 `tools/srt_process.py` + `tools/chs_srt_format.py` 的清理、短句/相同行合并与中文标点规范化；`domain/srt.py` 提供宽容解析与 LF 序列化；`domain/media.py` 移植 ffprobe 解析、MKV 补充、默认轨道选择与输出命名；`domain/paths.py` 移植 Windows 长路径/8.3 短路径处理；`domain/validate.py` 新增时间轴倒挂/重叠、空文本、时长、CPS、行宽校验并输出结构化报告。
- **媒体步骤**：`media.probe`（ffprobe，MKV 编码未知时 mkvmerge -J 补充）与 `media.extract_subtitles`（ffmpeg / mkvextract 双路径，保留 VTT→SRT 转换与进度解析）。
- **字幕步骤**：`sub.normalize`（括号/标签/人名提示/大写行/合并开关 + 可选中文标点）、`sub.validate`（warnings 报告，可配置 `fail_on_error`）、`sub.export`（UTF-8 + LF、覆盖前 `.bak`、输出目录可配）。
- **外部依赖错误**：ffmpeg / ffprobe / mkvmerge / mkvextract 缺失统一映射为 `1006`，`data.tool` 与安装提示可直接展示。
- **多产物端口**：Runner / 缓存支持 `multiple: true` 端口返回 Artifact 列表；缓存键纳入列表内所有产物哈希，避免多轨道提取后下游误命中旧缓存。
- **运行输入**：`pipeline.run.inputs` / CLI `--input` 注入步骤上下文，`media.probe` 可直接读取首个输入文件（也可用 `options.source` 覆盖）。

#### 工程改进
- **测试**：新增领域 Golden Test（直接导入旧 `tools/` 函数逐字节对比）、媒体解析/轨道选择/校验单测、真实 ffmpeg 生成的 MKV + MP4 双 fixture 端到端测试（探测→提取→规范→校验→导出，并与旧 `SubtitleExtractor` 输出对比）、mkvextract 分支与 `1006` 错误映射。引擎测试增至 **136 个**，全部通过；`steps.list` 自动暴露 M2 步骤 Schema。
- 旧 `app_ui.py` / `ui/` / `tools/` 保持不变，继续作为迁移对比基准。

### M1 引擎核心

#### 新增
- **持久化与产物存储**：`core/store.py` 提供 SQLite（`PRAGMA user_version` 顺序迁移，v1 建 projects/runs/artifacts/reviews/settings/step_cache 六张表，WAL + 外键）、内容寻址产物（`artifacts/<sha256>/`，临时文件 + `os.replace` 原子写入，同哈希复用）、Run 持久化与 settings/cache KV。
- **步骤缓存**：`core/cache.py` 按 TASKBOOK §10.2 计算缓存键（step_id + 引擎版本 + canonical JSON options + 排序后的输入产物哈希），命中前校验产物存在且哈希一致；负载损坏或产物被手改会自动失效并清理。
- **Runner 完整化**：`graphlib.TopologicalSorter` 拓扑排序与环检测、依赖端口按 kind 注入、`when: ${options.x}` 条件跳过（不支持的表达式显式报错）、可重试错误重试（默认 1 次，仅超时/连接/临时占用类）、`continue_on_error` 只跳过下游、同项目互斥（`1004`）、全局并行上限（默认 2，超出的 run 排队）。
- **子进程管理**：`core/processes.py` 统一登记步骤启动的子进程，取消/失败/退出时用 `taskkill /T /F` 清理整棵进程树。
- **CLI**：`python -m subtitle_engine run recipes/demo.yaml [--input ...] [--data-dir ...] [--json] [--no-cache] [--continue-on-error]`，事件摘要写 stderr、结果写 stdout；新增 `core/recipes.py`（YAML/JSON 配方加载）与 `recipes/demo.yaml` 三步示例。
- **演示步骤**：`demo.generate` / `demo.transform` / `demo.consume`，均为确定性文本步骤，用于验证依赖、产物与跨进程缓存。

#### 工程改进
- **Server**：`pipeline.run` 支持 `options` / `max_retries` / `continue_on_error` / `no_cache`；`job.status` 增加 `cached` / `attempts`；`RpcServer` 可注入数据目录，退出时关闭 SQLite。
- **测试**：引擎测试增至 **97 个**，覆盖 Store/Cache/Recipe 加载、拓扑与环、when、重试、继续执行、并发排队与项目锁、取消清理子进程、CLI 跨进程缓存；`pipeline.py` 覆盖率 **86%**（要求 >80%）。

### M0 骨架

#### 新增
- **全新架构骨架（`feat/pipeline-v2`）**：在保留旧 CustomTkinter 实现作为参考基准的前提下，新增 Tauri v2 + React 桌面壳与 Python headless 引擎。
    * `engine/`：独立 uv 项目（Python 3.15），提供 JSON-RPC 2.0 over stdio（JSONL）服务，严格保证 `stdout` 只输出协议消息、日志全部走 `stderr`。
    * `apps/desktop/`：Tauri v2 壳 + React 19/TypeScript/Vite/Tailwind，首页支持原生拖拽 / 文件选择，实时展示运行进度与事件日志。
- **引擎 RPC（M0）**：`engine.hello`、`engine.shutdown`、`steps.list`（含 Pydantic 自动生成的 Options JSON Schema）、`pipeline.run`（最小顺序执行器）、`job.status`、`job.cancel`；事件包含 `run.started` / `step.started` / `step.progress` / `step.log` / `step.failed` / `run.finished`，`seq` 单调递增。
- **Rust Supervisor**：spawn sidecar、10s 握手、请求/响应 id 匹配、stdout 事件转发、stderr 日志转发、60s 内最多 3 次崩溃重启、退出时 `engine.shutdown` → 2s 宽限 → `taskkill /T /F` 杀进程树；Windows 下使用 `CREATE_NO_WINDOW`。
- **协议文档**：新增 `docs/pipeline-v2/PROTOCOL.md`（分帧、方法表、错误码、事件、HITL、版本兼容）。

#### 工程改进
- **任务书 v1.1**：按用户决策将引擎 Python 目标由 3.12/3.13 调整为 **3.15**，与根项目统一。
- **测试**：引擎 31 个 pytest（分帧、非法 JSON、未知方法、握手、进度、取消、失败停止下游、子进程 stdout 纯净性），Rust 7 个协议解析单测；`npm run build` 通过。
- **开发环境**：Rust 1.100.0（MSVC）通过 `scoop install rustup-msvc` 安装。

## 0.9.8-beta

### 功能改进
- **双语合并**：
    * **重复片段字体对齐**：当译文与原文存在连续重复的片段（忽略大小写、空白与标点，数字不计入阈值，但会保留在片段内）且非数字字符超过 4 个时，译文中的该片段自动改用原文样式的字体名（`\fn`）渲染，字号、描边、颜色等仍沿用译文样式。

## 0.9.7

### 工程改进
- **升级至 Python 3.15**：`requires-python` 提升至 `>=3.15`，CI (`build.yml` / `release.yml`) 构建环境改用 Python 3.15（内置 Tcl/Tk 9.0）。已验证依赖解析、GUI 启动与 PyInstaller 打包产物在 3.15.2 上正常运行，拖拽（tkdnd）可用。同步精简 `uv.lock`：移除仅 Python < 3.10 需要的 `importlib-metadata` / `zipp` 及对应的版本分支标记。
- **依赖全部升级至最新**：`tkinterdnd2 0.6.2 → 0.7.0`、`pyinstaller 6.22.0 → 6.22.3`、`pyinstaller-hooks-contrib 2026.7 → 2026.10`、`setuptools 84.0.0 → 84.2.1`（`customtkinter 6.0.0`、`packaging 26.3`、`darkdetect 0.8.0` 等已是最新）。已验证 GUI 启动与打包产物的拖拽功能正常。

### 功能改进
- **字幕清理**：
    * **人名识别范围扩展**：优化单单词识别（如 `Ben:`、`Doctor:`、`旁白:`），支持被 `[]` 或 `()` 包裹的说话人提示（如 `[BEN]:`、`(John):`、`[Old Man]:`），优先处理人名以避免括号清除导致冒号残留。
    * **合并相同字幕行**：新增「合并相同字幕行」选项（默认不勾选）。当相邻两行字幕文本完全相同，且前一块结束时间与后一块开始时间间隔在 1 秒以内时，将两块合并为一条（起始时间取前者、结束时间取后者），并在日志中显示 `相同行合并-N` 统计。

### 问题修复
- **打包后拖拽功能失效**：修复使用 Python 3.14（Tcl 9）打包后，程序启动报 `Unable to load tkdnd library` / `this extension is compiled for Tcl 8.x` 的问题。将 `pyinstaller-hooks-contrib` 约束升级至 `>=2026.7`，其在打包时按 Tcl 主版本收集对应的 `win-x64-tcl9` 资源。

## 0.9.6

### 工程改进
- **uv 包管理迁移**：使用 [uv](https://docs.astral.sh/uv/) 替代 `pip` + `requirements.txt` 进行依赖管理，新增 `pyproject.toml` 与 `uv.lock` 锁定依赖版本，支持 `uv sync` 一键创建虚拟环境。
- **CI 迁移至 uv**：GitHub Actions (`build.yml` / `release.yml`) 改用 `astral-sh/setup-uv` + `uv sync` 安装依赖，`pyinstaller` 加入 `dev` 依赖组，打包命令改为 `uv run pyinstaller`。
- **CI 修复 Node 20 弃用警告**：升级 Actions 至基于 Node 24 的版本 (`actions/checkout@v7`, `actions/upload-artifact@v7`, `astral-sh/setup-uv@v9.0.0`)。

### 功能改进
- **路径规范化与短路径自动还原**：
    * **8.3 短路径自动还原**：集成 Windows Kernel32 API 自动检测与还原逻辑，自动将 Windows 自动生成的 DOS 8.3 格式压缩短路径（如 `NOONEW~1.265\NOONEW~3.SRT`）恢复为原始完整长路径。
    * **超长路径安全支持**：针对超过 240 字符的 Windows 超长路径，自动加上 Extended-Length Path 前缀 (`\\?\`)，防止在读写字幕文件时产生 `FileNotFoundError` 或 `PathTooLongException`。
    * **UI 与 API 全流程覆盖**：在文件选择对话框、文件拖放（Drag & Drop）以及所有底层字幕处理 API 入口处均生效，确保界面展示与后台处理时始终使用清晰完整的真实长路径。
- **字幕清理**：
    * **人名清理选项独立**：将人名清理功能独立为“清理人名提示”复选框，并且默认处于勾选状态。
    * **人名处理逻辑改进**：支持识别并清理不在第一排（多行字幕后续行）的人名提示；增强了对人名中空格及各种特殊符号（例如数字、`#`、`.`、`-`、`_`、`&`、`'`、`/`、`,`、`+` 等）的匹配与清理。
- **字幕提取**：仅提取单个字幕轨道时，输出文件不再附加语言/轨道序号后缀（如 `xxx.lang.idx.srt`），直接输出为 `xxx.srt`/`xxx.ass` 等简洁文件名；多轨道提取时保持原命名以区分。

## 0.9.5

### 功能改进
- **双语合并 (全新重构)**：
    * **智能路径特征识别**：支持根据文件名后缀 (如 `xxx.zh.srt`) 或父级路径特征 (如 `/zh/`, `/xxx_zh/`) 进行译文匹配，支持排除相同前缀仅匹配后缀，并自动根据同路径/异路径关系输出至对应的 `merge` 目录下。
    * **冲突与异常检测**：支持多重匹配冲突检测，将冲突与未匹配字幕置顶并标红，提供一键删除单个文件的选项。
    * **可视化拖拽与列表**：提供双栏对照列表与更直观的拖放区域，对于路径匹配的译文字幕在列表中显示为 `特征/文件名` (如 `zh/filename`)，长文件名支持中段截断。
    * **选择文件/文件夹**：选择按钮支持弹窗自由选择导入单个/多个字幕文件或整个文件夹。
    * **界面优化**：固化输出后缀为 `.ass`，选择按钮改进。
- **清理与格式化**：
    * **大写行与控制符清理**：新增大写行清理功能，可通过复选框勾选开启。支持在合并前逐行识别并剥离去除无标点的纯大写英文噪声行。
    * **日志统计改进**：在输出的日志及状态消息中支持大写行的过滤统计显示。

## 0.9.4

### 功能改进
- **重命名字幕**：
    * 支持 `SxxExx`, `01x01`, `TxxCxx` 等格式
    * 新增自定义后缀功能
    * 优化匹配到多个同格式字幕时的处理逻辑
- **双语合并**：支持模糊时间轴匹配
- **ASS 描边缩放**：添加目标分辨率选择，支持手动输入，以目标分辨率计算固定描边

## 0.9.3

### 新功能
- **帧率转换：** 新增字幕帧率转换功能，支持在各大常见帧率间互转（如 23.976 <-> 25），自动重算并在新旧帧率间同步时间轴。
- **时间轴平移：** 新增时间轴平移功能，支持输入秒数进行时间轴平移（正数延后，负数提前，源文件将被备份为 .bak）。

### 功能改进
- **双语合并：** 重构双语字幕合并功能并在 UI 中剥离原来堆叠的过长参数。新增独立的高级样式设置窗口，支持自定义两种语言的 ASS 字幕样式参数，并支持设置全局输出分辨率 (`PlayResX`/`PlayResY`)。修改配置时会自动保存至 `config.json` 并在下次启动时无缝加载。
- **格式支持 (WebVTT)：** 现支持在字幕提取时识别 `webvtt` 轨道并为其提供内置的“转为SRT”勾选转换选项。
- **清理与格式化：** 允许在“清理 SRT”功能中输入 VTT 字幕，自动调用 ffmpeg 将其转换为 SRT 后再处理。

### 移除
- **术语合并：** 移除了“术语合并”相关的功能、UI 和底层逻辑。

## 0.9.2

### 功能改进
- **字幕处理：** 优化了中文 SRT 字幕的规则格式化操作。
- **拖放响应：** 改进了应用的多文件拖拽解析逻辑，确保能更健壮地识别有效文件路径，并增加了空输入的检测防错处理。

### 界面调整 (UI)
- **提取进度：** 细化了“字幕提取”界面中的处理进度日志显示，提供了更友好的用户反馈。
- **布局整合：** 优化了主界面基础框架，使用网格布局（Grid）整合了各项功能的按钮与拖放区域，并将“跳过合并”复选项内置到对应处理区以节省空间。

---

## 0.9.1

### 功能改进
- **字幕提取 (MKV)：** 新增对未知/异常字幕流编码的 Fallback（回落）支持，自动调用 `mkvmerge` 与 `mkvextract` 接管底层的解析及提取。

---

## 0.9.0

### 功能改进
- **核心功能提取：** 首次推出针对 MP4 / MKV 视频的内部独立字幕流解析与提取功能。
- **批量处理：** 全面支持各类文本以及多文件的批量式拖拽合并，并改进了合并执行时的日志描述。
- **程序版本识别：** 引入内置的版本控制机制，并在窗口标题栏实时提供当前版本信息展示。

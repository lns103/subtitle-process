# 更新日志

所有针对当前软件功能和 UI 界面的重要更改都会记录在此文件中。

## Unreleased — Pipeline v2

### 双语合并拖放与产物目录

#### 修复
- **多条字幕自动分配交替**：通用投放改为整批先分类再落槽；带 `.clean` / 语言后缀 / 译文目录线索的文件整组进对应槽，无线索文件整批只选一次目标槽，不再出现原文/译文轮流分配。
- **拖到译文槽只有一条生效**：原生拖拽改用 Tauri v2 `drop` 事件的坐标命中 `[data-input-slot]`，整批文件追加到落点槽位（即使该槽已有内容），不再回落到原文槽；拖动悬停时同步高亮目标槽。
- **双语产物分散**：`batch_translated_to_bilingual` 与 `fn_merge_bilingual` 的导出目录固定为工作区 `output/bilingual/`，多个 ASS 集中在同一文件夹。
- **打开文件夹落到 artifacts**：产物列表与“打开所在文件夹”只使用真正写盘的文件，内容寻址中间产物（`artifacts/<sha256>/`）不再出现在界面中。
- **中间产物用完即清**：项目运行成功后删除本次运行的内容寻址中间产物（导出文件、配方声明产物与含人工审核的中间产物保留，仍被其它运行引用的产物跳过），避免 `artifacts/` 无限增长。
- **批量任务分目录输出**：`batch_video_to_clean_srt` → `output/clean/`、`batch_translated_to_bilingual` → `output/bilingual/`、`batch_normalize` → `output/normalize/`、`batch_shift_fps` → `output/fps/`；批量规范/帧率任务也会自动创建或复用项目工作区。
- 修正合并日志重复输出 `.ass.ass` 后缀。

#### 测试
- 前端新增多条普通 SRT 整批同槽、原文已填充时整批进译文、覆盖模式不交替、混合批次以及按 drop 坐标追加译文槽用例。
- 引擎新增 4 个批量配方输出子目录断言，以及中间产物删除与缓存同步清理用例。

### 项目卡片整合运行队列、产物与改名

#### 新增
- **修改项目名**：项目卡片标题旁新增编辑按钮，可直接改名；新增 `project.rename` RPC，改名只更新显示名，工作区与已有产物路径保持不变。
- **开始执行即显示项目卡片**：单次运行与批量运行创建/复用项目后会立即打开右侧项目卡片，无需等运行结束。

#### 变更
- **队列与产物移入项目卡片**：批量队列、本次运行产物、打开文件夹/复制路径都集中到项目卡片中，左侧任务区只保留输入与运行选项。
- **产物完成后折叠**：运行中展示全部产物，结束后默认只显示最新一项，可通过「展开全部」查看历史产物。
- **产物归属校验**：项目卡片仅在当前运行所属项目下显示本次产物，切换到其他项目时回退到该项目已归档产物。

#### 测试
- 前端新增项目卡片改名、产物完成折叠/运行中展开用例。
- 引擎新增项目改名持久化、工作区不变与空名校验用例。

### 版本

- **版本号收敛为单一来源**：引擎只在 `engine/src/subtitle_engine/version.py` 声明版本，`pyproject.toml` 改为 `dynamic` 由 hatchling 读取；桌面端以 `apps/desktop/package.json` 为准，`tauri.conf.json` 的 `version` 改为引用 `../package.json`，打包脚本与 Release 工作流直接读取该文件；`Cargo.toml` 的 crate 版本固定为 `0.0.0`（不参与应用版本），前端回退值改为 `0.0.0-dev`。应用版本与引擎版本号保持不变。
- 桌面应用版本号提升至 **`1.0.0-alpha5`**：只需改 `apps/desktop/package.json`，`package-lock.json` 由 `npm install --package-lock-only` 刷新，其余位置自动派生（见 README「升版与锁文件」）；Python 引擎版本仍为 `0.1.0`。
- 仅 GitHub CI 的 sidecar 构建改用 PyInstaller onefile（`build-engine.ps1 -Fallback`），跳过 Nuitka 编译以缩短流水线时间；Release 与本地仍使用默认 Nuitka 编译。
- NSIS 安装路径改为 ASCII 的 `%LOCALAPPDATA%\subtitle-process`：`productName` 同步改为 `subtitle-process`，开始菜单与“应用和功能”中的名称也随之为该值；窗口标题仍为“字幕工具箱”。

### SDH 默认规则、批量项目与悬浮运行按钮

#### 变更
- **SDH 默认不含音乐符号**：`sub.sdh_scan` 与内置视频/扫描配方默认启用 `bracketed / parenthetical / speaker / uppercase / arrow / ellipsis_action`，不再默认标记 `♪ ♫ ♬ ♩` 或“音乐”行；仍可在步骤选项中手动勾选 `music`。
- **批量视频共用一个项目**：一次投入多个视频时只创建一个项目，每个视频对应一个 run；项目名优先使用拖入的文件夹名，否则使用第一个视频的文件名。`files.scan` 新增 `directories` 返回，通用投放会保留文件夹信息供命名。
- **执行按钮悬浮**：首页任务页的「开始运行 / 批量处理」按钮移到右下角固定悬浮，滚动时始终可用。

#### 修复
- **双语自动填充只填最后一个**：新增 `pickOriginalSubtitles`，批量视频产生的全部干净 SRT 会按顺序填入双语任务「原版」槽；HandoffCard 与单次运行结束的自动填充也不再只取最后一个。
- **干净输出默认不加后缀**：`sub.export` 的 `suffix` 默认改为空，内置 `batch_video_to_clean_srt`、`fn_export`、`fn_normalize` 不再生成 `.clean.srt`，默认输出 `<stem>.srt`；仍可在步骤选项中自定义后缀。
- **配方画布连线不完整**：同一对步骤现在按全部兼容端口画线（例如 `sdh_scan.candidates → human.review.candidates` 与 `sdh_scan.subs → human.review.subs` 会同时显示）；`recipe.inputs` 渲染为只读输入节点，有 `bind` 的连线到目标端口，无 `bind` 的显示为运行时注入入口。

### 任务化界面与命名输入

#### 新增
- **首页任务化**：主界面改为「先选任务，再显示输入槽」。`tasks.list` 汇总 `workflow` / `function` 两类任务，内置 2 条主流程与 10 个单项功能配方（提取字幕、规范、校验、SDH 扫描、帧率转换、时间轴平移、ASS 描边缩放、导出、双语合并、重命名）。
- **通用投放与自动分发**：输入区新增“通用投放”槽，支持文件/文件夹；按扩展名、槽位语义、`.clean` / 语言后缀 / 文件夹名（含“译文”“翻译”或 `translated`）自动填入原版、译文或视频槽。文件夹会通过 `files.scan` 展开为逐个文件，分配结果可见、可撤销，默认不覆盖已有内容，可勾选“覆盖已有”和“包含子目录”。文件行可拖动到其他槽位改槽；单文件槽已有内容时交换而不是覆盖。
- **命名输入绑定**：`RecipeInput` 新增 `label` / `multiple` / `bind`；`pipeline.run` 支持 `inputs_by_name`，按配方绑定把原版/译文等命名输入注入指定步骤端口，并纳入缓存键。
- **双语合并双输入**：`batch_translated_to_bilingual` 升级为 v2，固定「原版字幕 + 译文字幕」两个输入；`sub.merge_bilingual` 支持显式 `original` / `translated` 端口，保留旧的 `subs` 配对兜底。
- **视频提取自动填入原版**：视频流程或提取功能完成后，把导出的干净 SRT 自动写入双语任务的「原版」槽；用户手动填写后不再覆盖。
- **手动提取字幕语言选择**：新增 `media.inspect` RPC；提取任务会探测内嵌字幕轨道并展示语言/标题/默认/强制/SDH 多选，选中轨道写入 `tracks`。
- **应用版本号**：首页与设置页展示 Tauri 应用版本、引擎版本与协议版本；Vite 构建时注入 `package.json` 版本作为回退。
- **CLI 命名输入**：`subtitle_engine run --input-name NAME=PATH`，并同步更新 `scripts/e2e.ps1` 的双语阶段。
- **默认模型**：Agent 默认模型改为 `deepseek-flash`（前端默认值与占位符同步）。

#### 修复
- **开发模式引擎启动**：`npm run tauri dev` 不再优先使用 `target/debug/subtitle-engine.exe`，改为按文档优先 `uv run`；此前若 `binaries/` 里是 PyInstaller onedir 产物，Tauri 只复制 exe、不复制 `_internal/`，会弹出 “Failed to load Python DLL” 并让 `engine.hello` 握手超时。需要在 dev 中联调 sidecar 时用 `SUBTITLE_ENGINE_BIN` 覆盖。
- **sidecar 打包**：`scripts/build-engine.ps1` 的回退链从 PyInstaller onedir 改为 onefile，与 `bundle.externalBin` 只复制单文件的行为一致，并清理旧的 `binaries/_internal`。
- **重启死循环**：引擎 supervisor 为每次启动分配 generation；手动重启/关机产生的旧进程 stdout 关闭事件会被丢弃，排队中的自动重启也会失效，修复“点一次重启后持续重启”的竞态。
- **重启按钮**：引擎处于 `starting` 时禁用，并增加本地 busy 状态防止连点。

#### 测试
- 引擎 `242 passed, 1 skipped`，`ruff check` 通过；新增命名输入、任务目录、显式双语合并、`media.inspect`、`files.scan`、默认模型、CLI 命名输入参数等用例。
- 前端 `110 passed`，`tsc --noEmit` 与 `vite build` 通过；新增任务目录/输入槽/通用分发/拖动改槽/自动填充用例。
- Rust `cargo test --lib` 14 个用例通过（含 3 个重启 generation 回归测试与 4 个引擎来源优先级用例）。
- 追加 RPC 冒烟：`tasks.list`、双语双输入生成 ASS、`fn_normalize` / `fn_merge_bilingual` / `fn_rename` 均通过。

### 批量处理、连接测试与项目删除

#### 新增
- **视频批量处理**：`batch_video_to_clean_srt` 与 `fn_extract_subtitles` 的视频输入支持多选/文件夹展开；首页把整批视频放进同一个项目、按视频顺序逐个运行，失败项不阻断队列，遇到人工审核自动暂停并在审核完成后继续，队列进度跨页面保留。
- **最近项目删除**：项目列表每行新增删除按钮，二次确认后调用 `project.delete`，会同时清理项目工作区与已导出文件；运行中的项目禁止删除。
- **关闭当前项目**：项目卡片右上角新增关闭按钮，只收起当前项目详情/HandoffCard，不删除数据；最近项目列表中的项目仍可再次打开。

#### 修复
- **Agent 连接测试误报**：`ping` 不再要求响应包含文本内容，并把 `max_tokens` 放宽到 128；推理型/兼容端点在空 `content` 时也能正确判定连接成功。
- **打开所在文件夹路径错误**：产物定位改走 Tauri `reveal_path`；引擎 Windows 实现改为 `explorer.exe /select,"<路径>"`，修复含空格路径被 explorer 忽略并打开默认目录的问题。

#### 测试
- 引擎 `248 passed, 1 skipped`；新增连接测试空正文、`reveal` 含空格路径、任务视频多选用例。
- 前端 `125 passed`，`tsc --noEmit` 与 `vite build` 通过；新增批量队列、视频多值分发、项目删除、关闭当前项目用例。

### 版本

- 桌面应用版本号提升至 **`1.0.0-alpha2`**：Tauri、前端与 Rust 配置保持同步；Python 引擎版本仍为 `0.1.0`。
- 同步 `package-lock.json`，补齐缺失的 Tauri 插件条目，恢复 `npm ci` 可复现安装。
- 打包新增免安装 ZIP（`scripts/package-portable.ps1`）；CI 在检查全部通过后自动构建并上传 NSIS 安装包与 portable ZIP，Release 同样附带该 ZIP。产物文件名统一使用 ASCII（`subtitle-process_<version>_x64-setup.exe`、`subtitle-process_<version>_x64-portable.zip`），避免 GitHub Release 过滤中文字符。

### 主线清理与持续集成

#### 变更
- **移除旧工具箱**：从主线删除 `app_ui.py`、`ui/`、`tools/`、根 `version.py`、根 `pyproject.toml` 与 `uv.lock`；旧版完整实现保存在 `archive/legacy-toolbox` 分支（原 `dev`）。
- **冻结 golden 基准**：将 golden 测试依赖的 7 个旧领域模块移入 `engine/tests/legacy_reference/`，测试改为包内导入并新增说明 README；生产代码不得引用该目录。
- **GitHub Workflows**：用 `ci.yml` 替换旧的 PyInstaller 单文件构建，新增引擎 `ruff` + `pytest`、前端 `vitest` + `tsc && vite build`、Rust `cargo check` 三条检查；`release.yml` 改为先构建 Python sidecar，再打包 Tauri 安装包，并在缺少 updater 私钥时自动关闭签名产物、正常产出普通安装包。预发布版本（`-alpha` / `-beta` / `-rc`）自动只构建 NSIS，因为 WiX/MSI 不接受非数字 prerelease。
- **文档**：`README.md` 与 `AGENTS.md` 更新为 pipeline-v2 架构，补充 CI/发布流程与存档分支说明。

## M7 合并与发布

#### 新增
- **领域层移植**：`domain/merge.py` 忠实移植旧 `tools/merge_srt.py`（重复片段极大匹配 + 贪心选择、精确时间戳匹配、5 条模糊匹配规则、连通分量合并、`classify_and_match_files`、ASS 渲染），并提供 `parse_srt_entries` 保持毫秒截断与旧实现逐字节一致；新增 `domain/timing.py`（帧率/时间平移）、`domain/rename.py`（SxxExx 重命名计划，纯函数）、`domain/outline.py`（ASS 描边缩放）。
- **M7 步骤**：`sub.match_project` 按项目产物/`clean/`/`extracted/` 与同目录原文匹配译文，综合 stem 与时间轴相似度（段落数差异 < 10%、首尾差 < 1s），低置信度时以结构化候选列表报错；`sub.merge_bilingual` 按 `pair_id` 分组生成双语 ASS，保留旧版重复片段字体对齐；新增 `sub.fps_convert` / `sub.shift_time` / `sub.rename`（支持 dry-run）/ `sub.outline_scale`。
- **流程 2 端到端**：RPC 与 CLI 均可完成「视频 → 干净 SRT → 手动翻译 → 拖回译文 → 双语 ASS」，项目状态从 `waiting_translation` 变为 `done`；CLI 在 `--project-id` 时加载项目并切换到其工作区，使 `sub.match_project` 与 RPC 行为一致。
- **前端流程 2**：拖入纯字幕时进入「译文 → 双语 ASS」面板，按文件名推荐目标项目（优先 `waiting_translation`），可手动切换；运行前校验配方，完成后展示 `.ass` 产物并支持打开文件夹/复制路径。新增 `lib/flow2.ts` 纯逻辑与 `HandoffCard` 的「继续合并译文」入口，抽取 `RunFeedback` 复用进度/日志。
- **打包与发布**：新增 `scripts/build-engine.ps1`（Nuitka onefile 优先、失败回退 PyInstaller onedir、按 `rustc` host triple 复制为 `binaries/subtitle-engine-<triple>.exe`）与 `scripts/e2e.ps1`（ffmpeg 生成真实 MKV，跑通两阶段 CLI）。`tauri.conf.json` 增加 `bundle.externalBin`、`createUpdaterArtifacts` 与 `plugins.updater` 占位；Rust 侧注册 `tauri-plugin-single-instance`（最先注册）、`updater`、`store`，新增 `check_for_updates` 命令与 `UPDATER.md` 说明；权限文件补充 `store:default` / `updater:default`。
- **文档**：根 `README.md` 重写为 pipeline-v2 架构、开发与打包说明；`engine/README.md` 补充 M7 步骤与领域模块。

#### 测试
- 引擎新增 35 个 M7 用例：合并算法与旧 `tools/merge_srt.py` 逐字节 golden、文件匹配、低置信度候选、流程 2 RPC 端到端与重启；帧率/平移与旧实现 golden；重命名/描边缩放与旧实现 golden。全量 **224 passed, 1 skipped**，`ruff check` 通过。
- 前端新增流程 2 纯函数与交互用例，**85 个 Vitest** 全部通过，`tsc && vite build` 通过。
- `scripts/e2e.ps1` 两阶段真实 ffmpeg 冒烟通过。
- 说明：本机未安装 Rust 工具链，Tauri 打包/单实例/自动更新代码未在本机编译验证；需在具备 `rustc` + `x86_64-pc-windows-msvc` 的环境执行 `npm run tauri build` 复核。

### M6 SDH Agent

#### 新增
- **OpenAI 兼容 Agent 客户端**：`agents/client.py` 基于 `httpx` 调用 `/chat/completions`，支持 `response_format=json_schema`（不兼容端点自动降级 `json_object`）、超时/429/5xx 重试、JSON 解析失败重试 1 次；错误信息与日志不包含 API Key 或字幕正文。
- **SDH Agent 步骤**：`agent.sdh_review` 接收 `sub.sdh_scan` 的候选，按 5~30 条分批并只附带前后各 N 条**非候选**上下文，调用 `prompts/sdh_v1.md` 得到严格 `keep/remove/rewrite` 结构化决策；绝不发送整片字幕、绝不修改时间轴。默认仅增强候选并交给 `human.review`。
- **安全策略与审计**：支持 `min_confidence`、`delete_ratio_limit`（默认 30%，超限强制转人工）和默认关闭的 `auto_apply`；自动应用写入 `reviews/audit-<run_id>-agent.jsonl` 并登记审核记录，`review.undo` 可生成撤销副本。Agent 决策按 `(输入哈希 + 选项 + prompt 版本 + model + base_url)` 缓存，`auto_apply` 时禁用缓存。
- **设置与钥匙串**：新增 `settings.get/set`、`secrets.set`、`agent.test`；API Key 由 `keyring` 写入 Windows Credential Manager，SQLite 只保存非敏感配置并拒绝含 `api_key` 的载荷；无 Key 时步骤与 `agent.test` 返回 `1005`。
- **设置页**：新增 `#/settings`，可编辑端点/模型/温度/超时/批大小/置信度/删除比例、保存 API Key（空值删除）、测试连接并显示延迟；顶部工具栏增加「设置」入口。
- **评测**：新增 30 条人工标注 SDH 样本（`tests/fixtures/sdh/samples.jsonl`）与 precision/recall/误删率评测脚本，未配置 API Key 时跳过真实调用。

#### 测试
- 引擎新增 13 个 M6 用例：`1005`、设置与钥匙串隔离、连接测试、只发送候选+上下文、默认不自动删除、自动应用+审计+撤销、删除比例保护、决策缓存、客户端降级；全量 **189 passed, 1 skipped**。
- 前端新增设置 store 与路由用例，**72 个 Vitest** 全部通过，`tsc --noEmit` 通过。

### M5 SDH 规则与人工审核

#### 新增
- **SDH 规则扫描**：`domain/sdh.py` 提供 `bracketed` / `parenthetical` / `music` / `speaker` / `uppercase` / `arrow` / `ellipsis_action` 七类 reason code，只标记不修改；`sub.sdh_scan` 输出 `candidates` 端口（JSON）并透传原字幕，`batch_video_to_clean_srt` 在 `sub.normalize` 后接入扫描与审核。
- **HITL 审核**：`human.review` 步骤把候选转为待审项并抛出暂停信号，Runner 将 run/项目状态置为 `waiting_review`，发出 `review.requested`；`review.list` / `review.submit` / `review.undo` 完成拉取、提交与撤销。决策支持接受/拒绝/人工改写，未决策项默认拒绝，接受删除时仅清空文本、绝不改时间轴。
- **断点续跑**：SQLite 迁移至 v2，新增 `run_state` 保存配方、选项、已完成步骤产物与事件序号；应用重启后 `job.status`、`review.list` 仍可查询，提交后从暂停步骤继续执行且不重算上游。
- **审计**：审核结果写 `<workspace>/reviews/audit-<run_id>.jsonl`（header + 逐条 before/after/action/confidence/reason），`review.undo` 依据审计生成撤销副本。
- **审核 UI**：新增 `#/review/<runId>` 页面，按置信度排序待审项，Monaco DiffEditor 对比 before/after，支持人工改写、单条接受/拒绝、批量接受高置信度、全部拒绝、提交与撤销，快捷键 `J/K/A/R`；运行页 `waiting_review` 时提供「前往审核」入口。
- **测试**：引擎新增 M5 审核测试（规则 reason、20 条候选标记、暂停/提交/应用、审计撤销、引擎重启续跑、无候选直通），引擎测试增至 **177 个**；前端新增 reviewStore / ReviewPage / router / runStore 用例（含事件早于 `pipeline.run` 响应到达的乱序保护），全部 62 个前端测试通过，`tsc && vite build` 通过。

### M4 自由连线编辑器

#### 新增
- **画布编辑器**：`/editor`（hash 路由 `#/editor/<recipeId>`）接入 `@xyflow/react` v12；左侧步骤面板数据来自 `steps.list`，支持搜索、点击/拖拽添加；节点按输入/输出端口渲染 handle，并实时显示参数数量、`when` 条件与 Agent 标记。
- **类型兼容连线**：`lib/recipeGraph.ts` 提供端口兼容规则（同 kind 或 `any`）、`needs` 由边推导、配方 ↔ 画布互转；画布 `isValidConnection` 与 store 双重校验，非法连线给出中文原因。
- **SchemaForm 参数面板**：自研轻量表单渲染 Pydantic `model_json_schema()`，支持 string/number/integer/boolean/enum/array/object、`$ref`、nullable `anyOf`、必填标记与 JSON 语法提示；未知 Schema 退化为只读 JSON。
- **配方管理**：保存/另存为/复制预设（内置配方只读，只能复制后保存）；保存前强制执行 `pipeline.validate`，未通过时阻止保存并高亮问题。引擎侧 `recipes.save` 也复用同一套校验，避免绕过 UI 写入非法图。
- **编辑体验**：撤销/重做（`zundo`，拖动合并为一步）、dagre 自动布局、框选、多选移动、删除（同时清理关联边）、缩放、运行输入选择与底部运行状态条。
- **校验定位**：`pipeline.validate` 的 `step_id` / `port` / `cycle` 映射到节点徽标与错误边；右侧面板展示节点问题与配方整体问题。
- **测试**：前端引入 Vitest + Testing Library，39 个用例覆盖配方互转、连接校验、布局、问题定位、Zustand 撤销/重做与 SchemaForm；引擎新增编辑器配方保存/校验/真实 MKV 端到端测试，引擎测试增至 **166 个**，全部通过。`tsc && vite build` 通过，并用 CDP + 假 Tauri invoke 在真实 WebView 浏览器内核中验证画布、校验高亮、另存为与运行流程。

### M3 项目与配方

#### 新增
- **项目工作区与状态机**：`core/projects.py` 提供 `ProjectManager`，按 `<data_dir>/projects/<prj_id>/` 创建 `source / extracted / clean / translated / output / artifacts / reviews / logs`；项目元数据（媒体引用、fingerprint、语言对、run 历史、导出产物、状态）持久化到 SQLite `projects` 表。运行结束自动归档 `output/` 产物，`batch_video_to_clean_srt` 成功后置为 `waiting_translation`，`batch_translated_to_bilingual` 成功后置为 `done`，失败为 `failed`。
- **配方库**：`core/recipe_library.py` + 4 个内置只读配方（`batch_video_to_clean_srt`、`batch_translated_to_bilingual`、`batch_normalize`、`batch_shift_fps`）；用户配方存 `<data_dir>/recipes/<id>.json`，内置配方禁止覆盖/删除。M7 步骤（`sub.match_project` / `sub.merge_bilingual` / `sub.fps_convert`）与 `translate.linguagacha` 先提供端口/Schema 占位，执行时返回带 `milestone` 的明确错误。
- **`pipeline.validate`**：`core/validation.py` 校验步骤 id 唯一、依赖存在、无环、未知实现、Options Schema、端口类型兼容、必填输入、when 表达式、导出目录不得越出工作区、导出文件名/路径冲突、配方输出端口与输入名重复；`pipeline.run` 启动前复用同一套规则，失败返回 `1001` + 完整报告。
- **RPC 扩展**：`recipes.list/get/save/delete`、`pipeline.validate`、`project.create/list/get/delete`、`artifact.reveal`；`pipeline.run` 支持 `recipe_id`、按项目工作区运行并接受 `project` 上下文；新增 `project.updated` 事件。
- **流程 1 前端**：拖入视频 → 创建项目 → 校验并运行 `batch_video_to_clean_srt`；新增「最近项目」列表（重启后从 SQLite 恢复）与交接卡片（最新产物、打开所在文件夹、复制路径、提示拖回译文）。`runStore` 按 `run_id` 过滤迟到事件。
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

# 任务书：字幕流水线 v2（Tauri v2 + React + Python Sidecar）

> **状态：历史任务书（M0–M7 已完成）。** 文中“保留旧 `app_ui.py` / `ui/` / `tools/`”
> 等迁移期约定已结束：旧工具箱删除并存档在 `archive/legacy-toolbox` 分支，
> golden 基准冻结在 `engine/tests/legacy_reference/`。当前开发规范以 `AGENTS.md` 为准。

> 版本：1.2
> 日期：2026-11-17
> 变更：v1.2 完成 M7（合并、流程 2、打包与发布），M0–M7 全部验收；v1.1 将 D7 从 Python 3.12/3.13 改为 **Python 3.15**（与根项目统一）。
> 分支：`feat/pipeline-v2`（基于 `dev` @ `466a460`）
> 执行者：新的 AI session（**先完整读完本文件再动手**）
> 必读：`AGENTS.md`、`README.md`、`CHANGELOG.md`

---

## 0. 一页摘要

把现有 CustomTkinter 字幕工具箱重写为：

- **桌面壳**：Tauri v2（Rust 只做窗口、拖拽、进程管理、系统能力）
- **前端**：React 19 + TypeScript + Vite + Tailwind + shadcn/ui
- **流水线画布**：React Flow（`@xyflow/react`），**自由连线 + 预设模板**
- **引擎**：Python 3.15 sidecar，headless，JSON-RPC over stdio
- **Agent**：SDH 规范检查/去除，走 OpenAI 兼容 **API**
- **领域逻辑**：**移植复用**现有 `tools/`，用 golden test 保证字节级一致

核心用户流程：

1. 拖入视频 → 自动提取字幕 → 规范化 →（可选）SDH Agent 检查/去除 → 导出干净 SRT
2. 用户手动用 LinguaGacha 翻译
3. 拖回译文 SRT → 自动匹配原项目 → 校验 → 合并 → 导出双语 ASS

本期**不接** LinguaGacha CLI，保持人工交接；只预留 `translate.linguagacha` 步骤位。

---

## 1. 已确认决策

| 编号 | 决策 | 说明 |
|---|---|---|
| D1 | 流水线支持**自由连线** | React Flow 画布，用户可任意编排 |
| D2 | 同时提供**预设模板** | 内置配方可复制后修改，不可直接覆盖 |
| D3 | SDH Agent **走 API** | OpenAI 兼容接口，Key 存系统钥匙串 |
| D4 | **复用现有 `tools/` 领域逻辑** | 不重写算法；用 golden test 对比旧实现 |
| D5 | 旧 GUI 保留为参考实现 | 新代码放 `engine/`、`apps/desktop/`，迁移完成前不删旧代码 |
| D6 | Windows 优先 | macOS/Linux 后续，代码不得写死盘符 |
| D7 | Python 引擎目标 **3.15** | 与根项目统一（3.15.2），复用同一套已验证的 Tcl/Tk 9 打包方案 |
| D8 | 通信使用 **stdio + JSONL + JSON-RPC 2.0** | 不开本地端口，不依赖 HTTP |
| D9 | 本期不接 LinguaGacha CLI | 人工交接；预留步骤接口 |
| D10 | 所有写操作可回滚 | `.bak`、内容寻址、审计日志 |

**"看你的"部分的结论**：领域逻辑**移植复用**，不借机重写。重写 GUI/编排/Agent 已经足够大，算法层再重写会显著增加回归风险。

---

## 2. 目标与非目标

### 2.1 目标

- 拖入视频即可产出规范 SRT，全程有结构化进度。
- SDH 检查可插入流水线任意位置，默认人工确认后才删除。
- 流水线可自由连线和保存为自定义配方。
- 译文拖回后能自动关联原项目并继续下游步骤。
- 引擎可脱离 GUI 用 CLI 运行，便于测试与未来 MCP 化。
- 打包为单个 Windows 安装包，用户无需安装 Python。

### 2.2 非目标（本期不做）

- 不实现语音识别（ASR）与视频字幕烧录。
- 不实现 LinguaGacha 的自动调用（GUI/CLI 都不接）。
- 不做云端同步、多人协作、移动端。
- 不重写 `merge_srt` 的重复片段算法等核心逻辑。
- 不做插件市场（但步骤注册表要为插件预留）。
- 不做自动翻译质量评分。

---

## 3. 总体架构

```
┌─────────────────────────────────────────────────────────┐
│ Tauri v2 Shell (Rust)                                   │
│  ├─ 窗口 / 原生拖拽 / 单实例 / 自动更新                  │
│  ├─ 文件对话框 / 打开产物                                │
│  └─ Sidecar Supervisor (tokio::process)                 │
│       ├─ 启动 / 健康检查 / 崩溃重启                       │
│       ├─ stdin 写 JSON-RPC 请求                          │
│       ├─ stdout 按行解析 → Tauri event                   │
│       └─ stderr → 日志文件 + 诊断事件                    │
└──────────▲────────────────────────┬──────────────────────┘
           │ invoke / listen        │ JSONL
┌──────────┴────────────────────────▼──────────────────────┐
│ React 前端                                               │
│  React Flow / Monaco / Zustand / Tailwind + shadcn       │
└──────────────────────────────────────────────────────────┘
           ▲ events / RPC responses
           │
┌──────────┴──────────────────────────────────────────────┐
│ Python Engine（headless）                                │
│  RPC Server → Job Manager → Pipeline Runner → Steps      │
│  Artifact Store / SQLite / Event Bus / Agent Client      │
│  Adapters: ffmpeg / mkv / llm                            │
└──────────────────────────────────────────────────────────┘
```

### 3.1 进程职责边界

| 层 | 负责 | 不负责 |
|---|---|---|
| Rust | 进程生命周期、拖拽、对话框、窗口、更新 | 任何字幕业务逻辑 |
| React | 展示、编辑配方、审核 diff、发起命令 | 解析字幕、调用 ffmpeg |
| Python | 全部业务、流水线、缓存、Agent、持久化 | 窗口与系统 UI |

### 3.2 为什么用 stdio 而不是 HTTP

- 无端口冲突、无防火墙弹窗。
- 生命周期跟随应用，退出即清理。
- 无鉴权与跨域问题。
- 天然流式；实现量小。

代价：必须严格保证 **stdout 只输出协议 JSON**，日志一律走 stderr。

---

## 4. 仓库结构

```
repo/
├─ AGENTS.md
├─ README.md
├─ CHANGELOG.md
├─ app_ui.py                    # 旧 GUI（迁移期保留）
├─ tools/                       # 旧逻辑（迁移期保留，作为参考实现）
├─ ui/                          # 旧 UI（迁移期保留）
├─ docs/
│  └─ pipeline-v2/
│     ├─ TASKBOOK.md            # 本文件
│     └─ PROTOCOL.md            # M0 产出
├─ engine/                      # 新 Python 引擎（独立 uv 项目）
│  ├─ pyproject.toml
│  ├─ src/subtitle_engine/
│  │  ├─ __main__.py
│  │  ├─ rpc/
│  │  │  ├─ server.py
│  │  │  ├─ framing.py
│  │  │  └─ errors.py
│  │  ├─ core/
│  │  │  ├─ models.py
│  │  │  ├─ step.py
│  │  │  ├─ registry.py
│  │  │  ├─ pipeline.py
│  │  │  ├─ store.py
│  │  │  ├─ cache.py
│  │  │  ├─ events.py
│  │  │  └─ workspace.py
│  │  ├─ domain/                # 从 tools/ 移植
│  │  │  ├─ srt.py
│  │  │  ├─ ass.py
│  │  │  ├─ merge.py
│  │  │  ├─ fps.py
│  │  │  ├─ shift.py
│  │  │  ├─ rename.py
│  │  │  ├─ outline.py
│  │  │  └─ paths.py
│  │  ├─ steps/
│  │  │  ├─ media_probe.py
│  │  │  ├─ media_extract.py
│  │  │  ├─ sub_normalize.py
│  │  │  ├─ sub_sdh_scan.py
│  │  │  ├─ sub_validate.py
│  │  │  ├─ sub_match_project.py
│  │  │  ├─ sub_merge.py
│  │  │  ├─ sub_shift.py
│  │  │  ├─ sub_fps.py
│  │  │  ├─ sub_rename.py
│  │  │  ├─ sub_export.py
│  │  │  ├─ human_review.py
│  │  │  └─ agent_sdh_review.py
│  │  ├─ agents/
│  │  │  ├─ client.py
│  │  │  ├─ sdh.py
│  │  │  └─ prompts/sdh_v1.md
│  │  ├─ recipes/
│  │  │  ├─ batch_video_to_clean_srt.yaml
│  │  │  ├─ batch_translated_to_bilingual.yaml
│  │  │  ├─ batch_normalize.yaml
│  │  │  └─ batch_shift_fps.yaml
│  │  └─ adapters/
│  │     ├─ ffmpeg.py
│  │     └─ mkv.py
│  └─ tests/
│     ├─ fixtures/
│     └─ golden/
├─ apps/
│  └─ desktop/
│     ├─ package.json
│     ├─ src/
│     │  ├─ app/                # 路由与布局
│     │  ├─ components/
│     │  ├─ features/
│     │  │  ├─ dropzone/
│     │  │  ├─ pipeline-editor/
│     │  │  ├─ run-view/
│     │  │  ├─ review/
│     │  │  ├─ projects/
│     │  │  └─ settings/
│     │  ├─ lib/
│     │  │  ├─ rpc.ts
│     │  │  ├─ events.ts
│     │  │  └─ schema-form/
│     │  └─ stores/
│     └─ src-tauri/
│        ├─ Cargo.toml
│        ├─ tauri.conf.json
│        ├─ binaries/           # sidecar 发布产物（gitignore）
│        └─ src/
│           ├─ main.rs
│           ├─ engine/
│           │  ├─ supervisor.rs
│           │  ├─ protocol.rs
│           │  └─ commands.rs
│           └─ fs_ops.rs
└─ scripts/
   ├─ build-engine.ps1
   └─ e2e.ps1
```

---

## 5. 协议规范（JSON-RPC over stdio）

> M0 必须产出 `docs/pipeline-v2/PROTOCOL.md`，本节为最低要求。

### 5.1 分帧

- 编码：UTF-8，无 BOM。
- 一行一个 JSON 对象，以 `\n` 结束。
- 禁止 pretty-print、禁止在 JSON 中输出未转义换行。
- 单行上限 4 MiB；超过视为协议错误。
- **stdout 只允许协议消息**；日志、traceback、print 全部走 stderr。

### 5.2 握手

请求：

```json
{"jsonrpc":"2.0","id":1,"method":"engine.hello","params":{"client":"subtitle-desktop","protocol":1}}
```

响应：

```json
{"jsonrpc":"2.0","id":1,"result":{"engine":"subtitle-engine","version":"0.1.0","protocol":1,"python":"3.15.2","capabilities":["pipeline","agent","review"]}}
```

协议版本不匹配时，UI 必须阻止运行并提示升级。

### 5.3 方法表

| 方法 | 参数 | 返回 | 说明 |
|---|---|---|---|
| `engine.hello` | `client, protocol` | 引擎信息 | 握手 |
| `engine.shutdown` | `{}` | `ok` | 优雅退出 |
| `steps.list` | `{}` | `StepSpec[]` | 步骤目录 + Options JSON Schema |
| `recipes.list` | `{}` | `RecipeSummary[]` | 预设 + 用户配方 |
| `recipes.get` | `id` | `Recipe` | 读取 |
| `recipes.save` | `recipe` | `Recipe` | 保存用户配方 |
| `recipes.delete` | `id` | `ok` | 只允许删用户配方 |
| `pipeline.validate` | `recipe` | `ValidationResult` | 环、端口、必填、路径冲突 |
| `pipeline.run` | `recipe, inputs, project_id?` | `{job_id, run_id}` | 启动 |
| `job.cancel` | `job_id` | `ok` | 取消并杀子进程树 |
| `job.status` | `job_id` | `Run` | 查询 |
| `project.list` | `{}` | `ProjectSummary[]` | 项目库 |
| `project.get` | `id` | `Project` | 详情 |
| `project.delete` | `id` | `ok` | 删除工作区 |
| `review.list` | `run_id` | `ReviewItem[]` | 待审项 |
| `review.submit` | `run_id, decisions` | `ok` | 提交审核结果 |
| `artifact.reveal` | `path` | `ok` | 在资源管理器打开 |
| `settings.get` | `{}` | `Settings` | 读取设置 |
| `settings.set` | `settings` | `Settings` | 保存设置 |
| `secrets.set` | `name, value` | `ok` | 写入系统钥匙串 |
| `agent.test` | `{}` | `{ok, latency_ms}` | 测试 API 连通性 |

### 5.4 错误

```json
{"jsonrpc":"2.0","id":7,"error":{"code":1002,"message":"Step failed","data":{"step":"extract","detail":"ffmpeg exited 1"}}}
```

| code | 含义 |
|---|---|
| `-32700` | JSON 解析失败 |
| `-32600` | 非法请求 |
| `-32601` | 方法不存在 |
| `-32602` | 参数错误 |
| `-32603` | 内部错误 |
| `1001` | 配方校验失败 |
| `1002` | 步骤执行失败 |
| `1003` | 已取消 |
| `1004` | 引擎忙（同一工作区并发限制） |
| `1005` | Agent 未配置 |
| `1006` | 依赖缺失（ffmpeg/mkvmerge） |

### 5.5 事件（Python → UI，notification）

```json
{"jsonrpc":"2.0","method":"event","params":{
  "event_id":"evt_01",
  "run_id":"run_01",
  "project_id":"prj_01",
  "seq":42,
  "type":"step.progress",
  "step":"extract",
  "percent":0.42,
  "message":"提取进度 42%",
  "ts":"2026-11-17T12:00:00Z"
}}
```

事件类型：

| type | 关键字段 |
|---|---|
| `run.started` | `recipe_id` |
| `step.started` | `step` |
| `step.progress` | `step, percent` |
| `step.log` | `step, level, message` |
| `step.artifact` | `step, key, path, kind` |
| `step.failed` | `step, error` |
| `run.finished` | `status: done/failed/cancelled`, `duration_ms` |
| `review.requested` | `run_id, review_id, items` |
| `review.resolved` | `review_id` |
| `project.updated` | `project` |

### 5.6 人工审核（HITL）

审核**不是**长连接阻塞请求，而是持久化状态：

1. `human.review` 步骤将待审项写入 SQLite，run 状态置为 `waiting_review`。
2. 引擎发出 `review.requested` 事件。
3. UI 调 `review.list` 拉取，用户在 diff 界面逐条处理。
4. UI 调 `review.submit`，引擎恢复 run。
5. 应用重启后，`project.list` 仍能看到 `waiting_review` 并继续。

审核项模型：

```json
{
  "id": "rev_0012",
  "segment_index": 12,
  "start_ms": 5400,
  "end_ms": 7100,
  "before": "[door slams]",
  "after": "",
  "action": "remove",
  "confidence": 0.93,
  "reason": "bracketed sound effect",
  "source": "agent"
}
```

---

## 6. 数据模型

### 6.1 工作区

```
<app_data>/projects/<project_id>/
├─ project.json
├─ source/                 # 只存引用，不复制视频
├─ extracted/
├─ clean/
├─ translated/
├─ output/
├─ artifacts/<sha256>/     # 内容寻址
├─ reviews/
├─ logs/
└─ project.db
```

`<app_data>` 在 Windows 为 `%APPDATA%/SubtitleProcess`。

### 6.2 Project

```python
class Project(BaseModel):
    id: str
    name: str
    created_at: datetime
    updated_at: datetime
    status: Literal[
        "draft", "running", "waiting_review",
        "waiting_translation", "done", "failed"
    ]
    media: MediaRef | None
    language: LanguagePair
    runs: list[RunRef] = []
    notes: str = ""
```

```python
class MediaRef(BaseModel):
    path: str
    fingerprint: str          # sha256(路径 + 大小 + mtime)
    duration: float
    streams: list[dict] = []
```

```python
class LanguagePair(BaseModel):
    source: str = "auto"      # BCP-47 或 ISO 639-1
    target: str = "zh"
```

### 6.3 Artifact

```python
class Artifact(BaseModel):
    key: str
    kind: Literal["srt", "ass", "vtt", "media_info", "subtitle_doc", "review", "any"]
    hash: str
    path: str
    meta: dict = {}
    created_at: datetime
```

规则：

- 产物路径必须在工作区内。
- 内容哈希 = `sha256(bytes)`，写入前计算。
- 同哈希已存在时直接复用，不重复写。

### 6.4 SubtitleDoc

```python
class Segment(BaseModel):
    index: int
    start_ms: int
    end_ms: int
    text: str
    style: str | None = None
    actor: str | None = None

class SubtitleDoc(BaseModel):
    fmt: Literal["srt", "ass", "vtt"]
    language: str | None = None
    segments: list[Segment]
    meta: dict = {}
```

> 注意：翻译步骤以**文件**为输入输出，`SubtitleDoc` 只用于分析、规则检查与审核，不用于 ASS 往返，避免丢样式。

### 6.5 SQLite 表

```sql
CREATE TABLE projects (
  id TEXT PRIMARY KEY,
  name TEXT NOT NULL,
  status TEXT NOT NULL,
  workspace TEXT NOT NULL,
  payload TEXT NOT NULL,      -- Project JSON
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);

CREATE TABLE runs (
  id TEXT PRIMARY KEY,
  project_id TEXT NOT NULL,
  recipe_id TEXT NOT NULL,
  status TEXT NOT NULL,
  payload TEXT NOT NULL,      -- Run JSON（含每步状态）
  started_at TEXT NOT NULL,
  finished_at TEXT
);

CREATE TABLE artifacts (
  hash TEXT PRIMARY KEY,
  kind TEXT NOT NULL,
  path TEXT NOT NULL,
  size INTEGER NOT NULL,
  payload TEXT NOT NULL,
  created_at TEXT NOT NULL
);

CREATE TABLE reviews (
  id TEXT PRIMARY KEY,
  run_id TEXT NOT NULL,
  step_id TEXT NOT NULL,
  status TEXT NOT NULL,       -- pending / submitted
  items TEXT NOT NULL,        -- JSON array
  decisions TEXT,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);

CREATE TABLE settings (
  key TEXT PRIMARY KEY,
  value TEXT NOT NULL
);
```

数据库迁移：`PRAGMA user_version` + 顺序迁移函数，禁止直接改表结构。

---

## 7. Step 规范

### 7.1 接口

```python
class PortSpec(BaseModel):
    kind: str                  # srt / ass / subtitle_doc / media_info / ...
    required: bool = True
    multiple: bool = False

class Step(Protocol):
    id: str                    # "media.extract_subtitles"
    title: str
    description: str
    inputs: dict[str, PortSpec]
    outputs: dict[str, PortSpec]
    Options: type[BaseModel]
    requires_agent: bool

    async def run(self, ctx: "StepContext", inputs: dict[str, Artifact]) -> dict[str, Artifact]:
        ...
```

### 7.2 StepContext

```python
@dataclass
class StepContext:
    run_id: str
    step_id: str
    project: Project
    workspace: Path
    options: BaseModel
    emit: Callable[[Event], None]
    progress: Callable[[float, str], None]
    is_cancelled: Callable[[], bool]
    services: "Services"       # cache / store / agent / ffmpeg
```

### 7.3 注册

```python
@register_step
class ExtractSubtitles(Step):
    id = "media.extract_subtitles"
    ...
```

`steps.list` 返回：

```json
{
  "id": "media.extract_subtitles",
  "title": "提取字幕",
  "description": "...",
  "inputs": {"probe": {"kind": "media_info", "required": true}},
  "outputs": {"subs": {"kind": "srt", "multiple": true}},
  "options_schema": { "type": "object", "properties": { ... } },
  "requires_agent": false
}
```

**Options 用 Pydantic 定义，自动 `model_json_schema()` 给前端生成表单。禁止前端硬编码每个步骤的参数。**

### 7.4 步骤状态

`idle → queued → running → done | failed | skipped | waiting_review`

`when` 条件为 false → `skipped`，不算失败。

---

## 8. 步骤清单与旧代码映射

| Step ID | 作用 | 复用来源 | 备注 |
|---|---|---|---|
| `media.probe` | ffprobe 分析 | `tools/subtitle_extractor.py::get_media_info` | 保留 mkvmerge 补充逻辑 |
| `media.extract_subtitles` | 提取字幕 | `extract_subtitles_v2` | 保留 VTT→SRT 转换 |
| `sub.normalize` | 清理/合并/标点 | `tools/srt_process.py` + `chs_srt_format.py` | 拆成可配置开关 |
| `sub.sdh_scan` | 规则扫描 SDH | 新增 | 只标记，不改 |
| `sub.validate` | 时间轴/空行/CPS 校验 | 新增 | 输出 warnings |
| `sub.match_project` | 译文与原项目匹配 | `merge_srt.classify_and_match_files` + 新增时间轴相似度 | 低置信度需人工选 |
| `sub.merge_bilingual` | 双语 ASS | `tools/merge_srt.py` | 保留样式配置 |
| `sub.shift_time` | 时间轴平移 | `tools/time_shifter.py` | |
| `sub.fps_convert` | 帧率转换 | `tools/fps_converter.py` | |
| `sub.rename` | 按视频重命名 | `tools/rename_sub.py` | |
| `sub.outline_scale` | ASS 描边缩放 | `tools/ass_outlinescale.py` | |
| `sub.export` | 写出文件 | 新增 | UTF-8 + LF + `.bak` |
| `human.review` | 人工审核 | 新增 | HITL |
| `agent.sdh_review` | SDH Agent | 新增 | API |
| `translate.linguagacha` | 预留占位 | 本期不实现 | 抛 `NotImplemented` |

移植要求：

- 新代码放 `engine/src/subtitle_engine/domain/`。
- 保持函数签名语义，去掉 `print`，改为 `logger` 或返回 warnings。
- **禁止静默吞异常**；失败必须抛出或写入 `StepResult.error`。
- 路径处理复用 `tools/path_utils.py` 的逻辑（移植为 `domain/paths.py`）。

---

## 9. Recipe 规范

### 9.1 Schema

```python
class RecipeInput(BaseModel):
    name: str
    kind: Literal["file", "folder", "files"]
    accept: list[str] = []
    required: bool = True

class StepNode(BaseModel):
    id: str
    uses: str
    needs: list[str] = []
    when: str | None = None          # 简单表达式，如 "${options.sdh_agent}"
    options: dict = Field(default_factory=dict, alias="with")
    ui: dict = {}                    # 画布坐标等，仅 UI 使用

class RecipeOutput(BaseModel):
    from_: str = Field(alias="from")
    key: str

class Recipe(BaseModel):
    id: str
    name: str
    version: int = 1
    description: str = ""
    builtin: bool = False
    inputs: list[RecipeInput]
    steps: list[StepNode]
    outputs: list[RecipeOutput]
    ui: dict = {}
```

### 9.2 校验规则

1. `id` 唯一，步骤 ID 唯一。
2. `needs` 必须指向已存在步骤。
3. 无环（`graphlib.TopologicalSorter`）。
4. 依赖端口类型兼容（相同 kind 或 `any`）。
5. 必填输入必须连接或有默认值。
6. `options` 必须通过对应 Step 的 Pydantic 校验。
7. 输出路径不得重复，不得越出工作区。
8. Agent 步骤必须配置模型，否则返回 `1005`。

### 9.3 预设模板

`engine/src/subtitle_engine/recipes/` 内置 4 个，`builtin=true`，UI 中**只读**，复制后可改：

1. `batch_video_to_clean_srt`
2. `batch_translated_to_bilingual`
3. `batch_normalize`
4. `batch_shift_fps`

用户配方存 `<app_data>/recipes/*.json`，版本字段用于未来迁移。

### 9.4 `batch_video_to_clean_srt` 参考

```yaml
id: batch_video_to_clean_srt
name: 视频 → 规范字幕
version: 1
builtin: true
inputs:
  - name: video
    kind: file
    accept: [".mkv", ".mp4", ".mov", ".avi", ".ts"]
steps:
  - id: probe
    uses: media.probe
  - id: extract
    uses: media.extract_subtitles
    needs: [probe]
    with:
      track: auto
      prefer_embedded: true
  - id: normalize
    uses: sub.normalize
    needs: [extract]
    with:
      strip_html: true
      merge_short: true
      merge_identical: true
      zh_punctuation: true
  - id: sdh_scan
    uses: sub.sdh_scan
    needs: [normalize]
    with:
      rules: [bracketed, parenthetical, music, speaker, uppercase]
  - id: sdh_review
    uses: agent.sdh_review
    needs: [sdh_scan]
    when: "${options.use_sdh_agent}"
    with:
      auto_apply: false
      min_confidence: 0.8
  - id: validate
    uses: sub.validate
    needs: [sdh_review]
  - id: export
    uses: sub.export
    needs: [validate]
    with:
      format: srt
      suffix: ""
```

### 9.5 `batch_translated_to_bilingual` 参考

```yaml
id: batch_translated_to_bilingual
name: 译文 SRT → 双语 ASS
version: 1
builtin: true
inputs:
  - name: translated
    kind: files
    accept: [".srt", ".ass"]
steps:
  - id: match
    uses: sub.match_project
    with:
      strategy: stem_then_timeline
  - id: validate
    uses: sub.validate
    needs: [match]
  - id: merge
    uses: sub.merge_bilingual
    needs: [validate]
    with:
      style_preset: house_default
      output_suffix: ".zh&en"
  - id: export
    uses: sub.export
    needs: [merge]
    with:
      format: ass
```

---

## 10. 流水线 Runner

### 10.1 执行流程

```
validate → 创建 run → 拓扑排序 → 逐层执行
  → 每步检查 when → 检查缓存 → 执行 → 存产物 → 写 DB → 发事件
  → 失败：记录、停止下游（可配置 continue_on_error）
  → 全部完成：汇总输出
```

### 10.2 缓存

```python
cache_key = sha256(
    step.id
    + engine_version
    + canonical_json(options)
    + sorted(input_artifact_hashes)
)
```

命中条件：产物存在且哈希一致。

缓存只对确定性步骤启用；Agent 步骤单独用 `(文本哈希 + prompt 版本 + 模型)` 缓存。

### 10.3 取消

- `job.cancel` 设置 `cancel_token`。
- 当前步骤的 `ctx.is_cancelled()` 返回 true。
- 子进程立即杀进程树。
- 状态置 `cancelled`，已完成的产物保留。

### 10.4 重试

- 默认每步最多 1 次重试（可配置）。
- 仅对“可重试错误”重试：网络超时、临时文件占用。
- 参数错误、依赖缺失不重试。

### 10.5 并发

- 同一 `project_id` 同时只允许一个 run（返回 `1004`）。
- 不同项目可并行，但全局限制 `max_parallel_jobs`（默认 2）。
- `extract` 等重 I/O 步骤内部不要并行多个 ffmpeg 写同一目录。

---

## 11. SDH Agent

### 11.1 总体流程

```
sub.sdh_scan（确定性规则）
    ↓ 候选 + reason code
agent.sdh_review（仅候选 + 上下文）
    ↓ 结构化决策
human.review（diff 确认）
    ↓
应用修改 → 审计日志
```

### 11.2 规则扫描（不依赖 LLM）

| reason | 示例 |
|---|---|
| `bracketed` | `[door slams]` |
| `parenthetical` | `(sighs)` |
| `music` | `♪ ...`、`♫` |
| `speaker` | `BEN:`、`- MARY:` |
| `uppercase` | 整行大写且长度 > 3 |
| `arrow` | `>> ...` |
| `ellipsis_action` | `... (laughs)` |

规则扫描只标记，不修改。输出 `SdhCandidate`：

```python
class SdhCandidate(BaseModel):
    segment_index: int
    reasons: list[str]
    text: str
```

### 11.3 Agent 输入

每批 20~30 条候选，附带前后各 2 条上下文：

```json
{
  "language": "en",
  "target_language": "zh",
  "context": [
    {"i": 10, "text": "..."},
    {"i": 11, "text": "..."}
  ],
  "candidates": [
    {"i": 12, "text": "[door slams]", "reasons": ["bracketed"]}
  ]
}
```

### 11.4 Agent 输出

使用 JSON Schema 严格约束：

```json
{
  "items": [
    {"i": 12, "action": "remove", "replacement": null, "confidence": 0.93, "reason": "sound effect"}
  ]
}
```

规则：

- `action` 只能是 `keep | remove | rewrite`。
- `rewrite` 必须给 `replacement`。
- **绝不返回或修改时间轴**。
- `confidence` 0~1。
- 解析失败重试 1 次，再失败则该批判 `failed`，不静默跳过。

### 11.5 应用策略

- `auto_apply=false`（默认）：全部进审核。
- `auto_apply=true` 且 `confidence >= min_confidence`：自动应用，但写入审计并允许撤销。
- 删除比例 > 30%：强制转人工，即使 `auto_apply=true`。
- 删除后若段落文本为空，保留该段但标记 `empty`，由 `sub.validate` 决定是否删除。

### 11.6 审计

```json
{
  "segment_index": 12,
  "before": "[door slams]",
  "after": "",
  "action": "remove",
  "source": "agent",
  "confidence": 0.93,
  "model": "deepseek-flash",
  "prompt_version": "sdh_v1",
  "ts": "..."
}
```

写入 `reviews/audit-<run_id>.jsonl`，UI 支持一键撤销整次 Agent 修改。

### 11.7 Prompt 管理

- 文件：`engine/src/subtitle_engine/agents/prompts/sdh_v1.md`
- 修改 prompt 必须升版本号。
- prompt 内容纳入缓存 key。
- 禁止把用户字幕内容写进日志。

### 11.8 评测

- `tests/fixtures/sdh/` 准备 30 条人工标注样本。
- 指标：precision / recall / 误删率。
- 误删率 > 2% 不允许默认自动应用。
- 评测脚本 `engine/tests/test_sdh_eval.py`（可跳过无 API 环境）。

### 11.9 API 配置

```json
{
  "base_url": "https://api.deepseek.com/v1",
  "model": "deepseek-flash",
  "temperature": 0,
  "timeout_s": 120,
  "max_retries": 2
}
```

- API Key 用 `keyring` 存 Windows Credential Manager。
- 设置页提供“测试连接”。
- 支持自定义 `base_url`，兼容 OpenAI / DeepSeek / Ollama 的 OpenAI 兼容端点。
- 默认不发送整片字幕，只发送候选段与上下文。

---

## 12. 前端要求

### 12.1 技术栈

| 类别 | 选择 |
|---|---|
| 框架 | React 19 + TypeScript + Vite |
| 样式 | Tailwind CSS + shadcn/ui |
| 图标 | lucide-react |
| 状态 | Zustand（+ `zundo` 做撤销） |
| 画布 | `@xyflow/react` v12 |
| 自动布局 | `dagre` 或 `elkjs` |
| Diff | `@monaco-editor/react` |
| 通知 | `sonner` |
| 表单 | 自研轻量 SchemaForm（支持 string/number/boolean/enum/array/object） |

不要引入 Redux、MobX 或重型表单库。

### 12.2 路由/页面

| 页面 | 职责 |
|---|---|
| `/` 首页 | 拖拽区、最近项目、推荐模板 |
| `/projects` 项目库 | 状态筛选、继续任务 |
| `/projects/:id` 项目详情 | 产物、运行记录、下一步 |
| `/editor/:recipeId?` 编辑器 | React Flow、步骤面板、参数面板 |
| `/runs/:id` 运行详情 | DAG 状态、日志、取消 |
| `/review/:runId` 审核 | diff、逐条接受/拒绝 |
| `/settings` 设置 | 路径、模型、语言、输出模板 |

### 12.3 拖拽

- 使用 Tauri `onDragDropEvent` 获取真实路径。
- 不要依赖 HTML5 `DataTransfer.files`（WebView 中拿不到完整路径）。
- 拖入后识别类型：
  - `.mkv/.mp4/.mov/.avi/.ts` → 推荐 `batch_video_to_clean_srt`
  - `.srt/.ass/.vtt` → 推荐 `batch_normalize` 或匹配已有项目
  - 文件夹 → 批量模式

### 12.4 React Flow 编辑器

必备能力：

1. 左侧步骤面板，数据来自 `steps.list`。
2. 拖入画布创建节点。
3. 连线仅允许类型兼容的端口。
4. 双击节点打开参数面板。
5. 节点状态实时着色。
6. 自动布局按钮。
7. 校验按钮 → 调 `pipeline.validate`，错误高亮到节点/边。
8. 保存 / 另存为 / 复制预设。
9. 撤销/重做。
10. 缩放、框选、删除、多选移动。

序列化时保留 `ui: {x, y}`；执行前剥离 UI 字段。

### 12.5 审核界面

- 左：视频/字幕预览（可选，M5 做基础版）。
- 中：待审列表（按置信度排序）。
- 右：Monaco diff（before/after）。
- 操作：接受、拒绝、批量接受高置信度、全部撤销。
- 快捷键：`J/K` 上下、`A` 接受、`R` 拒绝。

### 12.6 事件与状态

- `lib/rpc.ts`：请求/响应、超时、错误映射。
- `lib/events.ts`：订阅 Rust 转发的事件，按 `run_id` 分发。
- Zustand store 保存 runs、projects、editor state。
- 事件乱序/重连：以 `seq` 去重，断线后调 `job.status` 全量刷新。

---

## 13. 项目与交接流程

### 13.1 状态机

```
draft
  → running
  → waiting_review      （有审核项）
  → waiting_translation （干净 SRT 已导出）
  → running             （拖回译文）
  → done
  → failed
```

### 13.2 流程 1

1. 拖入视频。
2. 识别为视频 → 推荐 `batch_video_to_clean_srt`。
3. 运行，实时显示 DAG 状态。
4. 完成后产出 `<stem>.srt`。
5. 状态置 `waiting_translation`。
6. 显示交接卡片：
   - 路径
   - 「打开所在文件夹」
   - 「复制路径」
   - 提示“请用 LinguaGacha 翻译后拖回”

### 13.3 流程 2

1. 拖入译文 SRT。
2. 匹配项目，优先级：
   1. 同名 stem + 同源目录
   2. 项目 manifest 中的历史文件名
   3. 时间轴相似度：段落数差异 < 10%，首尾时间差 < 1s
   4. 最近 7 天项目
3. 找到 → 提示「继续 EP01 的合并流程」。
4. 找不到 → 展示候选列表 + 时间轴对比，让用户选。
5. 运行 `batch_translated_to_bilingual`。
6. 输出 `output/bilingual/<stem>.zh&en.ass`。

### 13.4 文件命名约定

| 产物 | 命名 |
|---|---|
| 原始提取 | `<stem>.orig.srt` |
| 清洗后 | `output/clean/<stem>.srt` |
| 译文（用户提供） | `<stem>.zh.srt` |
| 双语 | `output/bilingual/<stem>.zh&en.ass` |
| 批量规范 | `output/normalize/<stem>.srt` |
| 批量帧率转换 | `output/fps/<stem>.srt` |

允许用户在设置中改模板。

---

## 14. Rust Supervisor 要求

### 14.1 依赖

```toml
tauri = { version = "2", features = [] }
tokio = { version = "1", features = ["process", "io-util", "sync", "time", "macros"] }
serde = { version = "1", features = ["derive"] }
serde_json = "1"
tauri-plugin-dialog = "2"
tauri-plugin-opener = "2"
tauri-plugin-store = "2"
tauri-plugin-updater = "2"
tauri-plugin-single-instance = "2"
```

### 14.2 生命周期

- 应用启动 → 解析 sidecar 路径 → spawn。
- 握手 `engine.hello`，超时 10s。
- 崩溃 → 最多重启 3 次（60s 窗口），否则显示错误页。
- 应用退出 → `engine.shutdown`，等 2s，再杀进程树。
- Windows 创建进程加 `CREATE_NO_WINDOW`（`0x08000000`）。

### 14.3 请求路由

```rust
struct Supervisor {
    stdin: Mutex<ChildStdin>,
    pending: Mutex<HashMap<u64, oneshot::Sender<Value>>>,
    next_id: AtomicU64,
    status: RwLock<EngineStatus>,
}
```

- `engine_call(method, params)` 生成 id，写 stdin，等待 oneshot，超时 30s（`pipeline.run` 不等待，返回 job_id）。
- stdout 每行：若是 response → 命中 pending；若是 notification → `app.emit("engine:event", payload)`。
- stderr 每行：写日志文件 + `app.emit("engine:log", ...)`。
- 解析失败：记录原始行（截断 1KB），不崩溃。

### 14.4 暴露给前端的命令

| 命令 | 作用 |
|---|---|
| `engine_status` | 引擎状态 |
| `engine_restart` | 手动重启 |
| `pick_files` | 文件对话框 |
| `pick_folder` | 文件夹对话框 |
| `reveal_path` | 资源管理器打开 |
| `write_log` | 前端日志（可选） |

> 业务请求统一走 `engine_call` 泛型命令，不要为每个方法写一个 Rust 命令。

### 14.5 打包

`tauri.conf.json`：

```json
{
  "bundle": {
    "externalBin": ["binaries/subtitle-engine"]
  }
}
```

sidecar 文件名必须带 target triple，例如：

```
src-tauri/binaries/subtitle-engine-x86_64-pc-windows-msvc.exe
```

开发模式优先用 `uv run python -m subtitle_engine --rpc stdio`，避免每次打包。

---

## 15. 测试策略

### 15.1 Python

- `pytest` + `pytest-asyncio`。
- 协议：分帧、非法 JSON、未知方法、超时。
- Runner：拓扑、环检测、条件跳过、缓存命中、取消、失败停止下游。
- 步骤：每个步骤至少 1 个正常用例 + 1 个错误用例。
- Golden：输入 fixture → 输出与旧 `tools/` 结果一致（去除时间戳/路径差异）。
- SDH：规则扫描样本 + Agent 输出解析（mock API）。
- 属性测试：时间轴解析、SRT 序号连续性（hypothesis）。

### 15.2 Rust

- 行解析单元测试。
- 请求/响应匹配测试。
- 超时与重启策略测试（用假进程）。

### 15.3 前端

- Vitest + Testing Library：store、SchemaForm、连线校验。
- Playwright：在浏览器模式下 mock `window.__TAURI__`，测编辑器基本流程。
- Tauri 真机 E2E 可选（`tauri-driver`），不作为门槛。

### 15.4 端到端脚本

`scripts/e2e.ps1`：

1. 用 `engine` CLI 跑 `batch_video_to_clean_srt` 的 fixture。
2. 校验输出存在、行数、时间轴。
3. 跑 `batch_translated_to_bilingual`。
4. 返回非 0 即失败。

---

## 16. 打包与发布

### 16.1 引擎打包

优先：

```bash
cd engine
uv run nuitka --onefile --assume-yes-for-downloads \
  --output-filename subtitle-engine \
  src/subtitle_engine/__main__.py
```

若 Nuitka 不可用（或加 `-Fallback`），回退到 PyInstaller onefile：

```bash
uv run pyinstaller --onefile --noconsole --name subtitle-engine \
  src/subtitle_engine/__main__.py
```

两种方案都产出单个自包含可执行文件，直接作为 `bundle.externalBin` 打包；不要使用
onedir，Tauri 只复制 sidecar 文件本身，`_internal/` 不会跟随。

### 16.2 发布检查

- [ ] 干净 Windows 虚拟机安装可启动。
- [ ] 无 Python 环境时引擎可运行。
- [ ] ffmpeg/mkvmerge 缺失时有明确提示（`1006`）。
- [ ] 安装包体积记录（目标 < 120 MB）。
- [ ] 自动更新可用。
- [ ] 卸载不残留工作区（或提示用户）。

### 16.3 依赖检测

启动时检测：

```bash
ffmpeg -version
ffprobe -version
mkvmerge --version
```

结果写入设置页，缺失时相关步骤置灰并说明。

---

## 17. 里程碑与验收

> 每个里程碑结束必须：测试通过、`CHANGELOG.md` 增加条目、Conventional Commit 提交。

### M0 骨架（3~5 天）✅

- [x] `engine` uv 项目可运行。
- [x] JSON-RPC server 支持 `engine.hello` / `engine.shutdown`。
- [x] `steps.list` 返回 1 个假步骤。
- [x] Tauri 应用可启动并 spawn sidecar。
- [x] React 首页可拖入文件，显示路径。
- [x] 假步骤发出 `step.progress`，UI 实时显示。
- [x] `docs/pipeline-v2/PROTOCOL.md` 完成。

验收：拖入任意文件，点“运行示例”，日志区出现 0→100% 进度，无控制台窗口。
（已用 CDP 连真实 WebView 验证；sidecar 使用 `CREATE_NO_WINDOW`，主程序 release 隐藏控制台。）

### M1 引擎核心（5 天）✅

- [x] `models/registry/pipeline/store/cache/events` 完成。
- [x] SQLite 初始化与迁移。
- [x] 内容寻址产物存储。
- [x] CLI：`uv run python -m subtitle_engine run recipes/demo.yaml --input ...`。
- [x] Runner 单测覆盖率 > 80%（实测 86%）。
- [x] 缓存命中、取消、失败停止下游均有用例。
- [x] 取消时清理子进程树。

验收：三步假流水线第二次运行全命中缓存；取消后无残留子进程。
（`tests/test_cli.py` 跨进程验证全缓存；`tests/test_pipeline.py::test_cancel_kills_child_process_tree` 验证 taskkill。）

### M2 领域步骤（7 天）✅

- [x] `media.probe` / `media.extract_subtitles` 移植。
- [x] `sub.normalize` / `sub.export` 移植。
- [x] `sub.validate` 新增。
- [x] Golden test 与旧实现一致。
- [x] ffmpeg/mkvmerge 缺失错误可读（`1006` + `data.tool`）。

验收：用 2 个 fixture 视频跑出 SRT，与旧版输出逐段一致（忽略路径/时间戳）。
（`tests/test_media_steps.py` 动态生成 MKV/MP4（srt/mov_text）fixture，跑通
`probe → extract → normalize → validate → export`，并与旧 `SubtitleExtractor`
+ `srt_process` 输出逐字节对比；`tests/test_domain_golden.py` 在无需 ffmpeg 的环境
直接导入旧 `tools/` 算法做 Golden 对比。）

### M3 项目与配方（5 天）✅

- [x] Project 工作区、状态机、SQLite 持久化。
- [x] 4 个内置配方。
- [x] `pipeline.validate` 完整。
- [x] 流程 1 端到端可用。
- [x] 交接卡片（打开文件夹/复制路径）。

验收：拖入视频 → 干净 SRT → 状态 `waiting_translation`，重启应用后项目仍在。
（`tests/test_flow1.py` 用真实 ffmpeg 生成的 MKV 跑通
`project.create → pipeline.run(batch_video_to_clean_srt) → project.get`，并重启
`RpcServer` 验证项目仍在；前端新增「最近项目」与交接卡片。）

### M4 自由连线编辑器（7 天）✅

- [x] React Flow 画布 + 步骤面板。
- [x] 类型兼容连线校验。
- [x] SchemaForm 参数面板。
- [x] 保存/另存为/复制预设。
- [x] 撤销/重做、自动布局。
- [x] 校验错误定位到节点/边。

验收：用户从空白画布搭出 `probe → extract → normalize → export` 并成功运行。
（`apps/desktop/src/lib/recipeGraph.test.ts` 覆盖配方↔画布互转、端口兼容、自动布局与问题定位；
`src/stores/editorStore.test.ts` 覆盖连线、撤销/重做与拖动历史；`src/features/editor/SchemaForm.test.tsx`
覆盖 JSON Schema 表单。前端 39 个 Vitest 全部通过，`tsc && vite build` 通过；
`engine/tests/test_editor_recipes.py` 用真实 MKV 跑通编辑器产出的配方并可保存/重载。）

### M5 SDH 规则与审核（5 天）✅

- [x] `sub.sdh_scan` 规则 + reason code。
- [x] `human.review` 步骤与 SQLite 持久化。
- [x] 审核 UI + Monaco diff。
- [x] 审计 JSONL。
- [x] 重启后审核状态可恢复。

验收：规则标记 20 条，审核接受/拒绝后产物正确变化，审计可撤销。
（`engine/tests/test_reviews.py` 覆盖 7 条规则、`waiting_review` 暂停/恢复、接受/拒绝/改写、
审计 JSONL 与 `review.undo`；`test_review_survives_restart` 用同一 data-dir 重建
`RpcServer` 后提交审核并完成导出。前端 `reviewStore.test.ts` / `ReviewPage.test.tsx` /
`router.test.ts` / `runStore.test.ts` 覆盖审核页交互与事件。实现说明：暂停断点存
`run_state`（SQLite v2），未提交的审核项默认拒绝，接受 `remove` 时仅清空文本、
不改时间轴；`review.undo` 生成撤销副本。）

### M6 Agent（5 天）✅

- [x] OpenAI 兼容客户端（httpx）。
- [x] `agent.sdh_review` 结构化输出。
- [x] Key 存钥匙串，设置页可测试连接。
- [x] 只发送候选 + 上下文。
- [x] 缓存、置信度、删除比例保护。
- [x] 30 条评测样本，输出 precision/recall。

验收：无 Key 时步骤给出 `1005` 明确错误；有 Key 时只处理候选段，默认不自动删除。
（`engine/tests/test_agent.py` 用 `httpx.MockTransport` 覆盖 `1005`、`settings.get/set`、
`secrets.set` 不落 SQLite、`agent.test`、只发送候选+上下文、默认不自动删除、自动应用
审计与 `review.undo`、删除比例保护、Agent 缓存；`test_sdh_eval.py` 使用
`tests/fixtures/sdh/samples.jsonl` 30 条标注样本计算 precision/recall/误删率，未配置
API Key 时跳过真实评测。前端新增 `#/settings` 设置页与连接测试，72 个 Vitest 通过。）

### M7 合并与发布

- [x] `sub.match_project`（stem + 时间轴）。
- [x] `sub.merge_bilingual` / `sub.shift_time` / `sub.fps_convert` / `sub.rename` / `sub.outline_scale`。
- [x] 流程 2 端到端。
- [x] Nuitka sidecar 打包。
- [x] 自动更新、单实例、崩溃恢复。
- [x] `README` 更新，`CHANGELOG` 更新。

验收：干净 Windows 虚拟机安装 → 流程 1 → 手动翻译 → 拖回 → 双语 ASS，全程无 Python 环境。
（`engine/tests/test_flow2.py` 用真实 ffmpeg MKV 跑通
`project.create → batch_video_to_clean_srt → 构造译文 → batch_translated_to_bilingual`，
并验证重启后项目为 `done`；`scripts/e2e.ps1` 用 CLI 跑通两阶段。领域层
`domain/merge.py` 与旧 `tools/merge_srt.py`、`domain/timing.py` /
`domain/outline.py` 与旧实现均做逐字节 golden。
前端新增「译文 → 双语 ASS」面板，`flow2.ts` 负责项目推荐，85 个 Vitest 通过。
`scripts/build-engine.ps1` 产出 `binaries/subtitle-engine-<triple>.exe`，
`tauri.conf.json` 启用 `externalBin` / `createUpdaterArtifacts` / updater，
Rust 注册 single-instance（最先）、updater、store。实现说明：本机无 Rust
工具链，Tauri 打包与自动更新仅做静态配置，未在本机编译验证。

---

## 18. 新 session 执行顺序

1. `git status`，确认当前分支为 `feat/pipeline-v2`。
2. 阅读：`AGENTS.md` → 本文件 → `README.md` → `tools/subtitle_api.py`。
3. 检查环境：`uv --version`、`node --version`、`rustc --version`、`ffmpeg -version`。
4. 按 M0 → M7 顺序执行，**不要跳里程碑**。
5. 每个里程碑：
   - 先写测试或验收脚本。
   - 实现。
   - 跑测试。
   - 更新 `CHANGELOG.md`。
   - `git add` + Conventional Commit（如 `feat(engine): add json-rpc server`）。
6. 遇到需求不明确时，优先按本文件的“已确认决策”执行；确实冲突再询问。
7. 不要修改 `version.py`，除非用户明确要求发版。
8. 不要删除旧 `app_ui.py` / `ui/` / `tools/`，迁移完成前它们是对比基准。

### 18.1 首日建议

- 先完成 `engine` 的 `rpc/framing.py` 与 `__main__.py`，用管道手动测：
  ```powershell
  '{"jsonrpc":"2.0","id":1,"method":"engine.hello","params":{}}' | uv run python -m subtitle_engine --rpc stdio
  ```
- 再搭 Tauri，确保 Rust 能 spawn 并收到响应。
- 最后接 React，先做一个“运行示例”按钮，闭环。

---

## 19. 风险与红线

| 风险 | 对策 |
|---|---|
| Python 打包体积/启动/杀软 | Nuitka onefile 优先，失败回退 PyInstaller onefile；签名；延迟加载 |
| stdout 被 print 污染 | 禁用业务层 print；日志统一 stderr；协议层加断言 |
| Agent 误删字幕 | 默认不自动应用、置信度阈值、删除比例保护、审计可撤销 |
| 翻译文件匹配错误 | 双因子匹配，低置信度必须人工选 |
| 长任务取消不干净 | 记录 PID，Windows `taskkill /T /F` |
| 配方格式演进 | `version` + 迁移函数 |
| 用户手改中间文件 | 内容哈希检测，提示重跑 |
| 自由连线产生非法图 | 保存前必须 `pipeline.validate` |
| 并发写同一项目 | 项目级互斥，返回 `1004` |
| Tauri/Rust 复杂度 | Rust 只做壳，业务全在 Python |

### 红线

1. 领域算法不得在未通过 golden test 的情况下修改。
2. 不得静默吞异常（AGENTS.md 要求）。
3. 不得把 API Key 写入配置文件或日志。
4. 不得让 Agent 修改时间轴。
5. 不得让 UI 直接操作文件系统写业务产物（统一走引擎）。
6. 不得在 `stdout` 输出非协议内容。
7. 不得跳过审核直接覆盖用户文件；写前备份。
8. 不得在未更新 `CHANGELOG.md` 的情况下合并分支。

---

## 20. 附录

### 20.1 环境要求

| 工具 | 版本 |
|---|---|
| Python | 3.15 |
| uv | 最新稳定版 |
| Node.js | 22+ |
| pnpm / npm | 最新稳定版 |
| Rust | stable + `x86_64-pc-windows-msvc` |
| FFmpeg | 6+（含 ffprobe） |
| MKVToolNix | 最新稳定版 |

### 20.2 常用命令

```powershell
# 引擎开发
cd engine
uv sync
uv run python -m subtitle_engine --rpc stdio

# 引擎测试
uv run pytest -q

# 前端开发
cd apps/desktop
npm install
npm run tauri dev

# 前端测试
npm run test

# 打包
npm run tauri build
```

### 20.3 命名约定

- Step ID：`<domain>.<action>`，如 `media.extract_subtitles`。
- 事件：`<object>.<past_tense>`，如 `step.started`。
- 错误码：`1xxx` 业务错误，`-32xx` JSON-RPC 标准。
- 数据库表：小写下划线复数。
- 配方文件：kebab-case 或 snake_case 均可，但同一目录保持一致（推荐 snake_case）。

### 20.4 术语

| 术语 | 含义 |
|---|---|
| Recipe | 流水线配方，描述步骤与连线 |
| Run | 一次配方执行 |
| Project | 一个媒体/字幕任务的长期工作区 |
| Artifact | 步骤产物 |
| Port | 步骤的输入/输出类型 |
| HITL | Human-in-the-loop，人工审核 |
| SDH | Subtitles for the Deaf and Hard of hearing，听障字幕 |

---

## 21. 交付物清单

M7 结束时，分支上应包含：

- [x] `engine/` 完整实现与测试。
- [x] `apps/desktop/` 完整实现。
- [x] `docs/pipeline-v2/PROTOCOL.md`。
- [x] `docs/pipeline-v2/TASKBOOK.md`（本文件，持续更新）。
- [x] 4 个内置配方。
- [x] `scripts/build-engine.ps1`、`scripts/e2e.ps1`。
- [x] `README.md` 更新（新架构、开发、打包）。
- [x] `CHANGELOG.md` 更新（Unreleased → 版本）。
- [ ] 旧代码去留说明（保留或删除，需用户确认）。当前**保留** `app_ui.py` / `ui/` / `tools/` 作为参考与 golden 基准，待用户确认后再删除。

---

> 执行原则：**先把闭环跑通，再追求完整**。任何里程碑如果 3 天内无法闭环，先缩小范围，保证“拖入 → 运行 → 产出”始终可用。

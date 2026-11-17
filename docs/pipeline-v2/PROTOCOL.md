# 引擎协议规范（v1）

> 适用：`engine/`（Python sidecar）↔ `apps/desktop/src-tauri`（Rust supervisor）↔ React 前端
> 版本：协议 `1`，随 `engine/src/subtitle_engine/version.py::PROTOCOL_VERSION` 递增
> 最后更新：2026-11-17（M3）

## 1. 传输层

| 项 | 规定 |
|---|---|
| 通道 | 子进程 `stdin` / `stdout`（sidecar 模式） |
| 编码 | UTF-8，无 BOM |
| 分帧 | 一行一个 JSON 对象，`\n` 结尾；禁止 pretty-print |
| 单行上限 | **4 MiB**（4 194 304 字节），超限视为协议错误 |
| stdout | **只允许** JSON-RPC 消息 |
| stderr | 日志 / traceback / 诊断，可任意多行 |
| 超时 | 普通请求 30s；`pipeline.run` 立即返回，不等待执行结束 |

违规处理：

- 单行超限：引擎返回 `-32600` 并丢弃该行剩余内容，继续服务。
- JSON 解析失败：引擎返回 `-32700`，`id` 为 `null`，**不退出**。
- 非对象 JSON（数组/字符串/数字）：返回 `-32600`。
- Rust 侧解析失败：记录原始行（截断 1 KB）到日志，不崩溃。

启动命令：

```powershell
# 开发模式
uv run python -m subtitle_engine --rpc stdio

# 打包后（sidecar）
subtitle-engine.exe --rpc stdio
```

`--version` 只在人工调用时使用，输出到 stdout 后退出，不进入 RPC 循环。

## 2. 消息格式

请求：

```json
{"jsonrpc":"2.0","id":1,"method":"engine.hello","params":{"client":"subtitle-desktop","protocol":1}}
```

成功响应：

```json
{"jsonrpc":"2.0","id":1,"result":{...}}
```

错误响应：

```json
{"jsonrpc":"2.0","id":7,"error":{"code":1002,"message":"Step failed","data":{"step":"extract","detail":"ffmpeg exited 1"}}}
```

通知（引擎 → UI，无 `id`，无需响应）：

```json
{"jsonrpc":"2.0","method":"event","params":{...}}
```

- `id`：整数或字符串，由客户端生成；引擎原样回显。
- 无 `id` 的请求按 notification 处理：执行但不返回响应。
- `params` 必须是 JSON 对象；数组或缺省视为 `{}`（数组返回 `-32602`）。

## 3. 握手

请求：

```json
{"jsonrpc":"2.0","id":1,"method":"engine.hello","params":{"client":"subtitle-desktop","protocol":1}}
```

响应：

```json
{"jsonrpc":"2.0","id":1,"result":{
  "engine":"subtitle-engine",
  "version":"0.1.0",
  "protocol":1,
  "python":"3.15.2",
  "capabilities":["pipeline"]
}}
```

规则：

- 引擎**始终**返回自身 `protocol`，即使客户端版本不同。
- 前端必须比较 `result.protocol` 与自身支持的版本；不一致时阻止运行并提示升级。
- Rust supervisor 在 spawn 后 10s 内未完成握手即判定启动失败。
- `capabilities` 当前为 `["pipeline", "recipes", "project", "review", "agent"]`；客户端可按能力判断设置页/Agent 入口是否可用。

## 4. 方法表

状态列：**M0** = 已实现并通过测试；后续里程碑逐步补齐。

| 方法 | 参数 | 返回 | 状态 | 说明 |
|---|---|---|---|---|
| `engine.hello` | `client?, protocol?` | `EngineInfo` | M0 | 握手 |
| `engine.shutdown` | `{}` | `"ok"` | M0 | 优雅退出；响应发出后进程退出 |
| `steps.list` | `{}` | `StepSpec[]` | M0 | 步骤目录 + Options JSON Schema |
| `pipeline.run` | `recipe?, recipe_id?, inputs?, options?, project_id?, max_retries?, continue_on_error?, no_cache?` | `{job_id, run_id}` | M1/M3 | 启动；省略 recipe 时按 recipe_id 加载，再省略则运行内置示例 |
| `job.status` | `job_id` | `Run` | M0 | 查询运行状态 |
| `job.cancel` | `job_id` | `"ok"` | M0 | 取消并杀子进程树 |
| `recipes.list` | `{}` | `RecipeSummary[]` | M3 | 4 个内置模板 + 用户配方 |
| `recipes.get` | `id` | `Recipe` | M3 | 读取 |
| `recipes.save` | `recipe` | `Recipe` | M3 | 保存用户配方；内置配方只读 |
| `recipes.delete` | `id` | `"ok"` | M3 | 只允许删用户配方 |
| `pipeline.validate` | `recipe? / recipe_id?, project_id?` | `ValidationResult` | M3 | 环、端口、必填、选项、路径冲突 |
| `project.create` | `name?, media_path?, language?` | `Project` | M3 | 创建工作区（扩展方法） |
| `project.list` | `{}` | `ProjectSummary[]` | M3 | 项目库 |
| `project.get` | `id` | `Project` | M3 | 详情 |
| `project.delete` | `id` | `"ok"` | M3 | 删除工作区与 run 记录 |
| `review.list` | `run_id` | `ReviewItem[]` | M5 | 待审项（扁平数组，含 `review_id` / `review_status`） |
| `review.submit` | `run_id, decisions` | `"ok"` | M5 | 提交审核结果并恢复 run |
| `review.undo` | `run_id` | `{review_id, audit_path, restored[]}` | M5 | 按审计 JSONL 生成撤销副本（扩展方法） |
| `artifact.reveal` | `path` | `"ok"` | M3 | 资源管理器定位文件/目录 |
| `settings.get` | `{}` | `Settings` | M6 | 读取设置（含 `agent.api_key_configured`） |
| `settings.set` | `settings` | `Settings` | M6 | 保存非敏感设置；包含 API Key 返回 `-32602` |
| `secrets.set` | `name, value` | `"ok"` | M6 | 写入系统钥匙串；`value=""` 删除该项 |
| `agent.test` | `{}` | `{ok, latency_ms, model, base_url}` | M6 | 测试 API 连通性；未配置返回 `1005` |

### 4.1 `pipeline.run`（M1 行为）

- `recipe`：完整配方对象，见第 6 节；省略时运行内置 `demo` 配方（单步 `demo.tick`）。
- `inputs`：字符串路径数组，原样传给步骤上下文，M1 不复制文件。
- `options`：运行级选项对象，供 `when: "${options.x}"` 与后续步骤读取。
- `max_retries`：可重试错误的最大重试次数（默认 1，0 表示不重试）。
- `continue_on_error`：为 true 时某步失败只跳过其下游，其它分支继续（默认 false）。
- `no_cache`：为 true 时禁用步骤缓存。
- 立即返回 `{job_id, run_id}`；M1 二者相同。
- 同一项目已有运行中的 run 时返回 `1004`；全局并行超限时新 run 进入 `queued`。
- 配方校验（id 重复、依赖缺失、环）失败返回 `1001`，不会创建 run。

### 4.2 `job.status` 返回

```json
{
  "id":"run_1a2b3c4d",
  "project_id":null,
  "recipe_id":"demo",
  "status":"running",
  "steps":[
    {
      "id":"demo",
      "uses":"demo.tick",
      "status":"running",
      "progress":0.4,
      "cached":false,
      "attempts":1
    }
  ],
  "started_at":"2026-11-17T12:00:00.123456Z"
}
```

- `status`：`queued | running | waiting_review | done | failed | cancelled`
- 步骤 `status`：`idle | queued | running | done | failed | skipped | waiting_review | cancelled`
- `cached=true` 表示该步命中缓存（未执行、`attempts=0`）。
- 时间字段为 ISO 8601 UTC；未发生的字段省略（`exclude_none`）。

### 4.3 `pipeline.validate` 返回（M3）

```json
{
  "ok": false,
  "errors": [
    {
      "severity": "error",
      "code": "incompatible_port",
      "message": "步骤 export 的输入 subs（srt）与上游类型不兼容: ass",
      "step_id": "export",
      "port": "subs",
      "data": {"available": ["ass"]}
    }
  ],
  "warnings": [],
  "order": ["probe", "extract", "normalize", "validate", "export"]
}
```

校验规则：

- 步骤 id 唯一、`needs` 必须存在、无环。
- 未知步骤实现、Options Schema 校验失败。
- 必填输入端口必须有类型兼容的上游；`kind` 相同或任一端为 `any`。
- `sub.export` 的 `output_dir` 必须位于项目工作区内，`filename` 不得含路径分隔符；多个导出步骤不得写同一路径。
- `recipe.outputs` 必须引用已声明端口。
- 需要 Agent 的步骤在未配置时返回 `warning: agent_not_configured`（运行时会返回 `1005`）。

`pipeline.run` 会在启动前执行同一套校验；失败返回 `1001`，`error.data` 即上述结果。

### 4.4 `Project`（M3）

```json
{
  "id": "prj_1a2b3c4d5e6f",
  "name": "EP01",
  "status": "waiting_translation",
  "created_at": "2026-11-17T12:00:00Z",
  "updated_at": "2026-11-17T12:01:00Z",
  "media": {
    "path": "D:/video/EP01.mkv",
    "fingerprint": "sha256(路径+大小+mtime)",
    "duration": 0.0,
    "streams": []
  },
  "language": {"source": "auto", "target": "zh"},
  "runs": [{"id": "run_1a2b3c4d", "recipe_id": "video_to_clean_srt", "status": "done"}],
  "outputs": [
    {"path": "…/projects/prj_…/output/EP01.clean.srt", "kind": "srt", "step": "export"}
  ],
  "notes": "",
  "workspace": "…/projects/prj_1a2b3c4d5e6f"
}
```

工作区目录：`<data_dir>/projects/<project_id>/{source,extracted,clean,translated,output,artifacts,reviews,logs}`。
`project.list` 返回 `ProjectSummary`（含 `media_path`、`workspace`、`outputs` 路径数组）。

状态机：`draft → running → waiting_review / waiting_translation → running → done`，失败为 `failed`。
`video_to_clean_srt` 成功且登记到 `output/` 产物后置为 `waiting_translation`；
`translated_to_bilingual` 成功置为 `done`。

### 4.5 `recipes.list` 返回（M3）

```json
[
  {
    "id": "video_to_clean_srt",
    "name": "视频 → 规范字幕",
    "version": 1,
    "description": "…",
    "builtin": true,
    "step_count": 5
  }
]
```

内置配方：`video_to_clean_srt`、`translated_to_bilingual`、`batch_normalize`、`batch_shift_fps`。
内置项 `builtin=true`，`recipes.save` / `recipes.delete` 会返回 `1001`；用户配方存
`<data_dir>/recipes/<id>.json`。`translated_to_bilingual` / `batch_shift_fps` 依赖的
M7 步骤当前为占位实现，执行时返回 `1002` 且 `data.milestone` 标明计划里程碑。

### 4.6 Agent 设置与 `agent.sdh_review`（M6）

`settings.get` / `settings.set` 的完整形态：

```json
{
  "agent": {
    "base_url": "https://api.deepseek.com/v1",
    "model": "deepseek-chat",
    "temperature": 0,
    "timeout_s": 120,
    "max_retries": 2,
    "batch_size": 25,
    "context_size": 2,
    "min_confidence": 0.85,
    "auto_apply": false,
    "delete_ratio_limit": 0.3,
    "structured_output": "json_schema",
    "api_key_configured": true
  }
}
```

- `api_key_configured` 是只读状态；`settings.set` 中出现 `api_key` / `secret` / `token`
  字段会被拒绝（`-32602`），Key 只能通过 `secrets.set` 写入系统钥匙串。
- `secrets.set` 的 `name` 推荐 `agent.api_key`；密钥值绝不进入 SQLite、配方、日志或
  错误信息。无钥匙串的 headless 环境可用环境变量
  `SUBTITLE_ENGINE_AGENT_API_KEY`。
- `agent.test` 发送最小 `ping` 请求，返回 `latency_ms` 与实际 `model`；未配置返回 `1005`，
  HTTP/网络失败返回 `1002`。
- `agent.sdh_review` 输入 `subs` + `candidates`，输出同名字幕与增强后的
  `candidates`。每批 5~30 条候选并附带前后 `context_size` 行**非候选**上下文；
  不发送整片字幕，绝不修改时间轴。
- Agent 输出严格为 `{"items":[{"i","action","replacement","confidence","reason"}]}`；
  `action` 仅 `keep | remove | rewrite`，`rewrite` 必须有 `replacement`。解析失败重试
  1 次，仍失败则步骤失败（`1002`），不会静默跳过。
- 默认 `auto_apply=false`：所有决策写入候选，交给 `human.review`。开启后仅自动应用
  `confidence >= min_confidence` 的 `remove/rewrite`；删除比例超过
  `delete_ratio_limit`（默认 30%）强制转人工；自动应用写审计并可用 `review.undo` 撤销。
- Agent 决策缓存键为 `(输入产物哈希 + 步骤选项 + prompt 版本 + model + base_url +
  structured_output)`；`auto_apply=true` 时不使用缓存，避免跳过审计。

## 5. 错误码

| code | 含义 | 前端处理 |
|---|---|---|
| `-32700` | JSON 解析失败 | 记录并提示协议错误 |
| `-32600` | 非法请求 / 分帧超限 | 记录；检查客户端实现 |
| `-32601` | 方法不存在 | 版本不匹配，提示升级 |
| `-32602` | 参数错误 | 定位到表单字段 |
| `-32603` | 内部错误 | 展示 message + 日志 |
| `1001` | 配方校验失败 | 定位到节点/边 |
| `1002` | 步骤执行失败 | 展示 `data.step` + `data.detail` |
| `1003` | 已取消 | 不算失败，灰色显示 |
| `1004` | 引擎忙（同项目并发） | 提示等待或取消旧运行 |
| `1005` | Agent 未配置 | 跳转设置页 |
| `1006` | 依赖缺失（ffmpeg/mkvmerge） | 跳转依赖检测页 |

## 6. 步骤与配方

### 6.1 `StepSpec`

```json
{
  "id":"demo.tick",
  "title":"示例步骤（进度演示）",
  "description":"M0 占位步骤：把 0→100% 进度分批发给 UI，不产生业务产物。",
  "inputs":{},
  "outputs":{"summary":{"kind":"any","required":false,"multiple":false}},
  "options_schema":{
    "type":"object",
    "properties":{
      "steps":{"type":"integer","default":10},
      "delay_ms":{"type":"integer","default":60},
      "fail":{"type":"boolean","default":false}
    }
  },
  "requires_agent":false,
  "deterministic":true
}
```

- `options_schema` 由 Pydantic `model_json_schema()` 生成，前端**禁止**硬编码参数表单。
- 端口 `kind` 取值：`srt` / `ass` / `vtt` / `media_info` / `subtitle_doc` / `sdh_candidates` / `review_audit` / `review` / `any`。
- 连线规则：`kind` 相同或任一端为 `any`。

### 6.2 `Recipe`（M0 子集）

```json
{
  "id":"demo",
  "name":"示例流水线",
  "version":1,
  "description":"",
  "builtin":false,
  "inputs":[],
  "steps":[
    {"id":"demo","uses":"demo.tick","needs":[],"with":{"steps":10,"delay_ms":60},"ui":{"x":0,"y":0}}
  ],
  "outputs":[],
  "ui":{}
}
```

M1 执行约定：

- 步骤按 `needs` 进行拓扑排序执行（与数组顺序无关）；环、依赖缺失、id 重复在启动前返回 `1001`。
- `when` 仅支持 `${options.<key>}`（可嵌套，如 `${options.a.b}`）；不支持的表达式显式报 `-32602`，不会静默跳过。
- `with` 即 `options`；`ui` 仅前端使用，执行前可剥离。
- 输入端口按 `kind` 从上游输出自动注入；必填端口没有匹配产物时该步失败。
- 端口声明 `multiple: true` 时，步骤返回 Artifact 列表；每个产物依次发出一条 `step.artifact`（`key` 相同、`path`/`hash` 不同），缓存键包含列表内全部产物哈希。
- 确定性步骤默认启用缓存；命中时该步 `cached=true`，并照常发出 `step.artifact`。
- `pipeline.run.inputs` 会注入步骤上下文（首个输入可供 `media.probe` 直接读取），步骤也可用 `options.source` 显式覆盖。

## 7. 事件

引擎通过 notification 推送：

```json
{"jsonrpc":"2.0","method":"event","params":{
  "event_id":"evt_000042",
  "run_id":"run_1a2b3c4d",
  "project_id":null,
  "seq":42,
  "type":"step.progress",
  "step":"demo",
  "percent":0.42,
  "message":"示例进度 42%",
  "ts":"2026-11-17T12:00:00Z"
}}
```

| type | 附加字段 | 触发时机 |
|---|---|---|
| `run.started` | `recipe_id` | run 开始执行 |
| `step.started` | `step` | 单步开始 |
| `step.progress` | `step, percent, message?` | 步骤上报进度（0~1） |
| `step.log` | `step, level, message` | 步骤日志；`level`：`debug/info/warning/error` |
| `step.artifact` | `step, key, path, kind` | 产物落盘（M1 起） |
| `step.failed` | `step, error{code,message,data?}` | 步骤失败 |
| `run.finished` | `status, duration_ms` | run 结束，`status = done / failed / cancelled` |
| `review.requested` | `run_id, step, review_id, items` | 等待人工审核（M5）；run 状态转 `waiting_review` |
| `review.resolved` | `run_id, step, review_id` | 审核提交完成（M5）；随后 run 恢复执行 |
| `project.updated` | `project` | 项目状态变化（M3） |

约定：

- `seq` 在单个 run 内从 1 单调递增；前端按 `(run_id, seq)` 去重、排序。
- `event_id` 全局唯一（`evt_` + 序号），便于日志关联。
- 事件只描述状态，不携带完整字幕文本（避免大消息与隐私泄露）。
- 断线/重连后，前端调用 `job.status` 做全量刷新。

## 8. 人工审核（HITL）

审核**不是**阻塞式长请求，而是持久化状态（M5）：

1. `human.review` 写入待审项，run 状态置 `waiting_review`。
2. 引擎发 `review.requested`。
3. UI 调 `review.list`，在 diff 界面逐条处理。
4. UI 调 `review.submit`，引擎恢复 run。
5. 应用重启后 `project.list` 仍能看到 `waiting_review`。

断点续跑（M5 实现）：

- 暂停时 run、已完成步骤产物、配方、运行选项写入 SQLite（`run_state` 表）；
  引擎重启后 `job.status` / `review.list` 仍可查询。
- `review.submit` 后 `human.review` 重新执行一次：读取决策、应用文本修改、
  写审计 JSONL，再继续下游步骤。上游已完成步骤不会重算。
- 未在 `decisions` 中出现的审核项默认**拒绝**（保持原文），避免静默删除。
- `review.undo` 按 `reviews/audit-<run_id>.jsonl` 中的 `before` 生成撤销副本，
  返回新产物路径；原内容寻址产物不被修改。

审核项：

```json
{
  "id":"rev_ab12cd34_0000",
  "review_id":"rv_ab12cd34ef",
  "review_status":"pending",
  "status":"pending",
  "segment_index":12,
  "start_ms":5400,
  "end_ms":7100,
  "before":"[door slams]",
  "after":"",
  "action":"remove",
  "confidence":0.93,
  "reason":"bracketed",
  "reasons":["bracketed"],
  "source":"rules",
  "file":"EP01",
  "artifact_hash":"sha256..."
}
```

决策：

```json
{"id":"rev_ab12cd34_0000","action":"accept","after":null}
```

- `action` 只能是 `accept` / `reject`；`after` 非空时表示人工改写后的文本。
- 接受 `remove` 时把该段文本置空但保留时间轴；时间轴永不被审核修改。

## 9. 版本与兼容

- `protocol` 是整数；破坏性变更必须递增。
- 新增可选字段、事件类型不算破坏性变更；前端必须忽略未知字段。
- 引擎能力通过 `capabilities` 声明，前端据此隐藏入口，而不是靠版本号猜测。
- 引擎 `--version` 与 `engine.hello.version` 保持一致（`version.py` 单一来源）。

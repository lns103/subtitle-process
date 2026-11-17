# 引擎协议规范（v1）

> 适用：`engine/`（Python sidecar）↔ `apps/desktop/src-tauri`（Rust supervisor）↔ React 前端
> 版本：协议 `1`，随 `engine/src/subtitle_engine/version.py::PROTOCOL_VERSION` 递增
> 最后更新：2026-11-17（M0）

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
- `capabilities` 目前为 `["pipeline"]`；M5/M6 增加 `review` / `agent`。

## 4. 方法表

状态列：**M0** = 已实现并通过测试；后续里程碑逐步补齐。

| 方法 | 参数 | 返回 | 状态 | 说明 |
|---|---|---|---|---|
| `engine.hello` | `client?, protocol?` | `EngineInfo` | M0 | 握手 |
| `engine.shutdown` | `{}` | `"ok"` | M0 | 优雅退出；响应发出后进程退出 |
| `steps.list` | `{}` | `StepSpec[]` | M0 | 步骤目录 + Options JSON Schema |
| `pipeline.run` | `recipe?, inputs?, project_id?` | `{job_id, run_id}` | M0（最小） | 启动；省略 `recipe` 时运行内置示例 |
| `job.status` | `job_id` | `Run` | M0 | 查询运行状态 |
| `job.cancel` | `job_id` | `"ok"` | M0 | 取消并杀子进程树 |
| `recipes.list` | `{}` | `RecipeSummary[]` | M3 | 预设 + 用户配方 |
| `recipes.get` | `id` | `Recipe` | M3 | 读取 |
| `recipes.save` | `recipe` | `Recipe` | M3 | 保存用户配方 |
| `recipes.delete` | `id` | `"ok"` | M3 | 只允许删用户配方 |
| `pipeline.validate` | `recipe` | `ValidationResult` | M3 | 环、端口、必填、路径冲突 |
| `project.list` | `{}` | `ProjectSummary[]` | M3 | 项目库 |
| `project.get` | `id` | `Project` | M3 | 详情 |
| `project.delete` | `id` | `"ok"` | M3 | 删除工作区 |
| `review.list` | `run_id` | `ReviewItem[]` | M5 | 待审项 |
| `review.submit` | `run_id, decisions` | `"ok"` | M5 | 提交审核结果 |
| `artifact.reveal` | `path` | `"ok"` | M3 | 资源管理器打开 |
| `settings.get` | `{}` | `Settings` | M6 | 读取设置 |
| `settings.set` | `settings` | `Settings` | M6 | 保存设置 |
| `secrets.set` | `name, value` | `"ok"` | M6 | 写入系统钥匙串 |
| `agent.test` | `{}` | `{ok, latency_ms}` | M6 | 测试 API 连通性 |

### 4.1 `pipeline.run`（M0 行为）

- `recipe`：完整配方对象，见第 6 节；省略时运行内置 `demo` 配方（单步 `demo.tick`）。
- `inputs`：字符串路径数组，原样传给步骤上下文，M0 不复制文件。
- 立即返回 `{job_id, run_id}`；M0 二者相同，后续可能拆分。
- 同一项目并发限制、全局并发限制在 M1 实现，超出返回 `1004`。
- 配方校验失败返回 `1001`，不会创建 run。

### 4.2 `job.status` 返回

```json
{
  "id":"run_1a2b3c4d",
  "project_id":null,
  "recipe_id":"demo",
  "status":"running",
  "steps":[
    {"id":"demo","uses":"demo.tick","status":"running","progress":0.4}
  ],
  "started_at":"2026-11-17T12:00:00.123456Z"
}
```

- `status`：`queued | running | waiting_review | done | failed | cancelled`
- 步骤 `status`：`idle | queued | running | done | failed | skipped | waiting_review | cancelled`
- 时间字段为 ISO 8601 UTC；未发生的字段省略（`exclude_none`）。

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
- 端口 `kind` 取值：`srt` / `ass` / `vtt` / `media_info` / `subtitle_doc` / `review` / `any`。
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

M0 执行约定：

- 步骤按数组顺序执行；`needs` 在 M1 参与拓扑排序。
- `when` 条件表达式在 M0 遇到即报 `-32602`（明确失败，不静默跳过）。
- `with` 即 `options`；`ui` 仅前端使用，执行前可剥离。

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
| `review.requested` | `run_id, review_id, items` | 等待人工审核（M5） |
| `review.resolved` | `review_id` | 审核提交完成（M5） |
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

审核项：

```json
{
  "id":"rev_0012",
  "segment_index":12,
  "start_ms":5400,
  "end_ms":7100,
  "before":"[door slams]",
  "after":"",
  "action":"remove",
  "confidence":0.93,
  "reason":"bracketed sound effect",
  "source":"agent"
}
```

## 9. 版本与兼容

- `protocol` 是整数；破坏性变更必须递增。
- 新增可选字段、事件类型不算破坏性变更；前端必须忽略未知字段。
- 引擎能力通过 `capabilities` 声明，前端据此隐藏入口，而不是靠版本号猜测。
- 引擎 `--version` 与 `engine.hello.version` 保持一致（`version.py` 单一来源）。

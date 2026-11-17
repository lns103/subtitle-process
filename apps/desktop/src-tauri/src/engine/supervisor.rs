//! sidecar 监督器：spawn、握手、请求/响应匹配、崩溃重启、优雅退出。
//!
//! 红线：stdout 只解析 JSON-RPC；解析失败只记录截断日志，绝不崩溃。

use std::collections::{HashMap, VecDeque};
use std::env;
use std::future::Future;
use std::path::PathBuf;
use std::pin::Pin;
use std::process::Stdio;
use std::sync::atomic::{AtomicBool, AtomicU64, Ordering};
use std::sync::Arc;
use std::time::{Duration, Instant};

use serde::Serialize;
use serde_json::{json, Value};
use tauri::{AppHandle, Emitter};
use tokio::io::{AsyncBufReadExt, AsyncWriteExt, BufReader};
use tokio::process::{Child, ChildStdin, ChildStdout, Command};
use tokio::sync::{oneshot, Mutex, RwLock};
use tokio::time::timeout;

use super::protocol::{classify, Incoming, RpcErrorObject};

const HANDSHAKE_TIMEOUT: Duration = Duration::from_secs(10);
const SHUTDOWN_GRACE: Duration = Duration::from_secs(2);
const RESTART_WINDOW: Duration = Duration::from_secs(60);
const MAX_RESTARTS: usize = 3;
const RESTART_DELAY: Duration = Duration::from_millis(500);
const DEFAULT_REQUEST_TIMEOUT_MS: u64 = 30_000;
const MAX_LOG_LINE_CHARS: usize = 1024;

#[cfg(windows)]
const CREATE_NO_WINDOW: u32 = 0x0800_0000;

/// 引擎状态，直接序列化给前端（``{state: ...}``）。
#[derive(Debug, Clone, Serialize, PartialEq)]
#[serde(tag = "state", rename_all = "snake_case")]
pub enum EngineStatus {
    Starting,
    Ready {
        version: String,
        protocol: i64,
        python: String,
    },
    Failed {
        message: String,
    },
    Stopped,
}

struct PendingMap(HashMap<u64, oneshot::Sender<Result<Value, RpcErrorObject>>>);

pub struct Supervisor {
    app: AppHandle,
    status: RwLock<EngineStatus>,
    child: Mutex<Option<Child>>,
    stdin: Mutex<Option<ChildStdin>>,
    pending: Mutex<PendingMap>,
    next_id: AtomicU64,
    /// 每次启动递增；用于识别旧进程的 stdout 关闭事件，避免手动重启被
    /// “崩溃自动重启”链路再次杀掉新进程。
    generation: AtomicU64,
    restarts: Mutex<VecDeque<Instant>>,
    shutting_down: AtomicBool,
    restart_lock: Mutex<()>,
}

impl Supervisor {
    pub fn new(app: AppHandle) -> Self {
        Self {
            app,
            status: RwLock::new(EngineStatus::Starting),
            child: Mutex::new(None),
            stdin: Mutex::new(None),
            pending: Mutex::new(PendingMap(HashMap::new())),
            next_id: AtomicU64::new(1),
            generation: AtomicU64::new(0),
            restarts: Mutex::new(VecDeque::new()),
            shutting_down: AtomicBool::new(false),
            restart_lock: Mutex::new(()),
        }
    }

    /// 启动并握手；失败只记录状态，不 panic，前端可手动重启。
    pub async fn start(self: &Arc<Self>) {
        if let Err(err) = self.boot().await {
            log::error!("引擎启动失败: {err}");
            self.set_status(EngineStatus::Failed { message: err }).await;
        }
    }

    pub async fn status(&self) -> EngineStatus {
        self.status.read().await.clone()
    }

    pub async fn request(
        &self,
        method: &str,
        params: Value,
        wait: Duration,
    ) -> Result<Value, RpcErrorObject> {
        let id = self.next_id.fetch_add(1, Ordering::SeqCst);
        let (tx, rx) = oneshot::channel();
        self.pending.lock().await.0.insert(id, tx);

        let payload = json!({
            "jsonrpc": "2.0",
            "id": id,
            "method": method,
            "params": params,
        });
        let mut line = serde_json::to_vec(&payload).map_err(|err| RpcErrorObject {
            code: -32603,
            message: format!("请求序列化失败: {err}"),
            data: None,
        })?;
        line.push(b'\n');

        let write_error = {
            let mut guard = self.stdin.lock().await;
            match guard.as_mut() {
                Some(stdin) => match stdin.write_all(&line).await {
                    Ok(()) => match stdin.flush().await {
                        Ok(()) => None,
                        Err(err) => Some(format!("写入引擎 stdin 失败: {err}")),
                    },
                    Err(err) => Some(format!("写入引擎 stdin 失败: {err}")),
                },
                None => Some("引擎未运行".to_string()),
            }
        };
        if let Some(message) = write_error {
            self.pending.lock().await.0.remove(&id);
            return Err(RpcErrorObject {
                code: -32603,
                message,
                data: None,
            });
        }

        match timeout(wait, rx).await {
            Ok(Ok(result)) => result,
            Ok(Err(_)) => Err(RpcErrorObject {
                code: -32603,
                message: "引擎连接已关闭".into(),
                data: None,
            }),
            Err(_) => {
                self.pending.lock().await.0.remove(&id);
                Err(RpcErrorObject {
                    code: -32603,
                    message: format!("请求超时: {method}"),
                    data: None,
                })
            }
        }
    }

    pub async fn restart(self: &Arc<Self>) -> Result<(), String> {
        let _guard = self.restart_lock.lock().await;
        // 先递增 generation：旧进程接下来产生的 stdout 关闭事件会被忽略，
        // 不会在 restart_lock 释放后反过来重启刚拉起的新进程。
        self.generation.fetch_add(1, Ordering::SeqCst);
        self.cleanup_process().await;
        self.restarts.lock().await.clear();
        self.shutting_down.store(false, Ordering::SeqCst);
        self.boot().await
    }

    pub async fn shutdown(self: &Arc<Self>) {
        if self.shutting_down.swap(true, Ordering::SeqCst) {
            return;
        }
        // 先尝试优雅退出，超时后杀进程树（含 ffmpeg 等子进程）。
        let _ = timeout(
            SHUTDOWN_GRACE,
            self.request("engine.shutdown", json!({}), SHUTDOWN_GRACE),
        )
        .await;

        let mut child_guard = self.child.lock().await;
        if let Some(child) = child_guard.as_mut() {
            let pid = child.id();
            if timeout(SHUTDOWN_GRACE, child.wait()).await.is_err() {
                if let Some(pid) = pid {
                    kill_process_tree(pid);
                }
                let _ = child.kill().await;
                let _ = child.wait().await;
            }
        }
        *child_guard = None;
        *self.stdin.lock().await = None;
        self.fail_pending("引擎已关闭").await;
        self.set_status(EngineStatus::Stopped).await;
    }

    // ---- 内部 ---------------------------------------------------------

    // 重启路径里 boot 会被间接再次调用（stdout 关闭 → schedule_restart → boot），
    // 用装箱 future 打断 async 递归的类型环。
    fn boot(
        self: &Arc<Self>,
    ) -> Pin<Box<dyn Future<Output = Result<(), String>> + Send + '_>> {
        Box::pin(self.boot_inner())
    }

    async fn boot_inner(self: &Arc<Self>) -> Result<(), String> {
        self.set_status(EngineStatus::Starting).await;
        let mut cmd = build_engine_command()?;
        cmd.stdin(Stdio::piped())
            .stdout(Stdio::piped())
            .stderr(Stdio::piped());
        #[cfg(windows)]
        {
            cmd.creation_flags(CREATE_NO_WINDOW);
        }

        // 本次启动的代号；stdout 关闭时只有代号仍是最新的才允许触发自动重启。
        let generation = self.generation.fetch_add(1, Ordering::SeqCst) + 1;

        let mut child = cmd
            .spawn()
            .map_err(|err| format!("无法启动引擎进程: {err}"))?;
        let stdin = child.stdin.take();
        let stdout = child.stdout.take();
        let stderr = child.stderr.take();

        *self.child.lock().await = Some(child);
        *self.stdin.lock().await = stdin;

        if let Some(stdout) = stdout {
            tokio::spawn(read_stdout(self.clone(), stdout, generation));
        }
        if let Some(stderr) = stderr {
            tokio::spawn(read_stderr(self.clone(), stderr));
        }

        let hello = timeout(
            HANDSHAKE_TIMEOUT,
            self.request(
                "engine.hello",
                json!({"client": "subtitle-desktop", "protocol": 1}),
                HANDSHAKE_TIMEOUT,
            ),
        )
        .await
        .map_err(|_| "引擎握手超时（10s）".to_string())?
        .map_err(|err| format!("引擎握手失败: {err}"))?;

        let version = hello
            .get("version")
            .and_then(Value::as_str)
            .unwrap_or("unknown")
            .to_string();
        let protocol = hello.get("protocol").and_then(Value::as_i64).unwrap_or(1);
        let python = hello
            .get("python")
            .and_then(Value::as_str)
            .unwrap_or("unknown")
            .to_string();
        if protocol != 1 {
            log::warn!("引擎协议版本 {protocol} 与壳不一致（期望 1），前端会阻止运行");
        }
        self.set_status(EngineStatus::Ready {
            version,
            protocol,
            python,
        })
        .await;
        Ok(())
    }

    async fn set_status(&self, status: EngineStatus) {
        *self.status.write().await = status.clone();
        if let Err(err) = self.app.emit("engine:status", &status) {
            log::warn!("转发引擎状态失败: {err}");
        }
    }

    async fn fail_pending(&self, reason: &str) {
        let drained: Vec<_> = self.pending.lock().await.0.drain().collect();
        for (_, tx) in drained {
            let _ = tx.send(Err(RpcErrorObject {
                code: -32603,
                message: reason.to_string(),
                data: None,
            }));
        }
    }

    async fn cleanup_process(&self) {
        self.fail_pending("引擎进程已重启").await;
        *self.stdin.lock().await = None;
        if let Some(mut child) = self.child.lock().await.take() {
            if let Some(pid) = child.id() {
                kill_process_tree(pid);
            }
            let _ = child.kill().await;
            let _ = child.wait().await;
        }
    }

    /// stdout 关闭 = 进程退出（或崩溃）。只有当前 generation 的进程才允许
    /// 触发重启；旧进程的关闭事件在主动重启/关机时必须被丢弃。
    async fn on_stdout_closed(self: &Arc<Self>, generation: u64) {
        if !should_restart(
            self.shutting_down.load(Ordering::SeqCst),
            self.generation.load(Ordering::SeqCst),
            generation,
        ) {
            log::debug!("忽略旧引擎进程（generation {generation}）的退出事件");
            return;
        }
        log::warn!("引擎 stdout 已关闭，准备按策略重启");
        *self.stdin.lock().await = None;
        self.fail_pending("引擎意外退出").await;
        self.set_status(EngineStatus::Stopped).await;
        self.schedule_restart(generation).await;
    }

    async fn schedule_restart(self: &Arc<Self>, generation: u64) {
        let this = self.clone();
        tokio::spawn(async move {
            let _guard = this.restart_lock.lock().await;
            if this.shutting_down.load(Ordering::SeqCst) {
                return;
            }
            // 排队期间可能发生了手动重启；旧 generation 的自动重启必须放弃。
            if this.generation.load(Ordering::SeqCst) != generation {
                log::debug!("丢弃过期的自动重启任务（generation {generation}）");
                return;
            }
            {
                let mut history = this.restarts.lock().await;
                let now = Instant::now();
                while history
                    .front()
                    .is_some_and(|at| now.duration_since(*at) > RESTART_WINDOW)
                {
                    history.pop_front();
                }
                if history.len() >= MAX_RESTARTS {
                    let message = format!(
                        "引擎在 {} 秒内崩溃 {} 次，已停止自动重启",
                        RESTART_WINDOW.as_secs(),
                        MAX_RESTARTS
                    );
                    log::error!("{message}");
                    drop(history);
                    this.set_status(EngineStatus::Failed { message }).await;
                    return;
                }
                history.push_back(now);
            }

            tokio::time::sleep(RESTART_DELAY).await;
            if this.shutting_down.load(Ordering::SeqCst)
                || this.generation.load(Ordering::SeqCst) != generation
            {
                return;
            }
            this.cleanup_process().await;
            if let Err(err) = this.boot().await {
                log::error!("引擎重启失败: {err}");
                this.set_status(EngineStatus::Failed { message: err }).await;
            }
        });
    }
}

async fn read_stdout(supervisor: Arc<Supervisor>, stdout: ChildStdout, generation: u64) {
    let mut lines = BufReader::new(stdout).lines();
    loop {
        match lines.next_line().await {
            Ok(Some(line)) => handle_stdout_line(&supervisor, &line).await,
            Ok(None) => break,
            Err(err) => {
                log::warn!("读取引擎 stdout 失败: {err}");
                break;
            }
        }
    }
    supervisor.on_stdout_closed(generation).await;
}

async fn handle_stdout_line(supervisor: &Arc<Supervisor>, line: &str) {
    match classify(line) {
        Ok(Incoming::Response { id, result }) => {
            let sender = supervisor.pending.lock().await.0.remove(&id);
            match sender {
                Some(tx) => {
                    let _ = tx.send(result);
                }
                None => log::warn!("收到未知请求 id 的响应: {id}"),
            }
        }
        Ok(Incoming::Event { params }) => {
            if let Err(err) = supervisor.app.emit("engine:event", &params) {
                log::warn!("转发引擎事件失败: {err}");
            }
        }
        Ok(Incoming::Other { raw_method }) => {
            log::debug!("忽略不认识的引擎消息: {raw_method:?}");
        }
        Err(err) => {
            let preview: String = line.chars().take(MAX_LOG_LINE_CHARS).collect();
            log::warn!("引擎 stdout 不是合法 JSON: {err}; raw={preview}");
        }
    }
}

async fn read_stderr(supervisor: Arc<Supervisor>, stderr: tokio::process::ChildStderr) {
    let mut lines = BufReader::new(stderr).lines();
    loop {
        match lines.next_line().await {
            Ok(Some(line)) => {
                let preview: String = line.chars().take(MAX_LOG_LINE_CHARS).collect();
                log::info!("engine stderr: {preview}");
                let payload = json!({ "line": preview, "level": "info" });
                if let Err(err) = supervisor.app.emit("engine:log", &payload) {
                    log::warn!("转发引擎日志失败: {err}");
                }
            }
            Ok(None) => break,
            Err(err) => {
                log::warn!("读取引擎 stderr 失败: {err}");
                break;
            }
        }
    }
}

fn build_engine_command() -> Result<Command, String> {
    // 1) 显式覆盖（测试 / 自定义路径）
    if let Ok(explicit) = env::var("SUBTITLE_ENGINE_BIN") {
        let mut cmd = Command::new(explicit);
        cmd.args(["--rpc", "stdio"]);
        return Ok(cmd);
    }

    // 2) 打包后：与主程序同目录的 sidecar
    if let Ok(exe) = env::current_exe()
        && let Some(dir) = exe.parent()
    {
        let candidate = dir.join("subtitle-engine.exe");
        if candidate.exists() {
            let mut cmd = Command::new(candidate);
            cmd.args(["--rpc", "stdio"]);
            return Ok(cmd);
        }
    }

    // 3) 开发模式：uv run python -m subtitle_engine --rpc stdio
    let engine_dir = find_engine_dir()
        .ok_or_else(|| "找不到 engine/ 目录，且没有可用的 sidecar 二进制".to_string())?;
    let uv = env::var("SUBTITLE_UV").unwrap_or_else(|_| "uv".to_string());
    let mut cmd = Command::new(uv);
    cmd.args(["run", "python", "-m", "subtitle_engine", "--rpc", "stdio"])
        .current_dir(engine_dir);
    Ok(cmd)
}

fn find_engine_dir() -> Option<PathBuf> {
    if let Ok(dir) = env::var("SUBTITLE_ENGINE_DIR") {
        let candidate = PathBuf::from(dir);
        if candidate.join("pyproject.toml").exists() {
            return Some(candidate);
        }
    }
    let mut dir = env::current_dir().ok()?;
    loop {
        let candidate = dir.join("engine");
        if candidate.join("pyproject.toml").exists() {
            return Some(candidate);
        }
        if !dir.pop() {
            return None;
        }
    }
}

#[allow(dead_code)]
pub fn default_request_timeout() -> Duration {
    Duration::from_millis(DEFAULT_REQUEST_TIMEOUT_MS)
}

/// 退出事件是否属于当前引擎进程；主动重启/关机产生的旧事件必须忽略。
fn should_restart(shutting_down: bool, current_generation: u64, event_generation: u64) -> bool {
    !shutting_down && current_generation == event_generation
}

#[cfg(windows)]
fn kill_process_tree(pid: u32) {
    use std::os::windows::process::CommandExt;
    let _ = std::process::Command::new("taskkill")
        .args(["/PID", &pid.to_string(), "/T", "/F"])
        .creation_flags(CREATE_NO_WINDOW)
        .output();
}

#[cfg(not(windows))]
fn kill_process_tree(pid: u32) {
    let _ = std::process::Command::new("kill")
        .args(["-9", &pid.to_string()])
        .output();
}

#[cfg(test)]
mod tests {
    use super::should_restart;

    #[test]
    fn stale_generation_never_restarts() {
        // 手动重启前启动的进程（gen 3）在 gen 4 启动后才关闭，必须忽略。
        assert!(!should_restart(false, 4, 3));
    }

    #[test]
    fn current_generation_restarts_on_crash() {
        assert!(should_restart(false, 4, 4));
    }

    #[test]
    fn shutdown_never_restarts() {
        assert!(!should_restart(true, 4, 4));
    }
}

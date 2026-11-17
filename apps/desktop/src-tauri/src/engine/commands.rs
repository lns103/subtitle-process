//! 暴露给前端的 Tauri 命令。

use std::sync::Arc;
use std::time::Duration;

use serde_json::{json, Value};
use tauri::{AppHandle, State};
use tauri_plugin_dialog::DialogExt;

use super::protocol::RpcErrorObject;
use super::supervisor::{EngineStatus, Supervisor};

const DEFAULT_TIMEOUT_MS: u64 = 30_000;

#[tauri::command]
pub async fn engine_status(
    supervisor: State<'_, Arc<Supervisor>>,
) -> Result<EngineStatus, String> {
    Ok(supervisor.status().await)
}

/// 泛型业务入口：所有引擎方法都走这里，不为每个方法写一个 Rust 命令。
#[tauri::command]
pub async fn engine_call(
    supervisor: State<'_, Arc<Supervisor>>,
    method: String,
    params: Option<Value>,
    timeout_ms: Option<u64>,
) -> Result<Value, RpcErrorObject> {
    let wait = Duration::from_millis(timeout_ms.unwrap_or(DEFAULT_TIMEOUT_MS));
    supervisor
        .request(&method, params.unwrap_or_else(|| json!({})), wait)
        .await
}

#[tauri::command]
pub async fn engine_restart(supervisor: State<'_, Arc<Supervisor>>) -> Result<(), String> {
    supervisor.restart().await
}

#[tauri::command]
pub async fn pick_files(app: AppHandle) -> Result<Vec<String>, String> {
    let picked = app
        .dialog()
        .file()
        .add_filter(
            "媒体与字幕",
            &["mkv", "mp4", "mov", "avi", "ts", "srt", "ass", "vtt"],
        )
        .blocking_pick_files();
    Ok(picked
        .unwrap_or_default()
        .into_iter()
        .filter_map(|path| path.into_path().ok())
        .map(|path| path.to_string_lossy().into_owned())
        .collect())
}

#[tauri::command]
pub async fn pick_folder(app: AppHandle) -> Result<Option<String>, String> {
    Ok(app
        .dialog()
        .file()
        .blocking_pick_folder()
        .and_then(|path| path.into_path().ok())
        .map(|path| path.to_string_lossy().into_owned()))
}

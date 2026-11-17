//! 应用内更新：仅提供「检查更新」命令，下载与安装交给前端 updater 插件 API。
//!
//! 更新源、公钥在 `tauri.conf.json` 的 `plugins.updater` 中配置；这里不做任何网络兜底，
//! 失败原样返回给前端展示（不静默吞异常）。

use serde::Serialize;
use tauri::{AppHandle, Manager};
use tauri_plugin_updater::UpdaterExt;

/// 检查结果，序列化给前端（camelCase，便于 React 侧直接使用）。
#[derive(Debug, Clone, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct UpdateInfo {
    /// 是否存在比当前版本更新的发布。
    pub available: bool,
    /// 当前运行版本（来自 tauri.conf.json / package_info）。
    pub current_version: String,
    /// 远端最新版本，无更新时为 None。
    pub version: Option<String>,
    /// 发布说明（更新清单中的 notes/body）。
    pub notes: Option<String>,
    /// 发布时间（RFC3339 或更新器原始字符串），无更新时为 None。
    pub published_at: Option<String>,
}

/// 检查是否有可用更新。前端调用示例：
/// `invoke<UpdateInfo>("check_for_updates")`。
#[tauri::command]
pub async fn check_for_updates(app: AppHandle) -> Result<UpdateInfo, String> {
    let current_version = app.package_info().version.to_string();

    // 未配置有效 endpoints/pubkey 时会在此返回可读错误，前端据此提示「更新未配置」。
    let updater = app
        .updater()
        .map_err(|err| format!("初始化更新器失败: {err}"))?;

    let update = updater
        .check()
        .await
        .map_err(|err| format!("检查更新失败: {err}"))?;

    Ok(match update {
        Some(update) => UpdateInfo {
            available: true,
            current_version,
            version: Some(update.version.clone()),
            notes: update.body.clone(),
            published_at: update.date.map(|date| date.to_string()),
        },
        None => UpdateInfo {
            available: false,
            current_version,
            version: None,
            notes: None,
            published_at: None,
        },
    })
}

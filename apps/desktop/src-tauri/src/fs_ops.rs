//! 文件系统相关命令：打开产物位置。

use std::path::Path;

use tauri::AppHandle;
use tauri_plugin_opener::OpenerExt;

#[tauri::command]
pub async fn reveal_path(app: AppHandle, path: String) -> Result<(), String> {
    if Path::new(&path).is_dir() {
        // 目录直接打开，而不是在父目录中选中它。
        return app
            .opener()
            .open_path(path, None::<String>)
            .map_err(|err| format!("打开文件夹失败: {err}"));
    }
    app.opener()
        .reveal_item_in_dir(path)
        .map_err(|err| format!("打开路径失败: {err}"))
}

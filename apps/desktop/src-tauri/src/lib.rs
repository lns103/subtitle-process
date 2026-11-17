mod engine;
mod fs_ops;
mod updater;

use std::sync::Arc;

use tauri::Manager;

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    #[allow(unused_mut)]
    let mut builder = tauri::Builder::default();

    // 单实例插件必须最先注册：第二个实例启动时只把已有窗口带到前台，然后自身退出。
    #[cfg(desktop)]
    {
        builder = builder.plugin(tauri_plugin_single_instance::init(
            |app, _argv, _cwd| {
                if let Some(window) = app.get_webview_window("main") {
                    let _ = window.unminimize();
                    let _ = window.show();
                    let _ = window.set_focus();
                } else {
                    log::warn!("收到第二实例请求，但主窗口尚未创建");
                }
            },
        ));
    }

    builder
        .plugin(tauri_plugin_opener::init())
        .plugin(tauri_plugin_dialog::init())
        // store：前端设置/草稿持久化（路径由前端通过 `load()` 指定）。
        .plugin(tauri_plugin_store::Builder::new().build())
        // updater：更新源与公钥见 tauri.conf.json 的 plugins.updater。
        .plugin(tauri_plugin_updater::Builder::new().build())
        .setup(|app| {
            // 先注册状态，保证前端任何时刻都能查到 engine_status。
            let supervisor = Arc::new(engine::Supervisor::new(app.handle().clone()));
            app.manage(supervisor.clone());
            tauri::async_runtime::spawn(async move {
                supervisor.start().await;
            });
            Ok(())
        })
        .invoke_handler(tauri::generate_handler![
            engine::commands::engine_status,
            engine::commands::engine_call,
            engine::commands::engine_restart,
            engine::commands::pick_files,
            engine::commands::pick_folder,
            fs_ops::reveal_path,
            updater::check_for_updates,
        ])
        .build(tauri::generate_context!())
        .expect("error while building tauri application")
        .run(|app, event| {
            if let tauri::RunEvent::Exit = event
                && let Some(supervisor) = app.try_state::<Arc<engine::Supervisor>>()
            {
                tauri::async_runtime::block_on(supervisor.shutdown());
            }
        });
}

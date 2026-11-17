mod engine;
mod fs_ops;

use std::sync::Arc;

use tauri::Manager;

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    tauri::Builder::default()
        .plugin(tauri_plugin_opener::init())
        .plugin(tauri_plugin_dialog::init())
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

# 桌面壳：打包 / 自动更新 / 单实例

> 本文件只记录配置约定，不参与构建。真正的开关在
> `apps/desktop/src-tauri/tauri.conf.json`、`Cargo.toml` 与 `capabilities/default.json`。

## 1. Sidecar（Python 引擎）

- `bundle.externalBin: ["binaries/subtitle-engine"]`
- 先运行仓库根脚本生成带 triple 后缀的二进制：

  ```powershell
  pwsh scripts/build-engine.ps1
  # 或强制 PyInstaller onedir（仅本地调试）
  pwsh scripts/build-engine.ps1 -Fallback
  ```

- 产物：`apps/desktop/src-tauri/binaries/subtitle-engine-<target-triple>.exe`
- 该目录已被 `.gitignore` 忽略，发布包由 CI 现场构建。
- `engine/supervisor.rs` 在运行期查找与主程序同目录的 `subtitle-engine.exe`；
  Tauri 打包时会自动去掉 triple 后缀并放到主程序同级目录。

## 2. 自动更新（tauri-plugin-updater）

`tauri.conf.json` 中当前是**占位配置**，发布前必须替换：

```jsonc
"plugins": {
  "updater": {
    // 占位地址，替换为真实更新清单服务（或 GitHub Releases 的 latest.json）
    "endpoints": [
      "https://example.com/subtitle-process/{{target}}/{{arch}}/{{current_version}}"
    ],
    // 占位值，替换为 tauri signer generate 生成的公钥
    "pubkey": "REPLACE_WITH_PUBKEY_FROM_TAURI_SIGNER_GENERATE"
  }
}
```

生成签名密钥（私钥勿入库，放 CI secret）：

```powershell
npx tauri signer generate -w "$env:USERPROFILE\.tauri\subtitle-process.key"
```

签名与构建：

```powershell
$env:TAURI_SIGNING_PRIVATE_KEY = Get-Content "$env:USERPROFILE\.tauri\subtitle-process.key" -Raw
$env:TAURI_SIGNING_PRIVATE_KEY_PASSWORD = "<password>"
cd apps/desktop
npm run tauri build
```

- `bundle.createUpdaterArtifacts: true` 会额外生成 `.sig` 与更新清单所需的产物。
- updater 插件 v2 的配置字段只有 `endpoints` / `pubkey` / `windows` /
  `dangerous*` / `require_signed_version` / `allow_downgrades`；
  **没有 `dialog` 字段**（v1 遗留），因此这里省略，弹窗完全由前端控制。
- 前端可用 `invoke("check_for_updates")` 获取 `{ available, currentVersion,
  version, notes, publishedAt }`，或用 `@tauri-apps/plugin-updater` 的 `check()`。

## 3. 权限（capabilities）

`capabilities/default.json` 已加入：

- `dialog:default`：前端文件选择（现有 Rust 命令不依赖它，但保留 JS 侧能力）
- `store:default`：`@tauri-apps/plugin-store`
- `updater:default`：`check` / `download` / `install`

新增 Tauri 插件后首次 `npm run tauri build` 会重新生成
`gen/schemas/desktop-schema.json`，若编辑器提示未知 permission，先构建一次即可。

## 4. 单实例与崩溃恢复

- `tauri-plugin-single-instance` 在 `lib.rs` 中**第一个注册**。第二个实例启动时
  回调会 `show()` + `unminimize()` + `set_focus()` 主窗口，随后第二实例自行退出。
- 引擎崩溃恢复仍由 `src/engine/supervisor.rs` 负责：stdout 关闭即视为进程退出，
  60 秒窗口内最多自动重启 3 次，超过后状态置为 `failed` 并等前端手动重启。
  M7 未改动该逻辑。

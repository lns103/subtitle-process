import { getVersion } from "@tauri-apps/api/app";

/**
 * Vite 在构建时注入的 package.json 版本；测试环境没有该常量时回退到占位值。
 * 这里只做展示，不参与任何版本比较。
 */
function bundledVersion(): string {
  return typeof __APP_VERSION__ === "string" && __APP_VERSION__
    ? __APP_VERSION__
    : "0.0.0-dev";
}

/** 优先使用 Tauri 应用版本；浏览器 / 测试环境使用构建时注入的版本。 */
export async function getAppVersion(): Promise<string> {
  try {
    const version = await getVersion();
    if (version.trim()) return version;
  } catch {
    // 非 Tauri 环境（浏览器 / vitest）没有 app 接口，回退到打包版本。
  }
  return bundledVersion();
}

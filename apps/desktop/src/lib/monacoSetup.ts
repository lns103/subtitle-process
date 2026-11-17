import { loader } from "@monaco-editor/react";
// 只引入编辑器核心：审核页仅用 plaintext diff，避免打包全部语言与 worker。
import * as monaco from "monaco-editor/editor/editor.api";
import EditorWorker from "monaco-editor/editor/editor.worker?worker";

let configured = false;

/** 离线打包 Monaco：使用本地 worker，不依赖 CDN。 */
export function setupMonaco(): void {
  if (configured) return;
  configured = true;
  (self as unknown as { MonacoEnvironment?: unknown }).MonacoEnvironment = {
    getWorker: () => new EditorWorker(),
  };
  loader.config({ monaco });
}

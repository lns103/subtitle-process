/**
 * monaco-editor 的 package exports 把 ``monaco-editor/editor/editor.api``
 * 映射到 ``esm/vs/editor/editor.api.js``，但该子路径没有自带类型声明；
 * 这里复用主包类型，避免 ``tsc`` 报 TS2307。
 */
declare module "monaco-editor/editor/editor.api" {
  export * from "monaco-editor";
}

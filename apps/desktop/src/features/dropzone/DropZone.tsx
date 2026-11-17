import { useCallback, useEffect, useState } from "react";
import { getCurrentWebview } from "@tauri-apps/api/webview";
import type { UnlistenFn } from "@tauri-apps/api/event";
import { FileVideo, FolderOpen, MousePointerClick } from "lucide-react";
import { pickFiles, pickFolder } from "../../lib/rpc";

interface DropZoneProps {
  onPaths: (paths: string[]) => void;
}

/**
 * 使用 Tauri 原生拖拽事件拿真实路径（HTML5 DataTransfer 在 WebView 中不可靠）。
 */
export function DropZone({ onPaths }: DropZoneProps) {
  const [isOver, setIsOver] = useState(false);

  useEffect(() => {
    let unlisten: UnlistenFn | undefined;
    let disposed = false;

    getCurrentWebview()
      .onDragDropEvent((event) => {
        const payload = event.payload;
        if (payload.type === "over") {
          setIsOver(true);
        } else if (payload.type === "drop") {
          setIsOver(false);
          if (payload.paths.length > 0) onPaths(payload.paths);
        } else {
          setIsOver(false);
        }
      })
      .then((fn) => {
        if (disposed) fn();
        else unlisten = fn;
      })
      .catch((error) => console.error("注册拖拽事件失败", error));

    return () => {
      disposed = true;
      unlisten?.();
    };
  }, [onPaths]);

  const handlePickFiles = useCallback(async () => {
    const files = await pickFiles();
    if (files.length > 0) onPaths(files);
  }, [onPaths]);

  const handlePickFolder = useCallback(async () => {
    const folder = await pickFolder();
    if (folder) onPaths([folder]);
  }, [onPaths]);

  return (
    <section
      className={`rounded-2xl border-2 border-dashed p-10 text-center transition-colors ${
        isOver ? "border-sky-500 bg-sky-50" : "border-slate-300 bg-white"
      }`}
    >
      <MousePointerClick className="mx-auto mb-3 h-10 w-10 text-slate-400" />
      <h2 className="text-lg font-semibold text-slate-800">把视频或字幕拖进来</h2>
      <p className="mt-1 text-sm text-slate-500">
        支持 .mkv / .mp4 / .mov / .avi / .ts / .srt / .ass / .vtt；也支持文件夹
      </p>
      <div className="mt-5 flex justify-center gap-3">
        <button
          type="button"
          onClick={handlePickFiles}
          className="inline-flex items-center gap-2 rounded-lg border border-slate-300 bg-white px-3 py-2 text-sm text-slate-700 hover:bg-slate-50"
        >
          <FileVideo className="h-4 w-4" /> 选择文件
        </button>
        <button
          type="button"
          onClick={handlePickFolder}
          className="inline-flex items-center gap-2 rounded-lg border border-slate-300 bg-white px-3 py-2 text-sm text-slate-700 hover:bg-slate-50"
        >
          <FolderOpen className="h-4 w-4" /> 选择文件夹
        </button>
      </div>
    </section>
  );
}

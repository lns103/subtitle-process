import { useEffect, useState } from "react";
import { DiffEditor } from "@monaco-editor/react";
import { Loader2 } from "lucide-react";

interface DiffPanelProps {
  before: string;
  after: string;
  height?: number;
}

/** 测试环境（jsdom）下不加载 Monaco，降级为纯文本对比。 */
const MONACO_DISABLED = import.meta.env.MODE === "test";

function TextFallback({ before, after }: { before: string; after: string }) {
  return (
    <div className="grid gap-2 md:grid-cols-2">
      <div className="rounded-lg border border-slate-200 bg-slate-50 p-2">
        <p className="mb-1 text-[11px] font-medium uppercase tracking-wide text-slate-400">修改前</p>
        <pre
          data-testid="diff-before"
          className="max-h-72 overflow-auto whitespace-pre-wrap break-all font-mono text-xs text-slate-700"
        >
          {before}
        </pre>
      </div>
      <div className="rounded-lg border border-emerald-200 bg-emerald-50/50 p-2">
        <p className="mb-1 text-[11px] font-medium uppercase tracking-wide text-emerald-500">修改后</p>
        <pre
          data-testid="diff-after"
          className="max-h-72 overflow-auto whitespace-pre-wrap break-all font-mono text-xs text-emerald-900"
        >
          {after}
        </pre>
      </div>
    </div>
  );
}

export function DiffPanel({ before, after, height = 320 }: DiffPanelProps) {
  const [ready, setReady] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (MONACO_DISABLED) return;
    let cancelled = false;
    void import("../../lib/monacoSetup")
      .then(({ setupMonaco }) => {
        setupMonaco();
        if (!cancelled) setReady(true);
      })
      .catch((reason: unknown) => {
        if (!cancelled) setError(reason instanceof Error ? reason.message : String(reason));
      });
    return () => {
      cancelled = true;
    };
  }, []);

  if (MONACO_DISABLED) {
    return <TextFallback before={before} after={after} />;
  }

  if (error) {
    return (
      <div className="space-y-2">
        <p className="rounded-lg bg-amber-50 px-3 py-2 text-xs text-amber-800">
          Monaco diff 加载失败，已降级为文本对比：{error}
        </p>
        <TextFallback before={before} after={after} />
      </div>
    );
  }

  if (!ready) {
    return (
      <div
        className="flex items-center justify-center rounded-lg border border-slate-200 bg-slate-50 text-xs text-slate-500"
        style={{ height }}
      >
        <Loader2 className="mr-2 h-4 w-4 animate-spin" /> 正在加载 diff 编辑器…
      </div>
    );
  }

  return (
    <div className="overflow-hidden rounded-lg border border-slate-200">
      <DiffEditor
        height={height}
        language="plaintext"
        original={before}
        modified={after}
        theme="vs"
        options={{
          readOnly: true,
          domReadOnly: true,
          renderSideBySide: true,
          minimap: { enabled: false },
          scrollBeyondLastLine: false,
          fontSize: 13,
          automaticLayout: true,
          wordWrap: "on",
          renderOverviewRuler: false,
        }}
      />
    </div>
  );
}

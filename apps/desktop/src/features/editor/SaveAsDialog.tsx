import { useEffect, useState } from "react";
import { X } from "lucide-react";

interface SaveAsDialogProps {
  open: boolean;
  title: string;
  initialId: string;
  initialName: string;
  confirmText?: string;
  onCancel: () => void;
  onConfirm: (id: string, name: string) => void;
}

const ID_RE = /^[A-Za-z0-9][A-Za-z0-9_.-]{0,63}$/;

export function SaveAsDialog({
  open,
  title,
  initialId,
  initialName,
  confirmText = "保存",
  onCancel,
  onConfirm,
}: SaveAsDialogProps) {
  const [id, setId] = useState(initialId);
  const [name, setName] = useState(initialName);

  useEffect(() => {
    if (open) {
      setId(initialId);
      setName(initialName);
    }
  }, [open, initialId, initialName]);

  if (!open) return null;
  const idError = !ID_RE.test(id.trim())
    ? "id 只能包含字母、数字、_ . -，且不能以符号开头"
    : null;

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-slate-900/30 p-4">
      <div className="w-full max-w-md rounded-2xl border border-slate-200 bg-white shadow-xl">
        <header className="flex items-center justify-between border-b border-slate-100 px-4 py-3">
          <h2 className="text-sm font-semibold text-slate-800">{title}</h2>
          <button
            type="button"
            onClick={onCancel}
            className="rounded-lg p-1 text-slate-400 hover:bg-slate-50 hover:text-slate-600"
          >
            <X className="h-4 w-4" />
          </button>
        </header>
        <div className="space-y-3 px-4 py-4">
          <label className="block space-y-1 text-xs text-slate-600">
            <span className="font-medium">名称</span>
            <input
              autoFocus
              value={name}
              id="save-as-name"
              name="save-as-name"
              onChange={(event) => setName(event.target.value)}
              className="w-full rounded-lg border border-slate-200 px-2.5 py-1.5 text-sm text-slate-800 outline-none focus:border-slate-400"
            />
          </label>
          <label className="block space-y-1 text-xs text-slate-600">
            <span className="font-medium">配方 id</span>
            <input
              value={id}
              id="save-as-id"
              name="save-as-id"
              onChange={(event) => setId(event.target.value)}
              className="w-full rounded-lg border border-slate-200 px-2.5 py-1.5 font-mono text-xs text-slate-800 outline-none focus:border-slate-400"
            />
            {idError ? <span className="text-[11px] text-red-600">{idError}</span> : null}
          </label>
        </div>
        <footer className="flex justify-end gap-2 border-t border-slate-100 px-4 py-3">
          <button
            type="button"
            onClick={onCancel}
            className="rounded-lg border border-slate-200 px-3 py-1.5 text-xs text-slate-600 hover:bg-slate-50"
          >
            取消
          </button>
          <button
            type="button"
            disabled={Boolean(idError) || !name.trim()}
            onClick={() => onConfirm(id.trim(), name.trim())}
            className="rounded-lg bg-slate-900 px-3 py-1.5 text-xs font-medium text-white hover:bg-slate-800 disabled:cursor-not-allowed disabled:bg-slate-300"
          >
            {confirmText}
          </button>
        </footer>
      </div>
    </div>
  );
}

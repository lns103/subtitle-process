import { useCallback, useEffect, useState, type ChangeEvent, type ReactNode } from "react";
import {
  AlertCircle,
  ArrowLeft,
  CheckCircle2,
  FlaskConical,
  KeyRound,
  Loader2,
  Lock,
  Save,
  Settings as SettingsIcon,
  ShieldCheck,
} from "lucide-react";
import { navigate } from "../../lib/router";
import type { AgentSettings } from "../../lib/models";
import { useSettingsStore } from "../../stores/settingsStore";

const inputClass =
  "mt-1 w-full rounded-lg border border-slate-200 bg-white px-3 py-2 text-sm text-slate-800 outline-none focus:border-slate-400 disabled:bg-slate-50 disabled:text-slate-500";

interface FieldProps {
  label: string;
  htmlFor: string;
  hint?: string;
  children: ReactNode;
}

function Field({ label, htmlFor, hint, children }: FieldProps) {
  return (
    <div>
      <label htmlFor={htmlFor} className="text-xs font-medium text-slate-600">
        {label}
      </label>
      {children}
      {hint && <p className="mt-1 text-[11px] text-slate-400">{hint}</p>}
    </div>
  );
}

export function SettingsPage() {
  const settings = useSettingsStore((state) => state.settings);
  const loading = useSettingsStore((state) => state.loading);
  const saving = useSettingsStore((state) => state.saving);
  const testing = useSettingsStore((state) => state.testing);
  const apiKeyDraft = useSettingsStore((state) => state.apiKeyDraft);
  const lastError = useSettingsStore((state) => state.lastError);
  const testResult = useSettingsStore((state) => state.testResult);
  const load = useSettingsStore((state) => state.load);
  const save = useSettingsStore((state) => state.save);
  const setApiKeyDraft = useSettingsStore((state) => state.setApiKeyDraft);
  const saveApiKey = useSettingsStore((state) => state.saveApiKey);
  const test = useSettingsStore((state) => state.test);
  const reset = useSettingsStore((state) => state.reset);

  const [draft, setDraft] = useState<AgentSettings>(settings.agent);
  const [saved, setSaved] = useState(false);
  const [keyNotice, setKeyNotice] = useState<string | null>(null);
  const [testFailed, setTestFailed] = useState(false);

  useEffect(() => {
    void load();
    return () => reset();
  }, [load, reset]);

  // 引擎返回或保存成功后同步本地表单。
  useEffect(() => {
    setDraft(settings.agent);
  }, [settings]);

  const update = useCallback(<K extends keyof AgentSettings>(key: K, value: AgentSettings[K]) => {
    setDraft((current) => ({ ...current, [key]: value }));
    setSaved(false);
  }, []);

  const numberFrom = (event: ChangeEvent<HTMLInputElement>): number => {
    const value = event.target.valueAsNumber;
    return Number.isFinite(value) ? value : 0;
  };

  const handleSave = useCallback(async () => {
    await save({ agent: draft });
    if (!useSettingsStore.getState().lastError) setSaved(true);
  }, [draft, save]);

  const handleTest = useCallback(async () => {
    setKeyNotice(null);
    setTestFailed(false);
    await test();
    if (useSettingsStore.getState().lastError) setTestFailed(true);
  }, [test]);

  const handleSaveKey = useCallback(async () => {
    const removing = apiKeyDraft.length === 0;
    await saveApiKey();
    if (!useSettingsStore.getState().lastError) {
      setKeyNotice(removing ? "已删除已保存的 API Key。" : "API Key 已保存到系统钥匙串。");
    }
  }, [apiKeyDraft.length, saveApiKey]);

  const apiKeyConfigured = settings.agent.api_key_configured === true;
  const needsApiKey = lastError?.includes("1005") ?? false;

  return (
    <div className="min-h-screen bg-slate-100 px-5 py-6 text-slate-900">
      <div className="mx-auto max-w-5xl space-y-5">
        <header className="flex flex-wrap items-center justify-between gap-3">
          <div className="flex items-center gap-3">
            <button
              type="button"
              onClick={() => navigate({ name: "home" })}
              className="inline-flex items-center gap-1.5 rounded-full border border-slate-300 bg-white px-3 py-1.5 text-xs font-medium text-slate-700 hover:bg-slate-50"
            >
              <ArrowLeft className="h-3.5 w-3.5" /> 返回首页
            </button>
            <div>
              <h1 className="flex items-center gap-2 text-xl font-semibold tracking-tight">
                <SettingsIcon className="h-5 w-5 text-slate-500" /> 设置 · Agent
              </h1>
              <p className="text-xs text-slate-500">OpenAI 兼容接口配置与连接测试</p>
            </div>
          </div>

          <div className="flex flex-wrap items-center gap-2">
            <button
              type="button"
              data-testid="test-agent"
              disabled={testing}
              onClick={() => void handleTest()}
              className="inline-flex items-center gap-1.5 rounded-lg border border-slate-300 bg-white px-3 py-2 text-sm font-medium text-slate-700 hover:bg-slate-50 disabled:opacity-50"
            >
              {testing ? (
                <Loader2 className="h-4 w-4 animate-spin" />
              ) : (
                <FlaskConical className="h-4 w-4" />
              )}
              {testing ? "测试中…" : "测试连接"}
            </button>
            <button
              type="button"
              data-testid="save-settings"
              disabled={saving || loading}
              onClick={() => void handleSave()}
              className="inline-flex items-center gap-1.5 rounded-lg bg-slate-900 px-4 py-2 text-sm font-medium text-white hover:bg-slate-800 disabled:cursor-not-allowed disabled:bg-slate-300"
            >
              {saving ? <Loader2 className="h-4 w-4 animate-spin" /> : <Save className="h-4 w-4" />}
              {saving ? "保存中…" : "保存设置"}
            </button>
          </div>
        </header>

        {lastError && (
          <div
            role="alert"
            className="flex items-start gap-2 rounded-xl border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700"
          >
            <AlertCircle className="mt-0.5 h-4 w-4 shrink-0" />
            <div className="space-y-1">
              <p>{lastError}</p>
              {needsApiKey && (
                <p className="text-xs text-red-600">
                  检测到 1005：Agent 尚未配置，请先在右侧填写并保存 API Key。
                </p>
              )}
            </div>
          </div>
        )}

        {saved && (
          <div className="flex items-start gap-2 rounded-xl border border-emerald-200 bg-emerald-50 px-4 py-3 text-sm text-emerald-800">
            <CheckCircle2 className="mt-0.5 h-4 w-4 shrink-0" />
            <span>设置已保存。</span>
          </div>
        )}

        {testResult?.ok && (
          <div className="flex items-start gap-2 rounded-xl border border-emerald-200 bg-emerald-50 px-4 py-3 text-sm text-emerald-800">
            <ShieldCheck className="mt-0.5 h-4 w-4 shrink-0" />
            <div>
              <p>连接正常 · {Math.round(testResult.latency_ms)} ms</p>
              {(testResult.model || testResult.base_url) && (
                <p className="mt-1 break-all font-mono text-xs text-emerald-700">
                  {[testResult.model, testResult.base_url].filter(Boolean).join(" · ")}
                </p>
              )}
            </div>
          </div>
        )}

        <div className="grid gap-5 lg:grid-cols-[minmax(0,1fr)_minmax(0,340px)]">
          <section className="rounded-2xl border border-slate-200 bg-white p-5">
            <div className="flex items-center justify-between gap-2">
              <h2 className="text-sm font-semibold text-slate-800">Agent 参数</h2>
              {loading && (
                <span className="inline-flex items-center gap-1 text-xs text-slate-400">
                  <Loader2 className="h-3.5 w-3.5 animate-spin" /> 读取中…
                </span>
              )}
            </div>

            <div className="mt-4 space-y-4">
              <Field
                label="Base URL"
                htmlFor="settings-base-url"
                hint="兼容 OpenAI / DeepSeek / Ollama 的 OpenAI 兼容端点。"
              >
                <input
                  id="settings-base-url"
                  type="text"
                  value={draft.base_url}
                  disabled={loading}
                  onChange={(event) => update("base_url", event.target.value)}
                  placeholder="https://api.deepseek.com/v1"
                  className={inputClass}
                />
              </Field>

              <div className="grid gap-4 sm:grid-cols-2">
                <Field label="模型" htmlFor="settings-model">
                  <input
                    id="settings-model"
                    type="text"
                    value={draft.model}
                    disabled={loading}
                    onChange={(event) => update("model", event.target.value)}
                    placeholder="deepseek-chat"
                    className={inputClass}
                  />
                </Field>
                <Field label="Temperature" htmlFor="settings-temperature">
                  <input
                    id="settings-temperature"
                    type="number"
                    min={0}
                    max={2}
                    step={0.1}
                    value={draft.temperature}
                    disabled={loading}
                    onChange={(event) => update("temperature", numberFrom(event))}
                    className={inputClass}
                  />
                </Field>
                <Field label="超时（秒）" htmlFor="settings-timeout">
                  <input
                    id="settings-timeout"
                    type="number"
                    min={1}
                    max={600}
                    step={1}
                    value={draft.timeout_s}
                    disabled={loading}
                    onChange={(event) => update("timeout_s", numberFrom(event))}
                    className={inputClass}
                  />
                </Field>
                <Field label="最大重试次数" htmlFor="settings-max-retries">
                  <input
                    id="settings-max-retries"
                    type="number"
                    min={0}
                    max={5}
                    step={1}
                    value={draft.max_retries}
                    disabled={loading}
                    onChange={(event) => update("max_retries", numberFrom(event))}
                    className={inputClass}
                  />
                </Field>
                <Field label="批大小" htmlFor="settings-batch-size" hint="每次发送给模型的候选段数量。">
                  <input
                    id="settings-batch-size"
                    type="number"
                    min={5}
                    max={30}
                    step={1}
                    value={draft.batch_size}
                    disabled={loading}
                    onChange={(event) => update("batch_size", numberFrom(event))}
                    className={inputClass}
                  />
                </Field>
                <Field label="上下文段数" htmlFor="settings-context-size" hint="候选段前后附带的上下文条数。">
                  <input
                    id="settings-context-size"
                    type="number"
                    min={0}
                    max={5}
                    step={1}
                    value={draft.context_size}
                    disabled={loading}
                    onChange={(event) => update("context_size", numberFrom(event))}
                    className={inputClass}
                  />
                </Field>
                <Field
                  label="最低置信度"
                  htmlFor="settings-min-confidence"
                  hint="0–1，高于该阈值才可能自动应用。"
                >
                  <input
                    id="settings-min-confidence"
                    type="number"
                    min={0}
                    max={1}
                    step={0.05}
                    value={draft.min_confidence}
                    disabled={loading}
                    onChange={(event) => update("min_confidence", numberFrom(event))}
                    className={inputClass}
                  />
                </Field>
                <Field
                  label="删除比例上限"
                  htmlFor="settings-delete-ratio-limit"
                  hint="0–1，超过该比例强制转人工审核。"
                >
                  <input
                    id="settings-delete-ratio-limit"
                    type="number"
                    min={0}
                    max={1}
                    step={0.05}
                    value={draft.delete_ratio_limit}
                    disabled={loading}
                    onChange={(event) => update("delete_ratio_limit", numberFrom(event))}
                    className={inputClass}
                  />
                </Field>
              </div>

              <Field label="结构化输出" htmlFor="settings-structured-output">
                <select
                  id="settings-structured-output"
                  value={draft.structured_output}
                  disabled={loading}
                  onChange={(event) =>
                    update(
                      "structured_output",
                      event.target.value as AgentSettings["structured_output"],
                    )
                  }
                  className={inputClass}
                >
                  <option value="json_schema">json_schema（推荐）</option>
                  <option value="json_object">json_object</option>
                </select>
              </Field>

              <label
                htmlFor="settings-auto-apply"
                className="flex items-start gap-3 rounded-xl border border-slate-200 bg-slate-50/60 px-3 py-3"
              >
                <input
                  id="settings-auto-apply"
                  type="checkbox"
                  checked={draft.auto_apply}
                  disabled={loading}
                  onChange={(event) => update("auto_apply", event.target.checked)}
                  className="mt-0.5 h-4 w-4 rounded border-slate-300 text-slate-900 focus:ring-slate-400"
                />
                <span>
                  <span className="block text-xs font-medium text-slate-700">自动应用 Agent 结果</span>
                  <span className="mt-0.5 block text-[11px] text-slate-500">
                    默认关闭，删除前必须人工确认。开启后仅对达到最低置信度且不超过删除比例上限的结果自动应用，并保留审计与撤销能力。
                  </span>
                </span>
              </label>
            </div>
          </section>

          <div className="space-y-5">
            <section className="rounded-2xl border border-slate-200 bg-white p-5">
              <div className="flex items-center justify-between gap-2">
                <h2 className="flex items-center gap-2 text-sm font-semibold text-slate-800">
                  <KeyRound className="h-4 w-4 text-slate-500" /> API Key
                </h2>
                <span
                  className={`rounded-full px-2 py-0.5 text-[11px] ${
                    apiKeyConfigured
                      ? "bg-emerald-100 text-emerald-700"
                      : "bg-slate-100 text-slate-500"
                  }`}
                >
                  {apiKeyConfigured ? "已配置" : "未配置"}
                </span>
              </div>

              <p className="mt-2 flex items-center gap-1.5 text-[11px] text-slate-400">
                <Lock className="h-3 w-3" /> Key 存储在系统钥匙串中，页面不会回显已保存的 Key。
              </p>

              <label htmlFor="settings-api-key" className="mt-3 block text-xs font-medium text-slate-600">
                新的 API Key
              </label>
              <input
                id="settings-api-key"
                type="password"
                autoComplete="off"
                value={apiKeyDraft}
                onChange={(event) => {
                  setApiKeyDraft(event.target.value);
                  setKeyNotice(null);
                }}
                placeholder={apiKeyConfigured ? "已配置 · 输入新 Key 可替换" : "sk-…"}
                className={inputClass}
              />
              <p className="mt-1 text-[11px] text-slate-400">
                留空并点击「保存 Key」将删除已保存的 Key。
              </p>

              <button
                type="button"
                data-testid="save-api-key"
                disabled={saving}
                onClick={() => void handleSaveKey()}
                className="mt-3 inline-flex w-full items-center justify-center gap-1.5 rounded-lg border border-slate-300 bg-white px-3 py-2 text-sm font-medium text-slate-700 hover:bg-slate-50 disabled:opacity-50"
              >
                {saving ? <Loader2 className="h-4 w-4 animate-spin" /> : <KeyRound className="h-4 w-4" />}
                {apiKeyDraft.length === 0 ? "保存 Key（将删除）" : "保存 Key"}
              </button>

              {keyNotice && <p className="mt-2 text-[11px] text-emerald-700">{keyNotice}</p>}
            </section>

            <section className="rounded-2xl border border-slate-200 bg-white p-5">
              <h2 className="flex items-center gap-2 text-sm font-semibold text-slate-800">
                <FlaskConical className="h-4 w-4 text-slate-500" /> 连接测试
              </h2>
              <p className="mt-2 text-[11px] text-slate-400">
                使用已保存的 Base URL、模型与 API Key 发起一次轻量请求。修改参数后请先保存设置。
              </p>

              {testResult?.ok ? (
                <div className="mt-3 rounded-xl border border-emerald-200 bg-emerald-50 px-3 py-2 text-xs text-emerald-800">
                  <p className="font-medium">连接正常</p>
                  <p className="mt-1 font-mono">延迟 {Math.round(testResult.latency_ms)} ms</p>
                  {testResult.model && (
                    <p className="mt-0.5 break-all font-mono">模型 {testResult.model}</p>
                  )}
                  {testResult.base_url && (
                    <p className="mt-0.5 break-all font-mono">端点 {testResult.base_url}</p>
                  )}
                </div>
              ) : testFailed && lastError ? (
                <div className="mt-3 rounded-xl border border-red-200 bg-red-50 px-3 py-2 text-xs text-red-700">
                  <p>连接失败</p>
                  <p className="mt-0.5 break-all">{lastError}</p>
                  {needsApiKey && <p className="mt-1 text-red-600">请填写并保存 API Key 后重试。</p>}
                </div>
              ) : (
                <p className="mt-3 rounded-xl bg-slate-50 px-3 py-2 text-xs text-slate-500">
                  尚未测试连接。
                </p>
              )}

              <button
                type="button"
                data-testid="test-agent-card"
                disabled={testing}
                onClick={() => void handleTest()}
                className="mt-3 inline-flex w-full items-center justify-center gap-1.5 rounded-lg bg-slate-900 px-3 py-2 text-sm font-medium text-white hover:bg-slate-800 disabled:bg-slate-300"
              >
                {testing ? (
                  <Loader2 className="h-4 w-4 animate-spin" />
                ) : (
                  <FlaskConical className="h-4 w-4" />
                )}
                {testing ? "测试中…" : "测试连接"}
              </button>
            </section>
          </div>
        </div>
      </div>
    </div>
  );
}

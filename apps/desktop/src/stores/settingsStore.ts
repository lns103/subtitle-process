import { create } from "zustand";
import { getSettings, saveSettings, setSecret, testAgent } from "../lib/api";
import type { AgentSettings, AgentTestResult, AppSettings } from "../lib/models";

/** 引擎返回设置前用于渲染表单的默认值，与 M6 协议默认值保持一致。 */
export const DEFAULT_AGENT_SETTINGS: AgentSettings = {
  base_url: "https://api.deepseek.com/v1",
  model: "deepseek-flash",
  temperature: 0,
  timeout_s: 120,
  max_retries: 2,
  batch_size: 25,
  context_size: 2,
  min_confidence: 0.85,
  auto_apply: false,
  delete_ratio_limit: 0.3,
  structured_output: "json_schema",
  api_key_configured: false,
};

export const DEFAULT_SETTINGS: AppSettings = {
  agent: DEFAULT_AGENT_SETTINGS,
};

/** 钥匙串中的 secret 名称；与引擎 ``SECRET_AGENT_API_KEY`` 一致。 */
export const API_KEY_SECRET_NAME = "agent.api_key";

interface SettingsState {
  settings: AppSettings;
  loading: boolean;
  saving: boolean;
  testing: boolean;
  /** 输入框里的新 Key；永不来自引擎，也永不回显已存 Key。 */
  apiKeyDraft: string;
  lastError: string | null;
  testResult: AgentTestResult | null;
  load: () => Promise<void>;
  save: (settings: AppSettings) => Promise<void>;
  setApiKeyDraft: (value: string) => void;
  saveApiKey: () => Promise<void>;
  test: () => Promise<void>;
  reset: () => void;
}

const INITIAL = {
  settings: DEFAULT_SETTINGS,
  loading: false,
  saving: false,
  testing: false,
  apiKeyDraft: "",
  lastError: null as string | null,
  testResult: null as AgentTestResult | null,
};

function messageOf(error: unknown): string {
  return error instanceof Error ? error.message : String(error);
}

/**
 * 只保留可编辑字段：绝不把 ``api_key`` 或只读的 ``api_key_configured``
 * 发送给 ``settings.set``。
 */
export function editableSettings(settings: AppSettings): AppSettings {
  const agent = settings.agent;
  return {
    agent: {
      base_url: agent.base_url,
      model: agent.model,
      temperature: agent.temperature,
      timeout_s: agent.timeout_s,
      max_retries: agent.max_retries,
      batch_size: agent.batch_size,
      context_size: agent.context_size,
      min_confidence: agent.min_confidence,
      auto_apply: agent.auto_apply,
      delete_ratio_limit: agent.delete_ratio_limit,
      structured_output: agent.structured_output,
    },
  };
}

export const useSettingsStore = create<SettingsState>((set, get) => ({
  ...INITIAL,

  load: async () => {
    set({ loading: true, lastError: null });
    try {
      const settings = await getSettings();
      set({ settings, loading: false });
    } catch (error) {
      set({ loading: false, lastError: messageOf(error) });
    }
  },

  save: async (settings) => {
    if (get().saving) return;
    set({ saving: true, lastError: null });
    try {
      const payload = editableSettings(settings);
      const saved = await saveSettings(payload);
      set((state) => ({
        saving: false,
        settings: {
          agent: {
            ...saved.agent,
            // 引擎可能不回传只读状态，保留已知值避免 UI 闪烁。
            api_key_configured:
              saved.agent.api_key_configured ?? state.settings.agent.api_key_configured,
          },
        },
      }));
    } catch (error) {
      set({ saving: false, lastError: messageOf(error) });
    }
  },

  setApiKeyDraft: (value) => set({ apiKeyDraft: value }),

  saveApiKey: async () => {
    if (get().saving) return;
    const value = get().apiKeyDraft;
    set({ saving: true, lastError: null });
    try {
      // 空字符串表示删除已保存的 Key。
      await setSecret(API_KEY_SECRET_NAME, value);
      set((state) => ({
        saving: false,
        apiKeyDraft: "",
        settings: {
          agent: {
            ...state.settings.agent,
            api_key_configured: value.length > 0,
          },
        },
      }));
    } catch (error) {
      set({ saving: false, lastError: messageOf(error) });
    }
  },

  test: async () => {
    if (get().testing) return;
    set({ testing: true, lastError: null });
    try {
      const result = await testAgent();
      set({
        testing: false,
        testResult: result,
        lastError: result.ok ? null : "连接测试失败：Agent 返回 ok=false",
      });
    } catch (error) {
      set({ testing: false, testResult: null, lastError: messageOf(error) });
    }
  },

  reset: () => set({ ...INITIAL }),
}));

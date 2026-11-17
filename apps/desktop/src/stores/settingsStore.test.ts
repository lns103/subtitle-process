import { beforeEach, describe, expect, it, vi } from "vitest";
import { getSettings, saveSettings, setSecret, testAgent } from "../lib/api";
import type { AppSettings } from "../lib/models";
import {
  API_KEY_SECRET_NAME,
  DEFAULT_AGENT_SETTINGS,
  editableSettings,
  useSettingsStore,
} from "./settingsStore";

vi.mock("../lib/api", () => ({
  getSettings: vi.fn(),
  saveSettings: vi.fn(),
  setSecret: vi.fn(),
  testAgent: vi.fn(),
}));

const getMock = vi.mocked(getSettings);
const saveMock = vi.mocked(saveSettings);
const secretMock = vi.mocked(setSecret);
const testMock = vi.mocked(testAgent);

const SETTINGS: AppSettings = {
  agent: {
    ...DEFAULT_AGENT_SETTINGS,
    base_url: "https://api.example.com/v1",
    model: "gpt-test",
    api_key_configured: true,
  },
};

describe("settingsStore", () => {
  beforeEach(() => {
    getMock.mockReset();
    saveMock.mockReset();
    secretMock.mockReset();
    testMock.mockReset();
    useSettingsStore.getState().reset();
  });

  it("加载设置", async () => {
    getMock.mockResolvedValue(SETTINGS);

    await useSettingsStore.getState().load();

    const state = useSettingsStore.getState();
    expect(getMock).toHaveBeenCalledTimes(1);
    expect(state.loading).toBe(false);
    expect(state.lastError).toBeNull();
    expect(state.settings).toEqual(SETTINGS);
  });

  it("加载失败时记录错误", async () => {
    getMock.mockRejectedValue(new Error("engine offline"));

    await useSettingsStore.getState().load();

    expect(useSettingsStore.getState().lastError).toContain("engine offline");
    expect(useSettingsStore.getState().loading).toBe(false);
  });

  it("保存设置时不携带 api_key / api_key_configured", async () => {
    saveMock.mockImplementation(async (value) => value);

    await useSettingsStore.getState().save(SETTINGS);

    expect(saveMock).toHaveBeenCalledTimes(1);
    const payload = saveMock.mock.calls[0]![0];
    expect(payload.agent).not.toHaveProperty("api_key");
    expect(payload.agent).not.toHaveProperty("api_key_configured");
    expect(payload.agent).toEqual({
      base_url: SETTINGS.agent.base_url,
      model: SETTINGS.agent.model,
      temperature: SETTINGS.agent.temperature,
      timeout_s: SETTINGS.agent.timeout_s,
      max_retries: SETTINGS.agent.max_retries,
      batch_size: SETTINGS.agent.batch_size,
      context_size: SETTINGS.agent.context_size,
      min_confidence: SETTINGS.agent.min_confidence,
      auto_apply: SETTINGS.agent.auto_apply,
      delete_ratio_limit: SETTINGS.agent.delete_ratio_limit,
      structured_output: SETTINGS.agent.structured_output,
    });
    expect(editableSettings(SETTINGS)).toEqual(payload);
  });

  it("保存成功后同步引擎返回值并保留 Key 配置状态", async () => {
    useSettingsStore.setState({ settings: SETTINGS });
    saveMock.mockResolvedValue({ agent: { ...SETTINGS.agent, api_key_configured: undefined } });

    await useSettingsStore.getState().save(SETTINGS);

    const state = useSettingsStore.getState();
    expect(state.saving).toBe(false);
    expect(state.lastError).toBeNull();
    // 引擎未回传只读状态时沿用本地已知值。
    expect(state.settings.agent.api_key_configured).toBe(true);
  });

  it("保存空 Key 时向钥匙串写入空字符串并标记未配置", async () => {
    useSettingsStore.setState({
      apiKeyDraft: "",
      settings: { agent: { ...SETTINGS.agent, api_key_configured: true } },
    });
    secretMock.mockResolvedValue("ok");

    await useSettingsStore.getState().saveApiKey();

    expect(secretMock).toHaveBeenCalledWith(API_KEY_SECRET_NAME, "");
    const state = useSettingsStore.getState();
    expect(state.apiKeyDraft).toBe("");
    expect(state.settings.agent.api_key_configured).toBe(false);
    expect(state.lastError).toBeNull();
  });

  it("保存新 Key 后清空输入框并标记已配置", async () => {
    useSettingsStore.setState({ apiKeyDraft: "sk-new" });
    secretMock.mockResolvedValue("ok");

    await useSettingsStore.getState().saveApiKey();

    expect(secretMock).toHaveBeenCalledWith(API_KEY_SECRET_NAME, "sk-new");
    const state = useSettingsStore.getState();
    expect(state.apiKeyDraft).toBe("");
    expect(state.settings.agent.api_key_configured).toBe(true);
  });

  it("连接测试成功时保存结果", async () => {
    testMock.mockResolvedValue({ ok: true, latency_ms: 123, model: "gpt-test" });

    await useSettingsStore.getState().test();

    const state = useSettingsStore.getState();
    expect(state.testing).toBe(false);
    expect(state.lastError).toBeNull();
    expect(state.testResult).toEqual({ ok: true, latency_ms: 123, model: "gpt-test" });
  });

  it("连接测试失败时写入 lastError", async () => {
    testMock.mockRejectedValue(new Error("1005 agent_not_configured"));

    await useSettingsStore.getState().test();

    const state = useSettingsStore.getState();
    expect(state.testing).toBe(false);
    expect(state.testResult).toBeNull();
    expect(state.lastError).toContain("1005");
  });

  it("reset 恢复默认值", async () => {
    useSettingsStore.setState({
      apiKeyDraft: "sk-leftover",
      settings: SETTINGS,
      lastError: "boom",
      testResult: { ok: true, latency_ms: 1 },
    });

    useSettingsStore.getState().reset();

    const state = useSettingsStore.getState();
    expect(state.apiKeyDraft).toBe("");
    expect(state.settings).toEqual({ agent: DEFAULT_AGENT_SETTINGS });
    expect(state.lastError).toBeNull();
    expect(state.testResult).toBeNull();
  });
});

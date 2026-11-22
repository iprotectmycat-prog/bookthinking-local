"use client";

import { FormEvent, useState } from "react";

import type { ProviderSettings } from "../lib/types";

type SavePayload = {
  provider: string;
  model: string;
  apiKey: string;
  secondaryApiKey?: string;
  tertiaryApiKey?: string;
  quaternaryApiKey?: string;
};

const DEFAULT_MODELS: Record<string, string> = {
  openai: "gpt-5",
  deepseek: "deepseek-chat",
};

export function ProviderSettingsForm({ initial, onSave }: { initial: ProviderSettings; onSave: (payload: SavePayload) => Promise<void> }) {
  const [provider, setProvider] = useState(initial.provider || "openai");
  const [model, setModel] = useState(initial.model || DEFAULT_MODELS[initial.provider || "openai"]);
  const [apiKey, setApiKey] = useState("");
  const [secondaryApiKey, setSecondaryApiKey] = useState("");
  const [tertiaryApiKey, setTertiaryApiKey] = useState("");
  const [quaternaryApiKey, setQuaternaryApiKey] = useState("");
  const [message, setMessage] = useState("");
  const [messageKind, setMessageKind] = useState<"ok" | "error" | "info">("info");
  const [saving, setSaving] = useState(false);

  async function submit(event: FormEvent) {
    event.preventDefault();
    const hasSavedPrimaryKey = initial.configured && initial.provider === provider;
    if (!model.trim() || (!apiKey.trim() && !hasSavedPrimaryKey)) {
      setMessageKind("error");
      setMessage("请输入模型名称和 API Key。已保存的 Key 不会从系统钥匙串读取到页面中。");
      return;
    }
    setSaving(true);
    setMessageKind("info");
    setMessage("正在保存…");
    try {
      await onSave({
        provider,
        model: model.trim(),
        apiKey: apiKey.trim(),
        secondaryApiKey: provider === "deepseek" ? secondaryApiKey.trim() || undefined : undefined,
        tertiaryApiKey: provider === "deepseek" ? tertiaryApiKey.trim() || undefined : undefined,
        quaternaryApiKey: provider === "deepseek" ? quaternaryApiKey.trim() || undefined : undefined,
      });
      setApiKey("");
      setSecondaryApiKey("");
      setTertiaryApiKey("");
      setQuaternaryApiKey("");
      setMessageKind("ok");
      setMessage("设置已保存，可以返回书籍继续生成分析。");
    } catch (error) {
      setMessageKind("error");
      setMessage(error instanceof Error ? error.message : "保存失败。");
    } finally {
      setSaving(false);
    }
  }

  return (
    <form className="settings-form" onSubmit={submit}>
      <label className="settings-field"><span>模型服务</span><select value={provider} onChange={(event) => { const value = event.target.value; setProvider(value); setModel(DEFAULT_MODELS[value]); }}><option value="openai">OpenAI</option><option value="deepseek">DeepSeek</option></select></label>
      <label className="settings-field"><span>模型名称</span><input value={model} onChange={(event) => setModel(event.target.value)} placeholder={DEFAULT_MODELS[provider]} /></label>
      <fieldset className="settings-key-group">
        <legend>密钥</legend>
        <label className="settings-field"><span>API Key</span><input aria-label="API Key" type="password" autoComplete="off" value={apiKey} onChange={(event) => setApiKey(event.target.value)} placeholder="输入后保存到 macOS 钥匙串" /></label>
        {provider === "deepseek" && <>
          <label className="settings-field"><span>第二个 API Key <em>可选</em></span><input aria-label="第二个 API Key" type="password" autoComplete="off" value={secondaryApiKey} onChange={(event) => setSecondaryApiKey(event.target.value)} placeholder="可选：保存到独立的本机钥匙串槽位" /></label>
          <label className="settings-field"><span>第三个 API Key <em>可选</em></span><input aria-label="第三个 API Key" type="password" autoComplete="off" value={tertiaryApiKey} onChange={(event) => setTertiaryApiKey(event.target.value)} placeholder="可选：保存到独立的本机钥匙串槽位" /></label>
          <label className="settings-field"><span>第四个 API Key <em>可选</em></span><input aria-label="第四个 API Key" type="password" autoComplete="off" value={quaternaryApiKey} onChange={(event) => setQuaternaryApiKey(event.target.value)} placeholder="可选：保存到独立的本机钥匙串槽位" /></label>
        </>}
      </fieldset>
      {initial.configured && <p className="security-note">API Key 已安全保存，本页不会读取或显示原值。</p>}
      <aside className="privacy-note"><strong>本地优先</strong><p>PDF、章节和分析结果保存在本机。只有生成分析时，对应章节文本会发送给你配置的模型服务。</p></aside>
      <div className="settings-actions"><p className={`form-message form-message-${messageKind}`} aria-live="polite">{message}</p><button className="primary-button" disabled={saving} type="submit">{saving ? "正在保存…" : "保存模型设置"}</button></div>
    </form>
  );
}

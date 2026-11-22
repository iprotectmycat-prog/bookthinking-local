"use client";

import { useEffect, useState } from "react";
import Link from "next/link";

import { ProviderSettingsForm } from "./ProviderSettingsForm";
import { apiJson } from "../lib/api";
import type { ProviderSettings } from "../lib/types";

export function LocalModelSettings() {
  const [settings, setSettings] = useState<ProviderSettings>();
  const [error, setError] = useState("");

  useEffect(() => {
    apiJson<ProviderSettings>("/settings/providers/current").then(setSettings).catch((reason) => setError(reason.message || "无法读取模型设置。"));
  }, []);

  async function save(payload: { provider: string; model: string; apiKey: string; secondaryApiKey?: string; tertiaryApiKey?: string; quaternaryApiKey?: string }) {
    const result = await apiJson<ProviderSettings>(`/settings/providers/${payload.provider}`, {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        model: payload.model,
        api_key: payload.apiKey,
        api_key_secondary: payload.secondaryApiKey,
        api_key_tertiary: payload.tertiaryApiKey,
        api_key_quaternary: payload.quaternaryApiKey,
      }),
    });
    setSettings(result);
  }

  if (error) return <main className="state-page"><p role="alert">{error}</p><Link href="/">返回首页</Link></main>;
  if (!settings) return <main className="state-page"><p>正在读取模型设置…</p></main>;

  return (
    <main className="settings-page">
      <Link href="/" className="back-link">← 返回首页</Link>
      <header className="settings-header"><span className="eyebrow">本机设置</span><h1>连接分析模型</h1><p>选择一个兼容服务，用于生成章节核心思想、论证拆解与证据引用。</p></header>
      <ProviderSettingsForm initial={settings} onSave={save} />
    </main>
  );
}

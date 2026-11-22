import type { ProviderSettings } from "../lib/types";

export function CloudProviderStatus({ settings }: { settings: ProviderSettings }) {
  const provider = settings.provider === "openai" ? "OpenAI" : settings.provider === "deepseek" ? "DeepSeek" : "未配置";
  const summary = settings.provider ? `${provider} · ${settings.model || "未选择模型"}` : "尚未配置模型";

  return (
    <section className="cloud-provider-status" aria-label="云端模型配置">
      <h2>云端模型配置</h2>
      <p>{summary}</p>
      <p>{settings.configured ? "模型服务已配置。" : "模型服务尚未配置。"}</p>
      <p>模型密钥由服务器环境变量管理。</p>
    </section>
  );
}

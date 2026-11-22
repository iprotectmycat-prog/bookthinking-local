import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { ProviderSettingsForm } from "../components/ProviderSettingsForm";

describe("ProviderSettingsForm", () => {
  it("keeps an existing secret hidden and only submits a newly entered key", async () => {
    const user = userEvent.setup();
    const onSave = vi.fn().mockResolvedValue(undefined);
    render(<ProviderSettingsForm initial={{ provider: "openai", model: "gpt-5", configured: true }} onSave={onSave} />);

    expect(screen.getByText("API Key 已安全保存，本页不会读取或显示原值。")).toBeInTheDocument();
    expect(screen.getByLabelText("API Key")).toHaveAttribute("type", "password");
    await user.type(screen.getByLabelText("API Key"), "new-secret");
    await user.click(screen.getByRole("button", { name: "保存模型设置" }));

    expect(onSave).toHaveBeenCalledWith({ provider: "openai", model: "gpt-5", apiKey: "new-secret" });
  });

  it("submits four DeepSeek keys without revealing saved keys", async () => {
    const user = userEvent.setup();
    const onSave = vi.fn().mockResolvedValue(undefined);
    render(<ProviderSettingsForm initial={{ provider: "deepseek", model: "deepseek-v4-pro", configured: true, secondary_configured: false }} onSave={onSave} />);

    expect(screen.getByRole("group", { name: "密钥" })).toBeInTheDocument();
    expect(screen.getAllByText("可选")).toHaveLength(3);
    await user.type(screen.getByLabelText("API Key"), "primary-secret");
    await user.type(screen.getByLabelText("第二个 API Key"), "secondary-secret");
    await user.type(screen.getByLabelText("第三个 API Key"), "tertiary-secret");
    await user.type(screen.getByLabelText("第四个 API Key"), "quaternary-secret");
    await user.click(screen.getByRole("button", { name: "保存模型设置" }));

    expect(onSave).toHaveBeenCalledWith({
      provider: "deepseek",
      model: "deepseek-v4-pro",
      apiKey: "primary-secret",
      secondaryApiKey: "secondary-secret",
      tertiaryApiKey: "tertiary-secret",
      quaternaryApiKey: "quaternary-secret",
    });
  });

  it("adds a third DeepSeek key without requiring the saved primary key again", async () => {
    const user = userEvent.setup();
    const onSave = vi.fn().mockResolvedValue(undefined);
    render(<ProviderSettingsForm initial={{ provider: "deepseek", model: "deepseek-v4-flash", configured: true, secondary_configured: true }} onSave={onSave} />);

    await user.type(screen.getByLabelText("第三个 API Key"), "tertiary-secret");
    await user.click(screen.getByRole("button", { name: "保存模型设置" }));

    expect(onSave).toHaveBeenCalledWith({
      provider: "deepseek",
      model: "deepseek-v4-flash",
      apiKey: "",
      tertiaryApiKey: "tertiary-secret",
      secondaryApiKey: undefined,
      quaternaryApiKey: undefined,
    });
  });
});

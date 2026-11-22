import { render, screen } from "@testing-library/react";
import { expect, it } from "vitest";

import { CloudProviderStatus } from "../components/CloudProviderStatus";

it("shows server-managed provider status without a browser API-key field", () => {
  render(<CloudProviderStatus settings={{ provider: "openai", model: "gpt-5", configured: true }} />);

  expect(screen.getByText("云端模型配置")).toBeInTheDocument();
  expect(screen.getByText("OpenAI · gpt-5")).toBeInTheDocument();
  expect(screen.getByText("模型密钥由服务器环境变量管理。"))
    .toBeInTheDocument();
  expect(screen.queryByLabelText("API Key")).not.toBeInTheDocument();
});

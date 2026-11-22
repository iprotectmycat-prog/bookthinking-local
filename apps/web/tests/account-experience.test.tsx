import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

const { apiJson } = vi.hoisted(() => ({ apiJson: vi.fn() }));
vi.mock("../lib/api", () => ({ apiJson }));

import { AccountExperience } from "../components/AccountExperience";

describe("AccountExperience", () => {
  beforeEach(() => apiJson.mockReset());

  it("presents the evidence-first brand promise above a focused login form", () => {
    apiJson.mockRejectedValueOnce(new Error("not signed in"));

    render(<AccountExperience initialMode="login" />);

    expect(screen.getByRole("heading", { name: "读懂一本书，从可回查的结论开始。" })).toBeInTheDocument();
    expect(screen.getByText("从全书框架进入每章的问题、结论与论证，并随时回到原文证据。")).toBeInTheDocument();
    expect(screen.getByRole("form", { name: "登录 BookThinking" })).toBeInTheDocument();
    expect(screen.queryByText("原文 — 推理 — 结论")).not.toBeInTheDocument();
    expect(screen.queryByText("你的书籍与阅读记录仅属于你的账号")).not.toBeInTheDocument();
  });

  it("switches between login and invitation registration without leaving the auth page", async () => {
    const user = userEvent.setup();
    apiJson.mockRejectedValueOnce(new Error("not signed in"));

    render(<AccountExperience initialMode="login" />);

    await user.click(screen.getByRole("button", { name: "使用邀请码注册" }));

    expect(screen.getByRole("form", { name: "注册 BookThinking" })).toBeInTheDocument();
    expect(screen.getByLabelText("邀请码")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "创建账号" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "返回登录" })).toBeInTheDocument();
  });

  it("lets the user reveal and hide the password", async () => {
    const user = userEvent.setup();
    apiJson.mockRejectedValueOnce(new Error("not signed in"));

    render(<AccountExperience initialMode="login" />);

    const password = screen.getByLabelText("密码");
    expect(password).toHaveAttribute("type", "password");
    await user.click(screen.getByRole("button", { name: "显示密码" }));
    expect(password).toHaveAttribute("type", "text");
    await user.click(screen.getByRole("button", { name: "隐藏密码" }));
    expect(password).toHaveAttribute("type", "password");
  });

  it("clears and hides the password when switching authentication modes", async () => {
    const user = userEvent.setup();
    apiJson.mockRejectedValueOnce(new Error("not signed in"));

    render(<AccountExperience initialMode="login" />);

    const password = screen.getByLabelText("密码");
    await user.type(password, "private password");
    await user.click(screen.getByRole("button", { name: "显示密码" }));
    await user.click(screen.getByRole("button", { name: "使用邀请码注册" }));

    expect(password).toHaveValue("");
    expect(password).toHaveAttribute("type", "password");
  });

  it("lets a signed-in user change password", async () => {
    const user = userEvent.setup();
    apiJson.mockResolvedValueOnce({
      email: "reader@example.com", role: "user", status: "active", book_import_count: 0, book_import_limit: 2,
    });
    apiJson.mockResolvedValueOnce([]);
    apiJson.mockResolvedValueOnce(undefined);

    render(<AccountExperience initialMode="login" />);

    await user.type(await screen.findByLabelText("当前密码"), "old password");
    await user.type(screen.getByLabelText("新密码"), "new password");
    await user.click(screen.getByRole("button", { name: "修改密码" }));

    expect(apiJson).toHaveBeenCalledWith("/auth/change-password", expect.objectContaining({ method: "POST" }), expect.anything());
  });

  it("keeps the signed-in account page focused on identity, password, and logout", async () => {
    const user = userEvent.setup();
    apiJson.mockResolvedValueOnce({
      email: "owner@example.com", role: "owner", status: "active", book_import_count: 12, book_import_limit: null,
    });
    apiJson.mockResolvedValueOnce([]);
    apiJson.mockResolvedValueOnce(undefined);

    render(<AccountExperience initialMode="login" />);

    expect(await screen.findByRole("heading", { name: "账号设置" })).toBeInTheDocument();
    expect(screen.getByText("owner@example.com")).toBeInTheDocument();
    expect(screen.getByText("主账号 · 导入不限")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "管理体验账号" })).toHaveAttribute("href", "/admin");
    expect(screen.getByRole("button", { name: "退出登录" })).toBeInTheDocument();
    expect(screen.queryByText("登录设备")).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "退出所有设备" })).not.toBeInTheDocument();

    await waitFor(() => expect(apiJson).toHaveBeenCalledTimes(1));
    expect(apiJson).not.toHaveBeenCalledWith("/auth/sessions", expect.anything(), expect.anything());

    await user.click(screen.getByRole("button", { name: "退出登录" }));
    expect(apiJson).toHaveBeenCalledWith("/auth/logout", { method: "POST" }, expect.anything());
  });

  it("lets a signed-in user reveal both password fields independently", async () => {
    const user = userEvent.setup();
    apiJson.mockResolvedValueOnce({
      email: "reader@example.com", role: "user", status: "active", book_import_count: 0, book_import_limit: 2,
    });
    apiJson.mockResolvedValueOnce([]);

    render(<AccountExperience initialMode="login" />);

    const currentPassword = await screen.findByLabelText("当前密码");
    const newPassword = screen.getByLabelText("新密码");
    await user.click(screen.getByRole("button", { name: "显示当前密码" }));

    expect(currentPassword).toHaveAttribute("type", "text");
    expect(newPassword).toHaveAttribute("type", "password");

    await user.click(screen.getByRole("button", { name: "显示新密码" }));
    expect(newPassword).toHaveAttribute("type", "text");
  });
});

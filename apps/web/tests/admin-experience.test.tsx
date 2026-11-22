import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

const { apiJson } = vi.hoisted(() => ({ apiJson: vi.fn() }));
vi.mock("../lib/api", () => ({ apiJson }));

import { AdminExperience } from "../components/AdminExperience";

const readyPrivateBook = {
  id: "book-1",
  title: "示例书",
  filename: "example.pdf",
  source_format: "pdf" as const,
  visibility: "private" as const,
  overview_status: "ready",
  ready_chapter_count: 1,
  public_at: null,
  publication_blockers: [],
};

describe("AdminExperience", () => {
  beforeEach(() => apiJson.mockReset());

  it("lists invite status and confirms before revoking an invite", async () => {
    const user = userEvent.setup();
    vi.stubGlobal("confirm", vi.fn(() => true));
    apiJson.mockResolvedValueOnce([{ id: 2, email: "reader@example.com", role: "user", status: "active", book_import_count: 1, book_import_limit: 2 }]);
    apiJson.mockResolvedValueOnce([{ id: 9, status: "active", label: "给小张", created_at: "2026-08-19T00:00:00+00:00", used_at: null, revoked_at: null, used_by_user_id: null }]);
    apiJson.mockResolvedValueOnce([]);
    apiJson.mockResolvedValueOnce(undefined);
    apiJson.mockResolvedValueOnce([{ id: 2, email: "reader@example.com", role: "user", status: "active", book_import_count: 1, book_import_limit: 2 }]);
    apiJson.mockResolvedValueOnce([{ id: 9, status: "revoked", label: "给小张", created_at: "2026-08-19T00:00:00+00:00", used_at: null, revoked_at: "2026-08-19T00:01:00+00:00", used_by_user_id: null }]);
    apiJson.mockResolvedValueOnce([]);

    render(<AdminExperience />);

    expect(await screen.findByText(/未使用/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "保存额度" })).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "撤销邀请码" }));
    expect(globalThis.confirm).toHaveBeenCalled();
    expect(apiJson).toHaveBeenCalledWith("/admin/invites/9/revoke", { method: "POST" });
  });

  it("lets the owner freeze a user and displays a newly reset temporary password", async () => {
    const user = userEvent.setup();
    vi.stubGlobal("confirm", vi.fn(() => true));
    apiJson.mockResolvedValueOnce([{ id: 2, email: "reader@example.com", role: "user", status: "active", book_import_count: 1, book_import_limit: 2 }]);
    apiJson.mockResolvedValueOnce([]);
    apiJson.mockResolvedValueOnce([]);
    apiJson.mockResolvedValueOnce(undefined);
    apiJson.mockResolvedValueOnce([{ id: 2, email: "reader@example.com", role: "user", status: "frozen", book_import_count: 1, book_import_limit: 2 }]);
    apiJson.mockResolvedValueOnce([]);
    apiJson.mockResolvedValueOnce([]);
    apiJson.mockResolvedValueOnce({ temporary_password: "temporary-password" });

    render(<AdminExperience />);

    await screen.findByText(/reader@example.com/);
    await user.click(screen.getByRole("button", { name: "冻结账号" }));
    expect(apiJson).toHaveBeenCalledWith("/admin/users/2/freeze", { method: "POST" });
    await user.click(screen.getByRole("button", { name: "重置密码" }));
    expect(apiJson).toHaveBeenCalledWith("/admin/users/2/reset-password", { method: "POST" });
    expect(await screen.findByText(/temporary-password/)).toBeInTheDocument();
  });

  it("requires rights confirmation before publishing a ready book", async () => {
    const user = userEvent.setup();
    apiJson.mockImplementation((path: string) => {
      if (path === "/admin/users") return Promise.resolve([]);
      if (path === "/admin/invites") return Promise.resolve([]);
      if (path === "/admin/books") return Promise.resolve([readyPrivateBook]);
      if (path === "/admin/books/book-1/publish") return Promise.resolve({ ...readyPrivateBook, visibility: "public" });
      return Promise.resolve(undefined);
    });

    render(<AdminExperience />);

    const publish = await screen.findByRole("button", { name: "发布到精选书架" });
    expect(publish).toBeDisabled();
    await user.click(screen.getByRole("checkbox", { name: /拥有公开传播/ }));
    expect(publish).toBeEnabled();
    await user.click(publish);

    expect(apiJson).toHaveBeenCalledWith("/admin/books/book-1/publish", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ rights_confirmed: true }),
    });
  });
});

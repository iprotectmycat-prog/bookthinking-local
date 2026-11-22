import { act, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import { BookImport } from "../components/BookImport";

describe("BookImport", () => {
  afterEach(() => vi.unstubAllGlobals());

  it("uploads a file immediately after the system picker selection", async () => {
    const user = userEvent.setup();
    const fetchMock = vi.fn().mockResolvedValue({
      ok: false,
      status: 415,
      json: async () => ({ detail: "不支持的文件格式" }),
    });
    vi.stubGlobal("fetch", fetchMock);
    render(<BookImport />);

    await user.upload(
      screen.getByLabelText("选择 PDF 或 EPUB 文件"),
      new File(["epub"], "黑天鹅——如何应对不可预知的未来.epub", {
        type: "application/epub+zip",
      }),
    );

    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(1));

    const [, request] = fetchMock.mock.calls[0];
    expect(request).toMatchObject({ method: "POST" });
    expect((request?.body as FormData).get("file")).toMatchObject({ name: "黑天鹅——如何应对不可预知的未来.epub" });
    expect(screen.getByText("不支持的文件格式")).toBeVisible();
  });

  it("prevents duplicate uploads while parsing, then allows selecting the same file again", async () => {
    const user = userEvent.setup();
    let complete!: (response: unknown) => void;
    const fetchMock = vi.fn().mockImplementationOnce(() => new Promise((resolve) => { complete = resolve; }));
    vi.stubGlobal("fetch", fetchMock);
    render(<BookImport label="导入书籍" />);
    const file = new File(["epub"], "测试书.epub", { type: "application/epub+zip" });
    const input = screen.getByLabelText("选择 PDF 或 EPUB 文件");
    await user.upload(input, file);
    const busyButton = screen.getByRole("button", { name: "正在解析…" });
    expect(busyButton).toBeDisabled();
    expect(screen.getByRole("status")).toHaveTextContent("测试书.epub");
    await user.click(busyButton);
    expect(fetchMock).toHaveBeenCalledOnce();
    const failure = { ok: false, status: 422, json: async () => ({ detail: "无法解析这本书" }) };
    await act(async () => complete(failure));
    expect(screen.getByRole("button", { name: "导入书籍" })).toBeEnabled();
    fetchMock.mockResolvedValue(failure);
    await user.upload(input, file);
    expect(fetchMock).toHaveBeenCalledTimes(2);
  });

  it("keeps a readable error when the API returns structured validation details", async () => {
    const user = userEvent.setup();
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue({
      ok: false, status: 422, json: async () => ({ detail: [{ msg: "invalid" }] }),
    }));
    render(<BookImport />);
    await user.upload(screen.getByLabelText("选择 PDF 或 EPUB 文件"), new File(["pdf"], "测试.pdf", { type: "application/pdf" }));
    expect(await screen.findByRole("status")).toHaveTextContent("导入失败，请稍后重试。");
  });

});

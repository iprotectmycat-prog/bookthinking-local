import { act, fireEvent, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";
import { EpubSourceChat } from "../components/EpubSourceChat";

const passage = { cfi: "selection", quote: "一段原文", before: "", after: "" };
const model = { model: "test-model", thinking_options: [] };

afterEach(() => vi.unstubAllGlobals());

describe("EPUB conversation requests", () => {
  it("restores the question on stop, ignores a late reply, and does not submit again", async () => {
    let reply!: (response: Response) => void;
    const fetchMock = vi.fn().mockResolvedValueOnce(Response.json(model))
      .mockImplementationOnce(() => new Promise<Response>((resolve) => { reply = resolve; }));
    vi.stubGlobal("fetch", fetchMock);
    const onSave = vi.fn();
    const user = userEvent.setup();
    render(<EpubSourceChat bookId="book" passage={passage} chapterSummary="" turns={[]} onSave={onSave} onBack={vi.fn()} onClose={vi.fn()} />);
    await screen.findByText("test-model");
    const input = screen.getByRole("textbox");
    await user.type(input, "解释这段");
    await user.click(screen.getByRole("button", { name: "发送" }));
    expect(screen.getByText("解释这段")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "停止等待" }));
    expect(input).toHaveValue("解释这段");
    expect(fetchMock).toHaveBeenCalledTimes(2);
    expect(fetchMock.mock.calls[1][1].signal.aborted).toBe(true);
    await act(async () => reply(Response.json({ answer: "迟到的回答" })));
    expect(onSave).not.toHaveBeenCalled();
    expect(input).toHaveValue("解释这段");
  });

  it("keeps IME Enter from submitting and preserves failed questions for retry", async () => {
    const fetchMock = vi.fn().mockResolvedValueOnce(Response.json(model))
      .mockRejectedValueOnce(new TypeError("network error"))
      .mockResolvedValueOnce(Response.json({ answer: "回答" }));
    vi.stubGlobal("fetch", fetchMock);
    const onSave = vi.fn();
    render(<EpubSourceChat bookId="book" passage={passage} chapterSummary="" turns={[]} onSave={onSave} onBack={vi.fn()} onClose={vi.fn()} />);
    await screen.findByText("test-model");
    const input = screen.getByRole("textbox");
    fireEvent.change(input, { target: { value: "我的问题" } });
    fireEvent.keyDown(input, { key: "Enter", isComposing: true });
    expect(fetchMock).toHaveBeenCalledTimes(1);
    fireEvent.keyDown(input, { key: "Enter" });
    await screen.findByRole("alert");
    expect(input).toHaveValue("我的问题");
    fireEvent.click(screen.getByRole("button", { name: "发送" }));
    await vi.waitFor(() => expect(onSave).toHaveBeenCalledWith({ question: "我的问题", answer: "回答" }));
  });
});

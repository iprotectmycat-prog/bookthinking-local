import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { ReactNode } from "react";
import { describe, expect, it, vi } from "vitest";

vi.mock("react-pdf", () => ({
  pdfjs: { GlobalWorkerOptions: { workerSrc: "" } },
  Document: ({
    children,
    onLoadSuccess,
  }: {
    children: ReactNode;
    onLoadSuccess: (value: { numPages: number }) => void;
  }) => (
    <div data-testid="pdf-document">
      <button onClick={() => onLoadSuccess({ numPages: 3 })}>finish PDF load</button>
      {children}
    </div>
  ),
  Page: ({ pageNumber, scale }: { pageNumber: number; scale: number }) => (
    <div data-testid="pdf-page" data-page={pageNumber} data-scale={scale} />
  ),
}));

import { PdfReader } from "../components/PdfReader";

describe("PdfReader", () => {
  it("uses the browser's dark color scheme for the PDF display", () => {
    const matchMedia = vi.fn(() => ({
      matches: true,
      addEventListener: vi.fn(),
      removeEventListener: vi.fn(),
    }));
    Object.defineProperty(window, "matchMedia", { configurable: true, value: matchMedia });

    render(<PdfReader data={new Uint8Array([1]).buffer} page={1} onError={() => undefined} />);

    expect(screen.getByLabelText("原书 PDF 阅读器")).toHaveAttribute("data-color-scheme", "dark");
  });

  it("starts at the evidence page and navigates within document bounds", async () => {
    const user = userEvent.setup();
    render(<PdfReader data={new Uint8Array([1]).buffer} page={2} onError={() => undefined} />);

    await user.click(screen.getByRole("button", { name: "finish PDF load" }));
    expect(screen.getByTestId("pdf-page")).toHaveAttribute("data-page", "2");
    expect(screen.getByText("第 2 / 3 页")).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "下一页" }));
    expect(screen.getByTestId("pdf-page")).toHaveAttribute("data-page", "3");
    expect(screen.getByRole("button", { name: "下一页" })).toBeDisabled();
  });

  it("offers bounded zoom controls without a download action", async () => {
    const user = userEvent.setup();
    render(<PdfReader data={new Uint8Array([1]).buffer} page={1} onError={() => undefined} />);

    await user.click(screen.getByRole("button", { name: "finish PDF load" }));
    await user.click(screen.getByRole("button", { name: "放大" }));

    expect(screen.getByTestId("pdf-page")).toHaveAttribute("data-scale", "1.25");
    expect(screen.queryByRole("button", { name: "下载" })).not.toBeInTheDocument();
  });
});

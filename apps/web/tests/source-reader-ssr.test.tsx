// @vitest-environment node

import { renderToString } from "react-dom/server";
import { describe, expect, it } from "vitest";

import { SourceReaderContent } from "../components/SourceReaderContent";

describe("SourceReaderContent server rendering", () => {
  it("does not evaluate browser-only PDF.js code on the server", () => {
    expect(() =>
      renderToString(
        <SourceReaderContent
          bookId="book-1"
          target={{ format: "pdf", page: 1, quote: null, requestId: 1 }}
        />,
      ),
    ).not.toThrow();
  });
});

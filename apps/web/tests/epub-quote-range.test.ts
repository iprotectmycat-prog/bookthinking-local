import { afterEach, describe, expect, it } from "vitest";

import { findEpubQuoteRange } from "../lib/epub-quote-range";

afterEach(() => {
  document.body.innerHTML = "";
});

describe("findEpubQuoteRange", () => {
  it("finds an exact quote across EPUB inline nodes and whitespace", () => {
    document.body.innerHTML = "<p>凯恩斯认为 <em>有效需求</em>\n决定就业。</p>";

    const range = findEpubQuoteRange(document, "凯恩斯认为有效需求决定就业。");

    expect(range?.toString()).toBe("凯恩斯认为 有效需求\n决定就业。");
  });

  it("returns null when the complete quote is absent", () => {
    document.body.innerHTML = "<p>有效需求决定就业。</p>";

    expect(findEpubQuoteRange(document, "储蓄决定利率。")).toBeNull();
  });

  it("returns null when an exact quote appears more than once without surrounding text", () => {
    document.body.innerHTML = "<p>第一处：有效需求决定就业。</p><p>第二处：有效需求决定就业。</p>";

    expect(findEpubQuoteRange(document, "有效需求决定就业。")).toBeNull();
  });

  it("uses exact surrounding text to disambiguate repeated quotes", () => {
    document.body.innerHTML = "<p>第一处：有效需求决定就业。</p><p>第二处：有效需求决定就业。</p>";

    const range = findEpubQuoteRange(
      document,
      "有效需求决定就业。",
      "第二处：有效需求决定就业。",
    );

    expect(range?.toString()).toBe("有效需求决定就业。");
    expect(range?.startContainer.parentElement?.textContent).toBe("第二处：有效需求决定就业。");
  });
});

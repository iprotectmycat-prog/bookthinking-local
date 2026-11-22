import { describe, expect, it } from "vitest";

import {
  epubDisplayTarget,
  epubDisplayTargetForSpine,
  epubInitialDisplayTarget,
  epubLocatorSearchParams,
  parseEpubSourceLocator,
} from "../lib/epub-locator";

describe("EPUB locators", () => {
  it("keeps a publisher fragment as the primary display target", () => {
    const locator = parseEpubSourceLocator("OEBPS/text00004.html#bubble", 6);
    expect(locator).toEqual({
      href: "OEBPS/text00004.html",
      fragment: "bubble",
      cfi: null,
      spineIndex: 5,
    });
    expect(epubDisplayTarget(locator)).toBe("OEBPS/text00004.html#bubble");
  });

  it("uses the legacy zero-based spine only when href is absent", () => {
    const locator = parseEpubSourceLocator(null, 6);
    expect(epubDisplayTarget(locator)).toBe(5);
  });

  it("opens archive-qualified locators by spine, then resolves their fragment against epub.js href", () => {
    const locator = parseEpubSourceLocator("OEBPS/text00004.html#bubble", 6);

    expect(epubInitialDisplayTarget(locator)).toBe(5);
    expect(epubDisplayTargetForSpine(locator, "text00004.html")).toBe("text00004.html#bubble");
  });

  it("serializes a stable standalone-reader URL without CFI", () => {
    const params = epubLocatorSearchParams({
      href: "OEBPS/text00004.html",
      fragment: "bubble",
      cfi: "epubcfi(/6/8!/4/2:0)",
      spineIndex: 5,
    });
    expect(params.toString()).toBe(
      "href=OEBPS%2Ftext00004.html&fragment=bubble&spine=6",
    );
  });

  it("prefers a persistent href and fragment when CFI is also present", () => {
    expect(
      epubDisplayTarget({
        href: "OEBPS/text00004.html",
        fragment: "bubble",
        cfi: "epubcfi(/6/8!/4/2:0)",
        spineIndex: 5,
      }),
    ).toBe("OEBPS/text00004.html#bubble");
  });
});

import { describe, expect, it } from "vitest";

import { sourceReaderPresentation } from "../lib/source-reader";

describe("sourceReaderPresentation", () => {
  it("labels EPUB evidence as a spine-document segment instead of a physical page", () => {
    expect(sourceReaderPresentation({
      format: "epub",
      locator: { href: null, fragment: null, cfi: null, spineIndex: 1 },
      quote: null,
      surroundingText: null,
      requestId: 1,
    })).toEqual({
      location: "章节片段 2",
      description: "这里显示你上传的原始 EPUB，证据位置按书内章节片段顺序标记。",
      openLabel: "在原书中阅读",
      embedded: true,
    });
  });
});

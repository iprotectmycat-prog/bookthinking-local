import { describe, expect, it } from "vitest";

import { buildChapterTree, classifyChapter, isBodyContent, resolveChapterKind } from "../lib/chapter-tree";
import type { ChapterOverview } from "../lib/types";

function chapter(overrides: Partial<ChapterOverview> & { title: string }): ChapterOverview {
  return {
    id: Math.floor(Math.random() * 100000),
    position: 0,
    source_start_page: 1,
    source_end_page: 1,
    chapter_question: "",
    one_sentence_conclusion: "",
    core_idea_titles: [],
    role_in_book: "",
    estimated_reading_minutes: 3,
    generation_status: "pending",
    failure_reason: null,
    ...overrides,
  };
}

describe("resolveChapterKind", () => {
  it("trusts the kind the parser read from the source file", () => {
    const resolved = resolveChapterKind(chapter({ title: "看不出类型的标题", nav_kind: "part" }));

    expect(resolved).toBe("part");
  });

  it("ignores an unrecognised kind rather than rendering an unknown class", () => {
    const resolved = resolveChapterKind(chapter({ title: "第三章 论述", nav_kind: "sparkles" }));

    expect(resolved).toBe("chapter");
  });

  it("falls back to the title when the source file carried no structure", () => {
    const resolved = resolveChapterKind(chapter({ title: "第二章 财税与政府行为" }));

    expect(resolved).toBe("chapter");
  });
});

describe("classifyChapter", () => {
  it("separates a chapter's closing section from the book's afterword", () => {
    expect(classifyChapter("结语", 2)).toBe("section");
    expect(classifyChapter("结束语", 0)).toBe("back_matter");
  });

  it("does not let 结束语 be mistaken for 结语 through prefix matching", () => {
    expect(classifyChapter("结束语", 2)).toBe("section");
    expect(classifyChapter("结语", 0)).toBe("back_matter");
  });

  it("treats a nested entry as a chapter when it is not a numbered section", () => {
    expect(classifyChapter("第一章 地方政府的权力与事务", 1)).toBe("chapter");
    expect(classifyChapter("第一节 政府治理的特点", 2)).toBe("section");
  });

  it("recognises parts, front matter and appendices", () => {
    expect(classifyChapter("上篇 微观机制")).toBe("part");
    expect(classifyChapter("版权页")).toBe("front_matter");
    expect(classifyChapter("附录 一 数据来源")).toBe("back_matter");
  });
});

describe("isBodyContent", () => {
  it("excludes both ends of the book from body content", () => {
    expect(isBodyContent("front_matter")).toBe(false);
    expect(isBodyContent("back_matter")).toBe(false);
    expect(isBodyContent("chapter")).toBe(true);
    expect(isBodyContent("section")).toBe(true);
  });
});

describe("buildChapterTree", () => {
  it("attaches a repeated section to the chapter that declares it as parent", () => {
    // Regression: every chapter of 《置身事内》 ends with a "结语", and matching on the
    // most recent node alone put them all under whichever chapter came last.
    const tree = buildChapterTree([
      chapter({ title: "第一章 权力与事务", nav_kind: "chapter", depth: 1, parent_title: "上篇 微观机制" }),
      chapter({ title: "结语", nav_kind: "section", depth: 2, parent_title: "第一章 权力与事务" }),
      chapter({ title: "第二章 财税行为", nav_kind: "chapter", depth: 1, parent_title: "上篇 微观机制" }),
      chapter({ title: "结语", nav_kind: "section", depth: 2, parent_title: "第二章 财税行为" }),
    ]);

    expect(tree.map((node) => node.chapter.title)).toEqual(["第一章 权力与事务", "第二章 财税行为"]);
    expect(tree[0].children).toHaveLength(1);
    expect(tree[1].children).toHaveLength(1);
  });

  it("keeps a section under its declared parent even when entries are interleaved", () => {
    const tree = buildChapterTree([
      chapter({ title: "第一章", nav_kind: "chapter", depth: 1 }),
      chapter({ title: "第二章", nav_kind: "chapter", depth: 1 }),
      chapter({ title: "扩展阅读", nav_kind: "section", depth: 2, parent_title: "第一章" }),
    ]);

    expect(tree[0].children.map((child) => child.chapter.title)).toEqual(["扩展阅读"]);
    expect(tree[1].children).toEqual([]);
  });

  it("still nests by proximity when the backend sent no structure", () => {
    const tree = buildChapterTree([
      chapter({ title: "第一章 地方政府的权力与事务" }),
      chapter({ title: "第一节 政府治理的特点" }),
      chapter({ title: "第二章 财税与政府行为" }),
    ]);

    expect(tree).toHaveLength(2);
    expect(tree[0].children.map((child) => child.chapter.title)).toEqual(["第一节 政府治理的特点"]);
  });

  it("represents the full part to chapter to section hierarchy", () => {
    const tree = buildChapterTree([
      chapter({ title: "上篇 微观机制", nav_kind: "part", depth: 0 }),
      chapter({ title: "第一章 权力与事务", nav_kind: "chapter", depth: 1, parent_title: "上篇 微观机制" }),
      chapter({ title: "第一节 治理特点", nav_kind: "section", depth: 2, parent_title: "第一章 权力与事务" }),
    ]);

    expect(tree.map((node) => node.kind)).toEqual(["part"]);
    expect(tree[0].children.map((node) => node.kind)).toEqual(["chapter"]);
    expect(tree[0].children[0].children.map((node) => node.kind)).toEqual(["section"]);
  });

  it("nests an unnumbered publisher child below its top-level chapter", () => {
    const tree = buildChapterTree([
      chapter({ title: "第一章 日本人没有察觉到泡沫经济的崩溃", nav_kind: "chapter", depth: 0 }),
      chapter({
        title: "20世纪80年代，日本的国际地位逐步上升",
        nav_kind: "chapter",
        depth: 1,
        parent_title: "第一章 日本人没有察觉到泡沫经济的崩溃",
      }),
    ]);

    expect(tree).toHaveLength(1);
    expect(tree[0].children.map((child) => child.chapter.title)).toEqual([
      "20世纪80年代，日本的国际地位逐步上升",
    ]);
    expect(tree[0].children[0].kind).toBe("section");
  });
});

import { describe, expect, it } from "vitest";

import { buildEditableChapterGroups } from "../lib/editable-chapter-tree";
import type { EditableChapter } from "../lib/types";

describe("buildEditableChapterGroups", () => {
  it("groups a publisher child even when nav_kind calls it a chapter", () => {
    const drafts: EditableChapter[] = [
      {
        title: "第二章 揭秘海龟思维",
        source_start_page: 14,
        source_end_page: 14,
        depth: 0,
        nav_kind: "chapter",
      },
      {
        title: "情绪陷阱",
        source_start_page: 15,
        source_end_page: 15,
        depth: 1,
        parent_title: "第二章 揭秘海龟思维",
        nav_kind: "chapter",
      },
    ];

    const groups = buildEditableChapterGroups(drafts);

    expect(groups).toHaveLength(1);
    expect(groups[0].children.map((child) => child.chapter.title)).toEqual(["情绪陷阱"]);
  });

  it("keeps an orphaned nested entry visible as a standalone group", () => {
    const orphan: EditableChapter = {
      title: "孤立小节",
      source_start_page: 2,
      source_end_page: 2,
      depth: 1,
      parent_title: "不存在的章节",
    };

    expect(buildEditableChapterGroups([orphan])).toEqual([{ chapter: orphan, children: [] }]);
  });

  it("keeps children grouped while a parent title is temporarily empty during editing", () => {
    const parent: EditableChapter = {
      title: "",
      source_start_page: 1,
      source_end_page: 1,
      depth: 0,
    };
    const child: EditableChapter = {
      title: "小节",
      source_start_page: 2,
      source_end_page: 2,
      depth: 1,
      parent_title: "",
    };

    expect(buildEditableChapterGroups([parent, child])).toEqual([
      { chapter: parent, children: [{ chapter: child, children: [] }] },
    ]);
  });

  it("keeps publisher parts as the parents of their nested chapters", () => {
    const part: EditableChapter = {
      title: "第一部分 财富",
      source_start_page: 11,
      source_end_page: 11,
      depth: 0,
      parent_title: null,
      nav_kind: "part",
    };
    const chapter: EditableChapter = {
      title: "第一章 积累财富",
      source_start_page: 12,
      source_end_page: 12,
      depth: 1,
      parent_title: "第一部分 财富",
      nav_kind: "chapter",
    };
    const section: EditableChapter = {
      title: "认识财富创造的原理",
      source_start_page: 13,
      source_end_page: 13,
      depth: 2,
      parent_title: "第一章 积累财富",
      nav_kind: "section",
    };

    expect(buildEditableChapterGroups([part, chapter, section])).toEqual([
      {
        chapter: part,
        children: [
          {
            chapter,
            children: [{ chapter: section, children: [] }],
          },
        ],
      },
    ]);
  });
});

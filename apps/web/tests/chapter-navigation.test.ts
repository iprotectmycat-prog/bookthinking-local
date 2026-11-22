import { describe, expect, it } from "vitest";

import { findAdjacentReadable, findNextReadyChapter } from "../lib/chapter-navigation";
import type { AnalysisStatus, ChapterOverview } from "../lib/types";

function chapter(id: number, title: string, status: AnalysisStatus): ChapterOverview {
  return {
    id,
    position: id,
    title,
    source_start_page: id,
    source_end_page: id,
    chapter_question: "",
    one_sentence_conclusion: "",
    core_idea_titles: [],
    role_in_book: "",
    estimated_reading_minutes: 3,
    generation_status: status,
    failure_reason: null,
  };
}

// 《置身事内》的真实开头：前 3 个片段都是没有正文的结构页。
const chapters = [
  chapter(1, "书名页", "skipped"),
  chapter(2, "版权页", "skipped"),
  chapter(3, "目录", "skipped"),
  chapter(4, "前言 从了解现状开始", "ready"),
  chapter(5, "上篇 微观机制", "skipped"),
  chapter(6, "第一章 地方政府的权力与事务", "ready"),
  chapter(7, "第二节 中美贸易冲突", "failed"),
  chapter(8, "第三节 复杂信息", "ready"),
];

describe("findAdjacentReadable", () => {
  it("skips structural pages when walking backwards", () => {
    // 后端给的 previous_chapter_id 是 3（目录），会把读者送进空白页。
    expect(findAdjacentReadable(chapters, 4, -1)).toBeNull();
  });

  it("skips the volume divider when walking forwards", () => {
    // 第 5 项「上篇 微观机制」只有标题没有正文，应直接跨到第一章。
    expect(findAdjacentReadable(chapters, 4, 1)).toBe(6);
  });

  it("still stops on a failed chapter so the reader can retry there", () => {
    expect(findAdjacentReadable(chapters, 6, 1)).toBe(7);
  });

  it("returns null at the end of the book", () => {
    expect(findAdjacentReadable(chapters, 8, 1)).toBeNull();
  });

  it("returns null for an unknown chapter", () => {
    expect(findAdjacentReadable(chapters, 999, 1)).toBeNull();
  });
});

describe("findNextReadyChapter", () => {
  it("offers the next readable chapter as an escape from a failed one", () => {
    expect(findNextReadyChapter(chapters, 7)).toBe(8);
  });

  it("looks backwards when nothing readable follows", () => {
    const tail = [chapter(1, "第一章", "ready"), chapter(2, "第二章", "failed")];
    expect(findNextReadyChapter(tail, 2)).toBe(1);
  });

  it("returns null when no chapter is readable at all", () => {
    const broken = [chapter(1, "第一章", "failed"), chapter(2, "第二章", "failed")];
    expect(findNextReadyChapter(broken, 1)).toBeNull();
  });
});

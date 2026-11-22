import type { ChapterOverview } from "./types";

export type ChapterKind = "front_matter" | "part" | "chapter" | "section" | "back_matter" | "plain";

export type ChapterTreeLeaf = {
  chapter: ChapterOverview;
  kind: ChapterKind;
};

export type ChapterTreeNode = ChapterTreeLeaf & {
  children: ChapterTreeNode[];
};

// Anchored on purpose: "结语" (a chapter's closing section) and "结束语" (the book's
// afterword) differ by one character, so prefix matching would conflate them.
const FRONT_MATTER = /^(封面|书名页|版权页|目录|扉页|献词|题献|出版说明|内容简介|作者简介)$/;
const BACK_MATTER = /^(参考文献|注释|注解|索引|后记|致谢|鸣谢|结束语|结语|出版后记|译后记|跋)$/;
const BACK_MATTER_PREFIX = /^(附录|附表|附图|参考文献|注释)([\s:：]|[一二三四五六七八九十百千零〇\d])/;
const PART = /^(上篇|中篇|下篇|上册|下册|第[一二三四五六七八九十百千零〇\d]+(部分|篇|卷)|Part\s)/;
const CHAPTER = /^(前言|序言|自序|他序|导论|引言|绪论|第[一二三四五六七八九十百千零〇\d]+章|Chapter\s)/;
const SECTION_PREFIX = /^第[一二三四五六七八九十百千零〇\d]+节/;
const SECTION = /^(扩展阅读|延伸阅读|小结|本章小结|思考题)$/;

const KNOWN_KINDS = new Set<ChapterKind>([
  "front_matter",
  "part",
  "chapter",
  "section",
  "back_matter",
  "plain",
]);

function isChapterKind(value: string | undefined): value is ChapterKind {
  return value !== undefined && KNOWN_KINDS.has(value as ChapterKind);
}

/**
 * Classify by title wording alone.
 *
 * This is the fallback path. It only runs when the source file gave us no structure
 * (PDF imports, EPUBs with a broken or missing navigation document).
 */
export function classifyChapter(title: string, depth = 0): ChapterKind {
  const text = title.trim();
  if (FRONT_MATTER.test(text)) return "front_matter";
  if (BACK_MATTER.test(text) || BACK_MATTER_PREFIX.test(text)) {
    // Nested under a chapter this is that chapter's closing section, not an afterword.
    return depth > 0 ? "section" : "back_matter";
  }
  if (depth > 0) {
    if (depth > 1 || SECTION_PREFIX.test(text) || SECTION.test(text)) return "section";
    return "chapter";
  }
  if (PART.test(text)) return "part";
  if (CHAPTER.test(text)) return "chapter";
  if (SECTION_PREFIX.test(text) || SECTION.test(text)) return "section";
  return "plain";
}

/**
 * Resolve one chapter's kind, preferring what the publisher declared.
 *
 * The source file's navigation already encodes the outline, so `nav_kind` wins when
 * present. Guessing from the title is strictly a fallback.
 */
export function resolveChapterKind(chapter: ChapterOverview): ChapterKind {
  if (isChapterKind(chapter.nav_kind)) return chapter.nav_kind;
  return classifyChapter(chapter.title, chapter.depth ?? 0);
}

export function isBodyContent(kind: ChapterKind): boolean {
  return kind !== "front_matter" && kind !== "back_matter";
}

export function buildChapterTree(chapters: ChapterOverview[]): ChapterTreeNode[] {
  const nodes: ChapterTreeNode[] = [];
  // The sidebar renders two levels, so the tree is flattened to match: every entry is
  // either a top-level node or a child of the nearest enclosing node. Attachment is
  // driven by parent_title when the backend supplies it, which keeps a repeated
  // "结语" under the chapter that actually contains it rather than the last one seen.
  const nodesByTitle = new Map<string, ChapterTreeNode>();
  let previousNode: ChapterTreeNode | null = null;

  for (const chapter of chapters) {
    const resolvedKind = resolveChapterKind(chapter);
    const declaredParent = chapter.parent_title?.trim();
    const parent = declaredParent ? nodesByTitle.get(declaredParent) ?? null : previousNode;
    // Old imports can carry the correct parent relationship but a stale `chapter`
    // label. Relative structure disambiguates it without misclassifying chapters
    // nested below a `part`.
    const kind = declaredParent && parent?.kind === "chapter" && resolvedKind === "chapter"
      ? "section"
      : resolvedKind;
    const node: ChapterTreeNode = { chapter, kind, children: [] };
    const attachesToDeclaredParent = parent && (
      (parent.kind === "part" && kind === "chapter")
      || (parent.kind === "chapter" && kind === "section")
    );
    const attachesByProximity = !declaredParent && parent?.kind === "chapter" && kind === "section";

    if (attachesToDeclaredParent || attachesByProximity) parent.children.push(node);
    else nodes.push(node);
    nodesByTitle.set(chapter.title.trim(), node);
    if (kind === "chapter" || kind === "part") previousNode = node;
    else if (kind !== "section") previousNode = null;
  }

  return nodes;
}

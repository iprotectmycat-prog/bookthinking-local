import type { ChapterOverview } from "./types";

/**
 * 「上一章 / 下一章」应当落在读者真正能读的章节上。
 *
 * 后端的 previous_chapter_id / next_chapter_id 是按章节序号直接取相邻项，
 * 会把读者顺序送进封面、版权页、目录、分卷标题这类 skipped 结构页 ——
 * 那些页面没有正文，读者只会看到一个空白页然后卡住。
 *
 * 这里按方向跳过所有 skipped 片段。failed / insufficient_evidence 不跳过：
 * 它们本该有正文，读者需要看到失败提示并能就地重试。
 */
export function findAdjacentReadable(
  chapters: ChapterOverview[],
  currentId: number,
  direction: 1 | -1,
): number | null {
  const index = chapters.findIndex((chapter) => chapter.id === currentId);
  if (index < 0) return null;

  for (let cursor = index + direction; cursor >= 0 && cursor < chapters.length; cursor += direction) {
    if (chapters[cursor].generation_status !== "skipped") return chapters[cursor].id;
  }
  return null;
}

/**
 * 当前章无法阅读时，指向下一个 ready 章节，让读者有明确出路。
 * 与 findAdjacentReadable 不同，这里要求状态必须是 ready ——
 * 把人从一个失败章送进另一个失败章毫无意义。
 */
export function findNextReadyChapter(
  chapters: ChapterOverview[],
  currentId: number,
): number | null {
  const index = chapters.findIndex((chapter) => chapter.id === currentId);
  if (index < 0) return null;

  for (let cursor = index + 1; cursor < chapters.length; cursor += 1) {
    if (chapters[cursor].generation_status === "ready") return chapters[cursor].id;
  }
  for (let cursor = index - 1; cursor >= 0; cursor -= 1) {
    if (chapters[cursor].generation_status === "ready") return chapters[cursor].id;
  }
  return null;
}

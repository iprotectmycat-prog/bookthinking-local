import type { EditableChapter } from "./types";

export type EditableChapterGroup<T extends EditableChapter = EditableChapter> = {
  chapter: T;
  children: EditableChapterGroup<T>[];
};

export function buildEditableChapterGroups<T extends EditableChapter>(
  chapters: T[],
): EditableChapterGroup<T>[] {
  const groups: EditableChapterGroup<T>[] = [];
  const parentsByTitle = new Map<string, EditableChapterGroup<T>>();

  for (const chapter of chapters) {
    const declaredParent = chapter.parent_title?.trim();
    const parent = chapter.parent_title == null
      ? undefined
      : parentsByTitle.get(declaredParent ?? "");

    const group = { chapter, children: [] } satisfies EditableChapterGroup<T>;
    if ((chapter.depth ?? 0) > 0 && parent) {
      parent.children.push(group);
    } else {
      groups.push(group);
    }
    parentsByTitle.set(chapter.title.trim(), group);
  }

  return groups;
}

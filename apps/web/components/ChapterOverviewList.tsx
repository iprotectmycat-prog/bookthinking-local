import { buildChapterTree, type ChapterTreeNode } from "../lib/chapter-tree";
import type { ChapterOverview } from "../lib/types";
import { ChapterOverviewCard } from "./ChapterOverviewCard";

type Props = {
  bookId: string;
  chapters: ChapterOverview[];
  onRetry?: (id: number) => void;
  retryingChapterId: number | null;
};

export function ChapterOverviewList({ bookId, chapters, onRetry, retryingChapterId }: Props) {
  function isVisible(node: ChapterTreeNode): boolean {
    return node.chapter.generation_status !== "skipped"
      || node.chapter.analysis_role === "outline_only" && node.children.some(isVisible);
  }

  function renderNode(node: ChapterTreeNode) {
    const outlineOnly = node.chapter.analysis_role === "outline_only";
    const visibleChildren = node.children.filter(isVisible);
    if (outlineOnly && visibleChildren.length === 0) return null;
    if (!outlineOnly && node.chapter.generation_status === "skipped") return null;

    if (visibleChildren.length === 0) {
      return (
        <ChapterOverviewCard
          key={node.chapter.id}
          bookId={bookId}
          chapter={node.chapter}
          level={node.kind === "section" ? "section" : undefined}
          onRetry={onRetry}
          retrying={retryingChapterId === node.chapter.id}
        />
      );
    }

    return (
      <section className={`chapter-overview-group kind-${node.kind}`} id={outlineOnly ? `chapter-${node.chapter.id}` : undefined} key={node.chapter.id}>
        {outlineOnly ? (
          <header className="chapter-group-heading">
            <span>{visibleChildren.length} {node.kind === "part" ? "章" : "个小节"}</span>
            <h2>{node.chapter.title}</h2>
          </header>
        ) : (
          <ChapterOverviewCard
            bookId={bookId}
            chapter={node.chapter}
            level={node.kind === "section" ? "section" : undefined}
            onRetry={onRetry}
            retrying={retryingChapterId === node.chapter.id}
          />
        )}
        <div className="chapter-section-list">
          {visibleChildren.map(renderNode)}
        </div>
      </section>
    );
  }

  return (
    <>
      {buildChapterTree(chapters).map(renderNode)}
    </>
  );
}

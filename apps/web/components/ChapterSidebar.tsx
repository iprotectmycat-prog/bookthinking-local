"use client";

import { useEffect, useId, useRef, useState } from "react";

import { buildChapterTree, isBodyContent, type ChapterTreeLeaf, type ChapterTreeNode } from "../lib/chapter-tree";
import type { ChapterOverview } from "../lib/types";
import { AnalysisStatus } from "./AnalysisStatus";

/**
 * anchor: 总览页 —— 有卡片的章节滚动到卡片，没卡片的（skipped）跳到章节页。
 * page:   单章页 —— 一律跳到对应章节页。
 */
type LinkMode = "anchor" | "page";

const PREFACE_TITLE = /^(前言|序言|自序|他序|译序|推荐序|序)(?:\s|[:：]|$)/;

function bodyChapterTree(nodes: ChapterTreeNode[]): ChapterTreeNode[] {
  return nodes.flatMap((node) => {
    const { chapter, kind } = node;
    if (chapter.structural_role === "front_matter" || chapter.structural_role === "back_matter") return [];
    const children = bodyChapterTree(node.children);
    if (kind === "part") return children.length ? [{ ...node, children }] : [];
    const isBody = chapter.structural_role === "body" || (
      chapter.in_body !== false && isBodyContent(kind) && (kind === "section" || !PREFACE_TITLE.test(chapter.title.trim()))
    );
    return isBody ? [{ ...node, children }] : [];
  });
}

function chapterHref(chapter: ChapterOverview, bookId: string, linkMode: LinkMode): string {
  // 过去所有非 ready 章节都退回 `#chapter-N`，但总览主列表已过滤掉 skipped 片段，
  // 那些锚点在 DOM 里并不存在 —— 点击毫无反应（死链）。现在只在确实存在卡片时
  // 才使用锚点，其余一律给出真实页面地址。
  const hasCard = chapter.generation_status !== "skipped";
  if (linkMode === "anchor" && hasCard) return `#chapter-${chapter.id}`;
  return `/books/${bookId}/chapters/${chapter.id}`;
}

function renderLeaf(leaf: ChapterTreeLeaf, bookId: string, linkMode: LinkMode, activeId?: number, isParent = false) {
  const { chapter } = leaf;
  const isActive = activeId === chapter.id;

  if (chapter.analysis_role === "outline_only") {
    return (
      <a
        className={`tree-link${isParent ? " is-parent" : ""}`}
        href={linkMode === "anchor" ? `#chapter-${chapter.id}` : `/books/${bookId}/overview#chapter-${chapter.id}`}
        data-chapter-link={chapter.id}
      >
        <span className="sidebar-title">{chapter.title}</span>
      </a>
    );
  }

  return (
    <a
      className={`tree-link${isActive ? " is-current" : ""}${isParent ? " is-parent" : ""}`}
      href={chapterHref(chapter, bookId, linkMode)}
      aria-current={isActive ? "page" : undefined}
      data-chapter-link={chapter.id}
    >
      <span className="sidebar-title">{chapter.title}</span>
      {chapter.generation_status !== "ready" && chapter.generation_status !== "skipped" && (
        <AnalysisStatus status={chapter.generation_status} />
      )}
    </a>
  );
}

function TreeBranch({ node, bookId, linkMode, activeId }: { node: ChapterTreeNode; bookId: string; linkMode: LinkMode; activeId?: number }) {
  const containsActive = (candidate: ChapterTreeNode): boolean =>
    candidate.chapter.id === activeId || candidate.children.some(containsActive);
  const activeChildId = node.children.find(containsActive)?.chapter.id;
  const [branchState, setBranchState] = useState(() => ({
    activeChildId,
    open: activeId === node.chapter.id || activeChildId !== undefined || node.kind === "part",
  }));

  // 滚动高亮落到折叠起来的小节上时，自动展开对应分支，否则读者看不到高亮在哪。
  if (activeChildId !== branchState.activeChildId) {
    setBranchState({
      activeChildId,
      open: activeChildId === undefined ? branchState.open : true,
    });
  }
  const open = branchState.open;

  return (
    <li className={`tree-node kind-${node.kind} has-children${open ? " is-open" : ""}`}>
      <div className="branch-head">
        <button
          type="button"
          className="branch-toggle"
          aria-expanded={open}
          aria-label={open ? "收起本章小节" : "展开本章小节"}
          onClick={() => setBranchState((state) => ({ ...state, open: !state.open }))}
        >
          <span aria-hidden="true">{open ? "▾" : "▸"}</span>
        </button>
        {renderLeaf(node, bookId, linkMode, activeId, true)}
      </div>
      {open && (
        <ol className="tree-children">
          {node.children.map((child) => (
            child.children.length > 0
              ? <TreeBranch key={child.chapter.id} node={child} bookId={bookId} linkMode={linkMode} activeId={activeId} />
              : <li key={child.chapter.id} className={`tree-node kind-${child.kind}`}>{renderLeaf(child, bookId, linkMode, activeId)}</li>
          ))}
        </ol>
      )}
    </li>
  );
}

type ChapterSidebarProps = {
  bookId: string;
  chapters: ChapterOverview[];
  activeId?: number;
  isOpen?: boolean;
  onOpenChange?: (open: boolean) => void;
  linkMode?: LinkMode;
  bodyOnly?: boolean;
};

export function ChapterSidebar({
  bookId,
  chapters,
  activeId,
  isOpen,
  onOpenChange,
  linkMode = "page",
  bodyOnly = false,
}: ChapterSidebarProps) {
  const chapterTree = buildChapterTree(chapters);
  const tree = bodyOnly ? bodyChapterTree(chapterTree) : chapterTree;
  const [mobileOpen, setMobileOpen] = useState(false);
  const [sidebarWidth, setSidebarWidth] = useState(260);
  const sidebarId = useId();
  const toggleRef = useRef<HTMLButtonElement>(null);
  const scrollRef = useRef<HTMLDivElement>(null);
  const directoryOpen = isOpen ?? true;
  const isControlled = isOpen !== undefined;

  useEffect(() => {
    if (!mobileOpen) return;
    if (!window.matchMedia) return;
    const desktop = window.matchMedia("(min-width: 1180px)");
    function closeOnDesktop() {
      if (desktop.matches) setMobileOpen(false);
    }
    desktop.addEventListener("change", closeOnDesktop);
    return () => desktop.removeEventListener("change", closeOnDesktop);
  }, [mobileOpen]);

  function closeDrawer() {
    setMobileOpen(false);
    toggleRef.current?.focus({ preventScroll: true });
  }

  // 侧栏本身可滚（59 个条目高于视口），高亮项若在视口外等于没有高亮。
  useEffect(() => {
    if (activeId === undefined) return;
    const container = scrollRef.current;
    const link = container?.querySelector<HTMLElement>(`[data-chapter-link="${activeId}"]`);
    if (!container || !link || getComputedStyle(container).visibility === "hidden") return;
    const linkBox = link.getBoundingClientRect();
    const containerBox = container.getBoundingClientRect();
    if (linkBox.top < containerBox.top || linkBox.bottom > containerBox.bottom) {
      container.scrollTop += linkBox.top - containerBox.top;
    }
  }, [activeId, mobileOpen]);

  function applyWidth(width: number) {
    const boundedWidth = Math.min(340, Math.max(200, width));
    setSidebarWidth(boundedWidth);
    document.documentElement.style.setProperty("--sidebar-width", `${boundedWidth}px`);
    document.documentElement.style.setProperty("--workspace-directory-width", `${boundedWidth}px`);
  }

  function startResize(event: React.PointerEvent<HTMLDivElement>) {
    event.preventDefault();
    const initialX = event.clientX;
    const initialWidth = sidebarWidth;
    const updateWidth = (moveEvent: PointerEvent) => applyWidth(initialWidth + moveEvent.clientX - initialX);
    const stopResize = () => {
      window.removeEventListener("pointermove", updateWidth);
      window.removeEventListener("pointerup", stopResize);
    };

    window.addEventListener("pointermove", updateWidth);
    window.addEventListener("pointerup", stopResize, { once: true });
  }

  return (
    <>
      <button ref={toggleRef} className="sidebar-toggle" type="button" aria-label={mobileOpen ? "收起章节侧栏" : "展开章节侧栏"} aria-expanded={mobileOpen} aria-controls={sidebarId} onClick={() => setMobileOpen((open) => !open)} onKeyDown={(event) => {
        if (mobileOpen && event.key === "Escape") closeDrawer();
      }}>☰</button>
      {mobileOpen && <div className="sidebar-backdrop" onClick={closeDrawer} aria-hidden="true" />}
      <aside id={sidebarId} className={`chapter-sidebar${mobileOpen ? " is-open" : ""}${isControlled && !directoryOpen ? " is-collapsed" : ""}`} aria-label="章节目录" ref={scrollRef} onKeyDown={(event) => {
        if (mobileOpen && event.key === "Escape") closeDrawer();
      }}>
        <div className="chapter-sidebar-heading">
          <a className="sidebar-home" href={`/books/${bookId}/overview`} onClick={() => mobileOpen && setMobileOpen(false)}>
            {bodyOnly ? "目录" : "全书章节"}
          </a>
          {isControlled && (
            <button
              type="button"
              className="chapter-sidebar-directory-toggle"
              aria-label={directoryOpen ? "收起章节目录" : "展开章节目录"}
              aria-expanded={directoryOpen}
              onClick={() => onOpenChange?.(!directoryOpen)}
            >
              <span className="reading-left-triangle" aria-hidden="true" />
            </button>
          )}
        </div>
        {/* 移动端侧栏是覆盖层，点了条目要顺手收起，否则内容被挡住。 */}
        <div className="chapter-sidebar-content" onClick={(event) => {
          if (mobileOpen && event.target instanceof Element && event.target.closest("a")) setMobileOpen(false);
        }}>
          <ol className="chapter-tree">
            {tree.map((node) => {
              if (node.children.length === 0) {
                return <li key={node.chapter.id} className={`tree-node kind-${node.kind}`}>{renderLeaf(node, bookId, linkMode, activeId)}</li>;
              }
              return <TreeBranch key={node.chapter.id} node={node} bookId={bookId} linkMode={linkMode} activeId={activeId} />;
            })}
          </ol>
        </div>
        <div className="sidebar-resizer" role="separator" aria-label="调整侧边栏宽度" aria-orientation="vertical" aria-valuemin={200} aria-valuemax={340} aria-valuenow={sidebarWidth} tabIndex={0} onPointerDown={startResize} />
      </aside>
    </>
  );
}

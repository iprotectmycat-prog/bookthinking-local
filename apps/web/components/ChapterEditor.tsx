"use client";

import { useState } from "react";
import Link from "next/link";

import { apiJson } from "../lib/api";
import {
  buildEditableChapterGroups,
  type EditableChapterGroup,
} from "../lib/editable-chapter-tree";
import type { Book, EditableChapter } from "../lib/types";

type IndexedEditableChapter = EditableChapter & { editorIndex: number };
type EditorMutation = (index: number, patch: Partial<EditableChapter>) => void;
type EditorRemoval = (index: number) => void;

type EpubChapterBranchProps = {
  node: EditableChapterGroup<IndexedEditableChapter>;
  update: EditorMutation;
  remove: EditorRemoval;
};

type EpubChapterRowProps = {
  chapter: IndexedEditableChapter;
  update: EditorMutation;
  remove: EditorRemoval;
};

type EpubMatterGroupProps = {
  label: "前置内容" | "后置内容";
  nodes: EditableChapterGroup<IndexedEditableChapter>[];
  update: EditorMutation;
  remove: EditorRemoval;
};

const FRONT_MATTER_TITLE = /^(?:(?:中文版|英文版|修订版|再版|新版|第[一二三四五六七八九十百千零〇\d]+版))?(?:前言|序言|自序|他序|译序|推荐序|驳辞|导读|阅读提示|图书在版编目)/;
const FRONT_MATTER_SUFFIX = /(?:译丛序|丛书序)$/;
const FRONT_MATTER_READER_NOTE = /^致(?:《[^》]+》)?(?:中文版)?(?:的)?读者/;
const FRONT_MATTER_BARE_PREFACE = /^序(?:[:：]|\s|$)/;
const BACK_MATTER_TITLE = /(?:推荐书目|书目|年谱|后记|译丛|丛书|封底)$/;

function explicitStructuralRole(title: string): "front_matter" | "back_matter" | undefined {
  const compact = title.replace(/\s+/g, "");
  if (BACK_MATTER_TITLE.test(compact)) return "back_matter";
  if (
    FRONT_MATTER_TITLE.test(compact)
    || FRONT_MATTER_SUFFIX.test(compact)
    || FRONT_MATTER_READER_NOTE.test(compact)
    || FRONT_MATTER_BARE_PREFACE.test(title.replace(/\s+/g, " ").trim())
  ) return "front_matter";
  return undefined;
}

function reconcileStoredStructuralRoles(chapters: EditableChapter[]): EditableChapter[] {
  return chapters.map((chapter) => {
    const explicitRole = explicitStructuralRole(chapter.title);
    if (explicitRole) {
      const roleAlreadyMatches = chapter.structural_role === explicitRole && chapter.role_source !== "unknown";
      return {
        ...chapter,
        structural_role: explicitRole,
        role_source: roleAlreadyMatches ? chapter.role_source : "title_fallback",
        role_confidence: roleAlreadyMatches ? chapter.role_confidence : "medium",
      };
    }
    if (
      chapter.structural_role === "front_matter"
      && chapter.role_source === "publisher_landmark"
      && chapter.in_body === true
    ) {
      return {
        ...chapter,
        structural_role: "body",
        role_source: "content_signal",
        role_confidence: "medium",
      };
    }
    return chapter;
  });
}

function ChapterTitleInput({
  chapter,
  kind,
  onChange,
}: {
  chapter: IndexedEditableChapter;
  kind: "chapter" | "section";
  onChange: (title: string) => void;
}) {
  return (
    <label className="epub-title-field">
      <span className="visually-hidden">{kind === "chapter" ? "章节标题" : "小节标题"}</span>
      <input
        className="epub-title-input"
        value={chapter.title}
        onChange={(event) => onChange(event.target.value)}
      />
    </label>
  );
}

function RemoveButton({ title, onClick }: { title: string; onClick: () => void }) {
  return (
    <button
      type="button"
      className="epub-remove"
      aria-label={`移除「${title}」`}
      onClick={onClick}
    >
      移除
    </button>
  );
}

function EpubChapterRow({ chapter, update, remove }: EpubChapterRowProps) {
  const kind = chapter.nav_kind === "section" ? "section" : "chapter";
  const meta = kind === "section"
    ? "小节"
    : chapter.nav_kind === "front_matter"
      ? "前置内容"
      : chapter.nav_kind === "back_matter"
        ? "后置内容"
        : chapter.nav_kind === "part"
          ? "卷"
          : chapter.nav_kind === "chapter"
            ? "章节"
            : "独立章节";

  return (
    <article className={`epub-chapter-row is-${kind}`}>
      <span className="epub-row-spacer" aria-hidden="true" />
      <span className="chapter-edit-index">{String(chapter.editorIndex + 1).padStart(2, "0")}</span>
      <ChapterTitleInput
        chapter={chapter}
        kind={kind}
        onChange={(title) => update(chapter.editorIndex, { title })}
      />
      <span className="epub-row-meta">{meta}</span>
      <RemoveButton title={chapter.title} onClick={() => remove(chapter.editorIndex)} />
    </article>
  );
}

function EpubChapterBranch({ node, update, remove }: EpubChapterBranchProps) {
  const [open, setOpen] = useState(false);
  const parent = node.chapter;
  const childLabel = parent.nav_kind === "part" ? "章节" : "小节";

  return (
    <section className={`epub-chapter-group${open ? " is-open" : ""}`}>
      <div className="epub-chapter-head">
        <button
          type="button"
          className="epub-chapter-toggle"
          aria-expanded={open}
          aria-label={`${open ? "收起" : "展开"}「${parent.title}」的${childLabel}`}
          onClick={() => setOpen((value) => !value)}
        >
          <span aria-hidden="true">{open ? "−" : "+"}</span>
        </button>
        <span className="chapter-edit-index">{String(parent.editorIndex + 1).padStart(2, "0")}</span>
        <ChapterTitleInput
          chapter={parent}
          kind="chapter"
          onChange={(title) => update(parent.editorIndex, { title })}
        />
        <span className="epub-section-count">{node.children.length} 个{childLabel}</span>
        <RemoveButton title={parent.title} onClick={() => remove(parent.editorIndex)} />
      </div>
      {open && (
        <div className="epub-section-list">
          {node.children.map((child) => (
            <EpubChapterNode
              key={child.chapter.editorIndex}
              node={child}
              update={update}
              remove={remove}
            />
          ))}
        </div>
      )}
    </section>
  );
}

function EpubChapterNode({ node, update, remove }: EpubChapterBranchProps) {
  return node.children.length > 0 ? (
    <EpubChapterBranch node={node} update={update} remove={remove} />
  ) : (
    <EpubChapterRow chapter={node.chapter} update={update} remove={remove} />
  );
}

function flattenEpubChapterGroups(
  nodes: EditableChapterGroup<IndexedEditableChapter>[],
): IndexedEditableChapter[] {
  return nodes.flatMap((node) => [node.chapter, ...flattenEpubChapterGroups(node.children)]);
}

function findEpubChapterGroup(
  nodes: EditableChapterGroup<IndexedEditableChapter>[],
  editorIndex: number,
): EditableChapterGroup<IndexedEditableChapter> | undefined {
  for (const node of nodes) {
    if (node.chapter.editorIndex === editorIndex) return node;
    const child = findEpubChapterGroup(node.children, editorIndex);
    if (child) return child;
  }
  return undefined;
}

function EpubMatterGroup({ label, nodes, update, remove }: EpubMatterGroupProps) {
  const [open, setOpen] = useState(false);
  const chapters = flattenEpubChapterGroups(nodes);

  return (
    <section className={`epub-chapter-group epub-matter-group${open ? " is-open" : ""}`}>
      <div className="epub-chapter-head">
        <button
          type="button"
          className="epub-chapter-toggle"
          aria-expanded={open}
          aria-label={`${open ? "收起" : "展开"}${label}`}
          onClick={() => setOpen((value) => !value)}
        >
          <span aria-hidden="true">{open ? "−" : "+"}</span>
        </button>
        <span className="chapter-edit-index" aria-hidden="true" />
        <span className="epub-matter-title">{label}</span>
        <span className="epub-section-count">{chapters.length} 项</span>
        <span className="epub-row-spacer" aria-hidden="true" />
      </div>
      {open && (
        <div className="epub-section-list">
          {nodes.map((node) => (
            <EpubChapterNode
              key={node.chapter.editorIndex}
              node={node}
              update={update}
              remove={remove}
            />
          ))}
        </div>
      )}
    </section>
  );
}

export function ChapterEditor({ book }: { book: Book }) {
  const isEpub = book.source_format === "epub";
  const [chapters, setChapters] = useState(() => (
    isEpub ? reconcileStoredStructuralRoles(book.chapters) : book.chapters
  ));
  const [message, setMessage] = useState("");
  const [messageKind, setMessageKind] = useState<"ok" | "error" | "info">("info");
  const [saving, setSaving] = useState(false);

  function warn(text: string) {
    setMessageKind("error");
    setMessage(text);
  }

  function update(index: number, patch: Partial<EditableChapter>) {
    setChapters((current) => {
      const original = current[index];
      if (!original) return current;
      const tree = buildEditableChapterGroups(current.map((chapter, editorIndex) => ({ ...chapter, editorIndex })));
      const directChildIndexes = new Set(
        findEpubChapterGroup(tree, index)?.children.map((child) => child.chapter.editorIndex),
      );
      const renamedParent = patch.title !== undefined;
      return current.map((chapter, itemIndex) => {
        if (itemIndex === index) return { ...chapter, ...patch };
        if (renamedParent && directChildIndexes.has(itemIndex)) {
          return { ...chapter, parent_title: patch.title };
        }
        return chapter;
      });
    });
  }

  function split(index: number) {
    const chapter = chapters[index];
    if (chapter.source_start_page >= chapter.source_end_page) {
      warn("单页章节无法继续拆分。");
      return;
    }
    const splitPage = Math.floor((chapter.source_start_page + chapter.source_end_page) / 2);
    setChapters((current) => [
      ...current.slice(0, index),
      { ...chapter, title: `${chapter.title}（上）`, source_end_page: splitPage },
      {
        title: `${chapter.title}（下）`,
        source_start_page: splitPage + 1,
        source_end_page: chapter.source_end_page,
      },
      ...current.slice(index + 1),
    ]);
    setMessage("");
  }

  function mergeNext(index: number) {
    if (index >= chapters.length - 1) return;
    const current = chapters[index];
    const next = chapters[index + 1];
    setChapters((items) => [
      ...items.slice(0, index),
      { ...current, title: `${current.title} / ${next.title}`, source_end_page: next.source_end_page },
      ...items.slice(index + 2),
    ]);
  }

  function remove(index: number) {
    const tree = buildEditableChapterGroups(chapters.map((chapter, editorIndex) => ({ ...chapter, editorIndex })));
    const target = findEpubChapterGroup(tree, index);
    if (!target) return;
    const removedIndexes = new Set(flattenEpubChapterGroups([target]).map((chapter) => chapter.editorIndex));
    const remainingCount = chapters.filter((_chapter, itemIndex) => !removedIndexes.has(itemIndex)).length;
    if (remainingCount === 0) {
      warn("至少需要保留一个章节。");
      return;
    }
    setChapters((current) => current.filter((_chapter, itemIndex) => !removedIndexes.has(itemIndex)));
  }

  function addChapter() {
    const last = chapters.at(-1);
    const page = last?.source_end_page ?? 1;
    setChapters((current) => [
      ...current,
      {
        title: "新章节",
        source_start_page: page,
        source_end_page: page,
        depth: 0,
        parent_title: null,
        nav_kind: "plain",
        in_body: true,
        structural_role: "unknown",
        role_source: "manual",
        role_confidence: "low",
      },
    ]);
  }

  async function confirm() {
    const invalid = chapters.some((chapter) => (
      !chapter.title.trim()
      || chapter.source_start_page < 1
      || chapter.source_end_page < chapter.source_start_page
    ));
    if (invalid) {
      warn("请检查章节标题和页码范围。");
      return;
    }
    setSaving(true);
    setMessageKind("info");
    setMessage("正在保存章节…");
    try {
      await apiJson(`/books/${book.id}/chapters`, {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          chapters: chapters.map((chapter) => ({
            title: chapter.title.trim(),
            source_start_page: chapter.source_start_page,
            source_end_page: chapter.source_end_page,
            depth: chapter.depth ?? 0,
            parent_title: chapter.parent_title?.trim() || null,
            nav_kind: chapter.nav_kind ?? "plain",
            in_body: chapter.in_body ?? true,
            structural_role: chapter.structural_role ?? "unknown",
            role_source: chapter.role_source ?? "unknown",
            role_confidence: chapter.role_confidence ?? "low",
            analysis_role: chapter.analysis_role ?? "analysis_unit",
          })),
        }),
      });
      window.location.assign(`/books/${book.id}/overview`);
    } catch (error) {
      warn(error instanceof Error ? error.message : "无法连接本机 API。");
      setSaving(false);
    }
  }

  const epubTree = isEpub
    ? buildEditableChapterGroups(chapters.map((chapter, editorIndex) => ({ ...chapter, editorIndex })))
    : [];
  const frontMatter = epubTree.filter((node) => node.chapter.structural_role === "front_matter");
  const backMatter = epubTree.filter((node) => node.chapter.structural_role === "back_matter");
  const mainMatter = epubTree.filter((node) => (
    node.chapter.structural_role !== "front_matter"
    && node.chapter.structural_role !== "back_matter"
  ));
  const editorDescription = isEpub ? "核对目录层级与章节标题。" : "核对标题与原书页码。";

  return (
    <main className="chapter-editor-page">
      <header className="editor-header">
        <Link href="/" className="back-link">← 返回导入</Link>
        <span className="eyebrow">解析完成</span>
        <h1>确认章节结构</h1>
        <p>{editorDescription}确认后，系统会按章节生成可回查的阅读分析。</p>
      </header>
      <section className="editor-card">
        <div className="editor-book-name">
          {[book.title?.trim(), book.subtitle?.trim()].filter(Boolean).join("：") || book.filename}
        </div>
        {isEpub ? (
          <div className="epub-outline" aria-label="章节目录">
            {frontMatter.length > 0 && (
              <EpubMatterGroup label="前置内容" nodes={frontMatter} update={update} remove={remove} />
            )}
            {mainMatter.map((node) => (
              <EpubChapterNode
                key={node.chapter.editorIndex}
                node={node}
                update={update}
                remove={remove}
              />
            ))}
            {backMatter.length > 0 && (
              <EpubMatterGroup label="后置内容" nodes={backMatter} update={update} remove={remove} />
            )}
          </div>
        ) : (
          <div className="chapter-edit-list">
            {chapters.map((chapter, index) => (
              <article className="chapter-edit-row" key={`${index}-${chapter.source_start_page}`}>
                <span className="chapter-edit-index">{String(index + 1).padStart(2, "0")}</span>
                <label className="title-field">
                  <span>章节标题</span>
                  <input value={chapter.title} onChange={(event) => update(index, { title: event.target.value })} />
                </label>
                <label className="page-field">
                  <span>起始页</span>
                  <input type="number" min="1" value={chapter.source_start_page} onChange={(event) => update(index, { source_start_page: Number(event.target.value) })} />
                </label>
                <label className="page-field">
                  <span>结束页</span>
                  <input type="number" min="1" value={chapter.source_end_page} onChange={(event) => update(index, { source_end_page: Number(event.target.value) })} />
                </label>
                <div className="row-actions">
                  <button type="button" onClick={() => split(index)}>拆分</button>
                  <button type="button" disabled={index === chapters.length - 1} onClick={() => mergeNext(index)}>合并下一章</button>
                  <button type="button" className="danger-action" onClick={() => remove(index)}>删除</button>
                </div>
              </article>
            ))}
          </div>
        )}
        <button type="button" className="add-chapter" onClick={addChapter}>＋ 添加章节</button>
        <footer className="editor-footer">
          <p className={`form-message form-message-${messageKind}`} aria-live="polite">{message}</p>
          <button className="primary-button" type="button" disabled={saving} onClick={confirm}>
            {saving ? "正在保存…" : "确认并生成章节导读"}
          </button>
        </footer>
      </section>
    </main>
  );
}

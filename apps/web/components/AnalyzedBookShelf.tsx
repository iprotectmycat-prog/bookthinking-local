"use client";

/* eslint-disable @next/next/no-img-element -- The API already resizes covers; native images preserve each book's intrinsic aspect ratio. */

import Link from "next/link";
import { ArrowRight, CaretDown, CaretUp, Plus } from "@phosphor-icons/react";
import { useEffect, useId, useRef, useState, useSyncExternalStore, type KeyboardEvent } from "react";

import { apiJson } from "../lib/api";
import { getBookDisplay } from "../lib/book-display";
import type { AnalyzedBook } from "../lib/types";
import { BookImport } from "./BookImport";
import styles from "../app/home.module.css";

type Library = { books: AnalyzedBook[]; status: "loading" | "ready" | "failed" };
type Shelf = "mine" | "public";

function subscribeToViewport(callback: () => void) {
  window.addEventListener("resize", callback);
  return () => window.removeEventListener("resize", callback);
}
const viewportWidth = () => window.innerWidth;
const serverWidth = () => 1280;

// Navigation memory stays in this browser tab and contains no book content.
function recallShelf(key: string) {
  try { return sessionStorage.getItem(`bookthinking:home:${key}`); } catch { return null; }
}
function rememberShelf(key: string, value: string) {
  try { sessionStorage.setItem(`bookthinking:home:${key}`, value); } catch { /* Storage may be unavailable. Browsing still works. */ }
}

function useLibrary(path: string, enabled = true) {
  const [library, setLibrary] = useState<Library>({ books: [], status: "loading" });
  const [attempt, setAttempt] = useState(0);
  useEffect(() => {
    if (!enabled) return;
    let active = true;
    apiJson<AnalyzedBook[]>(path)
      .then((books) => { if (active) setLibrary({ books, status: "ready" }); })
      .catch(() => { if (active) setLibrary({ books: [], status: "failed" }); });
    return () => { active = false; };
  }, [path, enabled, attempt]);
  function retry() {
    setLibrary({ books: [], status: "loading" });
    setAttempt((value) => value + 1);
  }
  return { ...library, retry };
}

export function AnalyzedBookShelf({ showPublicShelf = false, publicOnly = false }: {
  showPublicShelf?: boolean;
  publicOnly?: boolean;
}) {
  return publicOnly ? <CuratedShelf /> : <PersonalShelf showPublicShelf={showPublicShelf} />;
}

function CuratedShelf() {
  const library = useLibrary("/library/public");
  return (
    <div className={styles.library}>
      <PublicShelfNavigation activeShelf="public" count={library.status === "ready" ? library.books.length : undefined} />
      <ShelfContent library={library} title="精选书架" shelfKey="public" active isPrivate={false} />
    </div>
  );
}

export function PublicShelfNavigation({ activeShelf, count }: { activeShelf: Shelf; count?: number }) {
  return (
    <div className={styles.toolbar}>
      <nav className={styles.tabs} aria-label="选择书架">
        <Link className={styles.tab} href="/my-shelf" aria-current={activeShelf === "mine" ? "page" : undefined}>我的书架</Link>
        <Link className={styles.tab} href="/" aria-current={activeShelf === "public" ? "page" : undefined}>
          精选书架 <span className={styles.count}>{count}</span>
        </Link>
      </nav>
      <Link className={styles.importButton} href="/my-shelf">
        <Plus size={15} aria-hidden="true" />导入书籍
      </Link>
    </div>
  );
}

function PersonalShelf({ showPublicShelf }: { showPublicShelf: boolean }) {
  const mine = useLibrary("/library/analyzed");
  const curated = useLibrary("/library/public", showPublicShelf);
  const [selected, setSelected] = useState<Shelf>("mine");
  useEffect(() => {
    if (showPublicShelf && recallShelf("active") === "public") {
      // eslint-disable-next-line react-hooks/set-state-in-effect -- Restore tab-local navigation after hydration; SSR always starts on the private shelf.
      setSelected("public");
    }
  }, [showPublicShelf]);
  function selectShelf(key: Shelf) {
    if (key === selected) return;
    rememberShelf(`scrollY:${selected}`, String(window.scrollY));
    setSelected(key);
    rememberShelf("active", key);
  }
  const id = useId();
  const tabRefs = useRef<Partial<Record<Shelf, HTMLButtonElement | null>>>({});
  const shelves: { key: Shelf; title: string; library: typeof mine }[] = [
    { key: "mine", title: "我的书架", library: mine },
    ...(showPublicShelf ? [{ key: "public" as const, title: "精选书架", library: curated }] : []),
  ];

  function navigateTabs(event: KeyboardEvent<HTMLButtonElement>, index: number) {
    let next: number;
    if (event.key === "ArrowRight") next = (index + 1) % shelves.length;
    else if (event.key === "ArrowLeft") next = (index + shelves.length - 1) % shelves.length;
    else if (event.key === "Home") next = 0;
    else if (event.key === "End") next = shelves.length - 1;
    else return;
    event.preventDefault();
    const key = shelves[next].key;
    selectShelf(key);
    tabRefs.current[key]?.focus();
  }

  return (
    <div className={styles.library}>
      <div className={styles.toolbar}>
        <div className={styles.tabs} role="tablist" aria-label="选择书架">
          {shelves.map(({ key, title, library }, index) => (
            <button
              key={key}
              ref={(element) => { tabRefs.current[key] = element; }}
              id={`${id}-${key}-tab`}
              type="button"
              role="tab"
              aria-selected={selected === key}
              aria-controls={`${id}-${key}-panel`}
              tabIndex={selected === key ? 0 : -1}
              className={styles.tab}
              onClick={() => selectShelf(key)}
              onKeyDown={(event) => navigateTabs(event, index)}
            >
              {title}{" "}
              <span className={styles.count}>{library.status === "ready" ? library.books.length : null}</span>
            </button>
          ))}
        </div>
        <BookImport buttonClassName={styles.importButton} label={<><Plus size={15} aria-hidden="true" />导入书籍</>} />
      </div>
      {shelves.map(({ key, title, library }) => (
        <div key={key} id={`${id}-${key}-panel`} role="tabpanel" aria-labelledby={`${id}-${key}-tab`} hidden={selected !== key}>
          <ShelfContent library={library} title={title} shelfKey={key} active={selected === key} isPrivate={key === "mine"} />
        </div>
      ))}
    </div>
  );
}

function ShelfContent({ library, title, shelfKey, active, isPrivate }: {
  library: Library & { retry: () => void }; title: string; shelfKey: Shelf; active: boolean; isPrivate: boolean;
}) {
  const width = useSyncExternalStore(subscribeToViewport, viewportWidth, serverWidth);
  // Keep these breakpoints aligned with the grid in home.module.css.
  const columns = width <= 760 ? 2 : width <= 1179 ? 4 : 5;
  const [expanded, setExpanded] = useState(() => recallShelf(`expanded:${shelfKey}`) === "1");
  const touchStart = useRef<{ x: number; y: number; expanded: boolean } | null>(null);
  const ignoreClickUntil = useRef(0);
  const listId = useId();
  const hasMore = library.books.length > columns;

  function collapse() {
    setExpanded(false);
    rememberShelf(`expanded:${shelfKey}`, "0");
  }

  useEffect(() => {
    if (!active || !expanded) return;
    function onKeyDown(event: globalThis.KeyboardEvent) {
      if (event.key !== "Escape") return;
      setExpanded(false);
      rememberShelf(`expanded:${shelfKey}`, "0");
    }
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [active, expanded, shelfKey]);

  useEffect(() => {
    if (!active || library.status !== "ready") return;
    // Restore after the grid is present, when the page has its full height.
    // A separate key avoids interpreting the old horizontal offset as a page position.
    const saved = Number(recallShelf(`scrollY:${shelfKey}`));
    window.scrollTo({ top: Number.isFinite(saved) && saved > 0 ? saved : 0, behavior: "instant" });
  }, [active, library.status, shelfKey]);

  if (library.status === "loading") return (
    <div className={styles.loading} role="status" aria-label={`${title}正在加载`}>
      <span className={styles.srOnly}>正在加载书架…</span>
      <div className={styles.skeletons} aria-hidden="true">{Array.from({ length: 5 }, (_, i) => <div className={styles.skeleton} key={i} />)}</div>
    </div>
  );
  if (library.status === "failed") return (
    <div className={styles.empty} role="alert">
      <p>书架暂时无法加载，请稍后重试。</p>
      <button className={styles.textButton} type="button" onClick={library.retry}>重试<ArrowRight size={16} aria-hidden="true" /></button>
    </div>
  );
  if (!library.books.length) return (
    <div className={styles.empty}>
      <p>{isPrivate ? "书架还空着，先放一本喜欢的书。" : "精选书籍正在整理中。"}</p>
      {isPrivate && <span>支持 PDF 与 EPUB，导入后即可核对章节。</span>}
    </div>
  );

  return (
    <section
      aria-label={`${title}，${library.books.length} 本`}
      className={styles.shelf}
      data-shelf-mode={expanded ? "expanded" : "collapsed"}
      onWheel={(event) => {
        const distance = event.deltaY * (event.deltaMode === 1 ? 16 : event.deltaMode === 2 ? window.innerHeight : 1);
        if (hasMore && !expanded && distance > 24 && Math.abs(event.deltaY) > Math.abs(event.deltaX) * 1.25) setExpanded(true);
      }}
      onTouchStart={(event) => {
        const touch = event.touches[0];
        touchStart.current = event.touches.length === 1 ? { x: touch.clientX, y: touch.clientY, expanded: false } : null;
      }}
      onTouchMove={(event) => {
        const start = touchStart.current;
        if (!start || event.touches.length !== 1 || !hasMore || expanded) return;
        const touch = event.touches[0];
        const distance = touch.clientY - start.y;
        if (distance > 40 && distance > Math.abs(touch.clientX - start.x) * 1.25) {
          start.expanded = true;
          ignoreClickUntil.current = Date.now() + 350;
          setExpanded(true);
        }
      }}
      onTouchEnd={() => {
        if (touchStart.current?.expanded) ignoreClickUntil.current = Date.now() + 350;
        touchStart.current = null;
      }}
      onTouchCancel={() => { touchStart.current = null; }}
      onClickCapture={(event) => {
        if (Date.now() < ignoreClickUntil.current) {
          event.preventDefault();
          event.stopPropagation();
          return;
        }
        rememberShelf(`expanded:${shelfKey}`, expanded ? "1" : "0");
        rememberShelf(`scrollY:${shelfKey}`, String(window.scrollY));
      }}
    >
      <ul id={listId} className={styles.grid} aria-label="书籍列表">
        {library.books.slice(0, expanded ? undefined : columns).map((book, index) => <BookCoverLink book={book} eager={index < columns} key={book.id} />)}
      </ul>
      {hasMore && <div className={styles.shelfControls}>
        <button className={styles.shelfToggle} type="button" aria-label={expanded ? "收起书架" : "展开书架"} aria-expanded={expanded} aria-controls={listId} onClick={() => expanded ? collapse() : setExpanded(true)}>
          {expanded ? <><CaretUp size={16} aria-hidden="true" />收起书架</> : <><CaretDown size={16} aria-hidden="true" />向下滑动展开 · 全部 {library.books.length} 本</>}
        </button>
      </div>}
    </section>
  );
}

function BookCoverLink({ book, eager }: { book: AnalyzedBook; eager: boolean }) {
  const [imageFailed, setImageFailed] = useState(false);
  const fallback = getBookDisplay(book.filename, book.source_format);
  const title = book.title?.trim() || fallback.title;
  return (
    <li className={styles.book}>
      <Link href={`/books/${book.id}/overview`} aria-label={title} draggable={false} prefetch={false} className={styles.bookLink}>
        <span className={styles.coverFrame}>
          {imageFailed ? (
            <span className={styles.coverFallback} aria-hidden="true"><small>BookThinking</small><strong>{title}</strong><span>{book.authors?.trim() || book.source_format.toUpperCase()}</span></span>
          ) : (
            <img className={styles.cover} src={`/local/library/books/${book.id}/cover`} alt={`${title} 封面`} width={200} height={300} loading={eager ? "eager" : "lazy"} draggable={false} onError={() => setImageFailed(true)} />
          )}
        </span>
        <span className={styles.bookTitle}>{title}</span>
        <span className={styles.bookByline}><span>{book.authors?.trim()}</span><ArrowRight size={16} aria-hidden="true" /></span>
      </Link>
    </li>
  );
}

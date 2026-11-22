"use client";

import { useCallback, useEffect, useRef, useState, type KeyboardEvent as ReactKeyboardEvent, type WheelEvent as ReactWheelEvent } from "react";
import type Contents from "epubjs/types/contents";
import type { Rendition } from "epubjs";
import type { Location } from "epubjs/types/rendition";
import { ReactReader, ReactReaderStyle } from "react-reader";
import { epubDisplayTarget, epubInitialDisplayTarget, epubResolvedDisplayTarget } from "../lib/epub-locator";
import { findEpubQuoteRange } from "../lib/epub-quote-range";
import { loadReaderState, saveReaderPreferences, saveReaderProgress, type EpubReaderPreferences } from "../lib/epub-reader-storage";
import { useSystemColorScheme, type SystemColorScheme } from "../lib/use-system-color-scheme";
import type { EpubLocator } from "../lib/types";
import { EpubReaderToolbar } from "./EpubReaderToolbar";
import { EpubSourceChat } from "./EpubSourceChat";
import { EpubSelectionPanel } from "./EpubSelectionPanel";
import { loadEpubAnnotations, saveEpubAnnotation, type EpubPassage } from "../lib/epub-annotations";

type WheelNavigationEvent = Pick<WheelEvent, "deltaY" | "preventDefault" | "stopPropagation">;

type SelectionPanel = {
  passage: EpubPassage;
  mode: "menu" | "note" | "chat";
  anchor?: { left: number; top: number };
};

const passageMarks = {
  draft: { fill: "#7895be", opacity: "0.32" },
  note: { fill: "#e9ad53", opacity: "0.43" },
  chat: { fill: "#56aa94", opacity: "0.43" },
  both: { fill: "#56aa94", opacity: "0.43", stroke: "#e9ad53" },
};

type ActiveHighlight = {
  cfi: string;
  rendition: Rendition;
  timeoutId: number | undefined;
};

type CurrentLocation = {
  cfi: string | null;
  href: string | null;
  tocLabel: string | null;
  page: number | null;
  total: number | null;
};

function isEditableTarget(target: EventTarget | null) {
  if (!target || typeof target !== "object") return false;

  let element = target as Element & {
    isContentEditable?: boolean;
    parentElement?: Element | null;
  };
  while (element) {
    if (element.matches?.("input, textarea, select")) return true;

    if (typeof element.isContentEditable === "boolean") {
      return element.isContentEditable;
    }

    const contentEditable = element.getAttribute?.("contenteditable")?.trim().toLowerCase();
    if (contentEditable === "" || contentEditable === "true" || contentEditable === "plaintext-only") {
      return true;
    }
    if (contentEditable === "false") return false;

    element = element.parentElement as typeof element;
  }
  return false;
}

export async function locateEvidence(
  rendition: Rendition,
  locator: EpubLocator,
  quote: string,
  surroundingText: string | null,
  displayTarget = epubDisplayTarget(locator),
): Promise<string | null> {
  if (typeof displayTarget === "string") {
    await rendition.display(displayTarget);
  } else {
    await rendition.display(displayTarget);
  }
  const contents = rendition.getContents() as Contents | Contents[];
  const renderedContents = Array.isArray(contents) ? contents : [contents];
  const match = renderedContents
    .map((content: Contents) => ({
      content,
      range: findEpubQuoteRange(content.document, quote, surroundingText),
    }))
    .find((item: { content: Contents; range: Range | null }) => item.range);

  if (!match?.range) return null;

  const cfi = match.content.cfiFromRange(match.range);
  await rendition.display(cfi);
  return cfi;
}

const epubThemes = {
  "source-light": {
    html: { color: "#28251f", background: "#fffdf8 !important" },
    body: { color: "#28251f", background: "#fffdf8 !important" },
    a: { color: "#9b4e32" },
    ".source-evidence-highlight": { fill: "#e2a73b", "fill-opacity": "0.45" },
  },
  "source-dark": {
    html: { color: "#ede6d9", background: "#24211d !important" },
    body: { color: "#ede6d9", background: "#24211d !important" },
    a: { color: "#ffb08a" },
    ".source-evidence-highlight": { fill: "#e8b969", "fill-opacity": "0.52" },
  },
};

function applyEpubTheme(rendition: Rendition, colorScheme: SystemColorScheme) {
  rendition.themes.register("source-light", epubThemes["source-light"]);
  rendition.themes.register("source-dark", epubThemes["source-dark"]);
  rendition.themes.select(`source-${colorScheme}`);
}

function readerStylesFor(colorScheme: SystemColorScheme) {
  const isDark = colorScheme === "dark";
  const backgroundColor = isDark ? "#24211d" : "#fffdf8";
  const color = isDark ? "#ede6d9" : "#28251f";
  const mutedColor = isDark ? "#b4ada1" : "#746f65";

  return {
    ...ReactReaderStyle,
    container: { ...ReactReaderStyle.container, backgroundColor, color },
    readerArea: { ...ReactReaderStyle.readerArea, backgroundColor, color, boxShadow: `inset 0 1px 0 ${isDark ? "rgba(255,255,255,.035)" : "rgba(72,59,44,.06)"}` },
    reader: { ...ReactReaderStyle.reader, top: 40, left: 64, right: 64, bottom: 28 },
    titleArea: { ...ReactReaderStyle.titleArea, backgroundColor, color },
    tocBackground: { ...ReactReaderStyle.tocBackground, left: 280, backgroundColor: isDark ? "rgba(0,0,0,.34)" : "rgba(53,43,31,.16)" },
    tocArea: { ...ReactReaderStyle.tocArea, width: 280, backgroundColor, color, padding: "14px 0", borderRight: `1px solid ${isDark ? "#48433b" : "#ded7cc"}`, boxShadow: isDark ? "18px 0 34px rgba(0,0,0,.22)" : "18px 0 34px rgba(58,44,30,.12)" },
    toc: { ...ReactReaderStyle.toc, color: mutedColor },
    tocAreaButton: { ...ReactReaderStyle.tocAreaButton, color, padding: "11px 18px", borderBottom: `1px solid ${isDark ? "rgba(72,67,59,.68)" : "rgba(222,215,204,.8)"}`, fontSize: ".86em" },
    tocButton: { ...ReactReaderStyle.tocButton, top: 12, left: 14, width: 30, height: 30, borderRadius: 9, background: isDark ? "rgba(36,33,29,.78)" : "rgba(255,253,248,.78)", color, boxShadow: `0 1px 4px ${isDark ? "rgba(0,0,0,.22)" : "rgba(62,48,33,.12)"}` },
    tocButtonExpanded: { ...ReactReaderStyle.tocButtonExpanded, background: isDark ? "#302c26" : "#f0ebe2" },
    containerExpanded: { ...ReactReaderStyle.containerExpanded, transform: "translateX(280px)" },
    arrow: { ...ReactReaderStyle.arrow, color: mutedColor, fontSize: 36, marginTop: -22, padding: "6px 10px", opacity: 0.68, transition: "color .18s ease, opacity .18s ease" },
    arrowHover: { ...ReactReaderStyle.arrowHover, color, opacity: 1 },
  };
}

type EpubReaderProps = {
  bookId: string;
  data: ArrayBuffer;
  locator: EpubLocator;
  quote?: string | null;
  surroundingText?: string | null;
  highlightRequestId?: number;
  restoreProgress?: boolean;
  discussion?: { chapterSummary: string };
  onError: (message: string) => void;
};

export function EpubReader(props: EpubReaderProps) {
  const { bookId, locator, restoreProgress = false } = props;
  const locationKey = [
    bookId,
    restoreProgress,
    locator.href,
    locator.fragment,
    locator.cfi,
    locator.spineIndex,
  ].join(":");

  return <EpubReaderContent key={locationKey} {...props} />;
}

function EpubReaderContent({
  bookId,
  data,
  locator,
  quote = null,
  surroundingText = null,
  highlightRequestId = 0,
  restoreProgress = false,
  discussion,
  onError,
}: EpubReaderProps) {
  const colorScheme = useSystemColorScheme();
  const savedReaderState = loadReaderState(bookId);
  const hasExplicitLocator = locator.href !== null || locator.fragment !== null || locator.cfi !== null || locator.spineIndex !== null;
  const initialLocation = restoreProgress && !hasExplicitLocator
    ? savedReaderState.progressCfi ?? epubDisplayTarget(locator)
    : epubInitialDisplayTarget(locator);
  const [preferences, setPreferences] = useState<EpubReaderPreferences>(() => savedReaderState.preferences);
  const [location, setLocation] = useState<string | number | null>(initialLocation);
  const [currentLocation, setCurrentLocation] = useState<CurrentLocation>({ cfi: null, href: null, tocLabel: null, page: null, total: null });
  const [searchOpen, setSearchOpen] = useState(false);
  const [selectionPanel, setSelectionPanel] = useState<SelectionPanel>();
  const [annotations, setAnnotations] = useState(() => loadEpubAnnotations(bookId));
  const [annotationRendition, setAnnotationRendition] = useState<Rendition>();
  const readerRoot = useRef<HTMLDivElement>(null);
  const savedMarks = useRef(new Map<string, keyof typeof passageMarks>());
  const readerColorScheme = preferences.theme === "system" ? colorScheme : preferences.theme;
  const readerStyles = readerStylesFor(readerColorScheme);
  const renditionRef = useRef<Rendition | null>(null);
  const lastPageTurnAtRef = useRef<number | null>(null);
  const readerWindowsRef = useRef(new Set<Window>());
  const subscribedRenditionsRef = useRef(new WeakSet<Rendition>());
  const activeHighlightRef = useRef<ActiveHighlight | null>(null);
  const settledEvidenceRequestRef = useRef<number | null>(null);
  const highlightedRequestRef = useRef<number | null>(null);
  const highlightingRequestRef = useRef<number | null>(null);
  const resolvedDisplayTargetRef = useRef<string | number>(initialLocation);

  const captureSelection = useCallback((cfi: string, contents: Contents) => {
    const selection = contents.range(cfi);
    const quote = selection?.toString().trim();
    if (!quote) return;

    const context = contents.document.createRange();
    context.selectNodeContents(contents.document.body);
    context.setEnd(selection.startContainer, selection.startOffset);
    const before = context.toString().trimEnd().slice(-600);
    context.selectNodeContents(contents.document.body);
    context.setStart(selection.endContainer, selection.endOffset);
    const after = context.toString().trimStart().slice(0, 600);
    const frame = contents.document.defaultView?.frameElement;
    const root = readerRoot.current?.getBoundingClientRect();
    const frameRect = frame?.getBoundingClientRect();
    const rect = selection.getBoundingClientRect?.();
    const anchor = root && frameRect && rect ? {
      left: Math.max(8, Math.min(frameRect.left + rect.left - root.left, root.width - 260)),
      top: Math.max(8, Math.min(frameRect.top + rect.bottom - root.top + 8, root.height - 62)),
    } : undefined;
    const passage = { cfi, quote: quote.slice(0, 2000), before, after };
    setSelectionPanel((current) => current?.passage.cfi === cfi && current.mode !== "menu"
      ? current
      : { passage, mode: "menu", anchor });
  }, []);

  const clearActiveHighlight = useCallback(() => {
    const activeHighlight = activeHighlightRef.current;
    if (!activeHighlight) {
      return;
    }

    window.clearTimeout(activeHighlight.timeoutId);
    activeHighlight.rendition.annotations.remove(activeHighlight.cfi, "highlight");
    activeHighlightRef.current = null;
  }, []);

  const highlightEvidenceQuote = useCallback(async () => {
    const rendition = renditionRef.current;
    if (!rendition || !quote || settledEvidenceRequestRef.current === highlightRequestId) {
      return;
    }
    if (highlightingRequestRef.current === highlightRequestId) {
      return;
    }

    highlightingRequestRef.current = highlightRequestId;
    try {
      const cfi = await locateEvidence(
        rendition,
        locator,
        quote,
        surroundingText,
        resolvedDisplayTargetRef.current,
      );
      if (highlightingRequestRef.current !== highlightRequestId) {
        return;
      }
      settledEvidenceRequestRef.current = highlightRequestId;
      if (!cfi) return;
      if (savedMarks.current.has(cfi)) return;
      highlightedRequestRef.current = highlightRequestId;
      rendition.annotations.highlight(cfi, {}, undefined, "source-evidence-highlight");
      const timeoutId = window.setTimeout(() => {
        rendition.annotations.remove(cfi, "highlight");
        if (activeHighlightRef.current?.cfi === cfi) {
          activeHighlightRef.current = null;
        }
      }, 2_800);
      activeHighlightRef.current = { cfi, rendition, timeoutId };
    } finally {
      if (highlightingRequestRef.current === highlightRequestId) {
        highlightingRequestRef.current = null;
      }
    }
  }, [highlightRequestId, locator, quote, surroundingText]);

  useEffect(() => {
    const rendition = annotationRendition;
    if (!discussion || !rendition) return;
    const marks = new Map<string, keyof typeof passageMarks>();
    for (const [cfi, annotation] of Object.entries(annotations)) {
      if (annotation.note) marks.set(cfi, annotation.turns?.length ? "both" : "note");
      else if (annotation.turns?.length) marks.set(cfi, "chat");
    }
    const activeCfi = selectionPanel?.passage.cfi;
    if (activeCfi && selectionPanel?.mode !== "menu" && !marks.has(activeCfi)) marks.set(activeCfi, "draft");

    for (const [cfi, kind] of savedMarks.current) {
      if (marks.get(cfi) !== kind) rendition.annotations.remove(cfi, "highlight");
    }
    for (const [cfi, kind] of marks) {
      if (savedMarks.current.get(cfi) === kind) continue;
      if (activeHighlightRef.current?.cfi === cfi) clearActiveHighlight();
      const style = passageMarks[kind];
      const annotation = annotations[cfi];
      rendition.annotations.highlight(cfi, {}, annotation ? (event?: MouseEvent) => {
        if (event?.type === "touchstart") return;
        setSelectionPanel({ passage: annotation.passage, mode: kind === "both" ? "menu" : kind === "note" ? "note" : "chat" });
      } : undefined, `source-${kind}-highlight`, {
        fill: style.fill,
        "fill-opacity": style.opacity,
        "mix-blend-mode": "normal",
        ...("stroke" in style ? { stroke: style.stroke, "stroke-opacity": "0.85" } : {}),
      });
    }
    savedMarks.current = marks;
  }, [annotationRendition, annotations, clearActiveHighlight, discussion, selectionPanel]);

  useEffect(() => {
    clearActiveHighlight();
    void highlightEvidenceQuote();

    return () => {
      highlightedRequestRef.current = null;
      highlightingRequestRef.current = null;
      clearActiveHighlight();
    };
  }, [clearActiveHighlight, highlightEvidenceQuote, highlightRequestId]);

  useEffect(() => {
    if (renditionRef.current) {
      applyEpubTheme(renditionRef.current, readerColorScheme);
      renditionRef.current.themes.fontSize(`${preferences.fontScale}%`);
      renditionRef.current.themes.override("line-height", String(preferences.lineHeight), true);
      renditionRef.current.themes.override("padding-left", `${preferences.pageMargin}px`, true);
      renditionRef.current.themes.override("padding-right", `${preferences.pageMargin}px`, true);
    }
  }, [preferences.fontScale, preferences.lineHeight, preferences.pageMargin, readerColorScheme]);

  const previous = useCallback(() => {
    void renditionRef.current?.prev();
  }, []);

  const next = useCallback(() => {
    void renditionRef.current?.next();
  }, []);

  const turnPageWithWheel = useCallback((event: WheelNavigationEvent) => {
    if (!renditionRef.current || event.deltaY === 0) {
      return;
    }

    event.preventDefault();
    event.stopPropagation();

    const now = Date.now();
    if (lastPageTurnAtRef.current !== null && now - lastPageTurnAtRef.current < 420) {
      return;
    }

    lastPageTurnAtRef.current = now;
    if (event.deltaY > 0) next();
    else previous();
  }, [next, previous]);

  const turnPageWithKeyboard = useCallback((event: KeyboardEvent | ReactKeyboardEvent<HTMLDivElement>) => {
    if (isEditableTarget(event.target)) return;
    if (event.key === "ArrowLeft") {
      event.preventDefault();
      previous();
    } else if (event.key === "ArrowRight") {
      event.preventDefault();
      next();
    }
  }, [next, previous]);

  const attachContentWheelListeners = useCallback((contents: Contents | Contents[]) => {
    const renderedContents = Array.isArray(contents) ? contents : [contents];

    for (const content of renderedContents) {
      if (!content?.window || readerWindowsRef.current.has(content.window)) {
        continue;
      }
      content.window.addEventListener("wheel", turnPageWithWheel, { passive: false });
      content.window.addEventListener("keydown", turnPageWithKeyboard);
      readerWindowsRef.current.add(content.window);
    }
  }, [turnPageWithKeyboard, turnPageWithWheel]);

  const attachRenderedContentWheelListeners = useCallback((rendition: Rendition) => {
    attachContentWheelListeners(rendition.getContents());
  }, [attachContentWheelListeners]);

  useEffect(() => () => {
    clearActiveHighlight();
    for (const readerWindow of readerWindowsRef.current) {
      readerWindow.removeEventListener("wheel", turnPageWithWheel);
      readerWindow.removeEventListener("keydown", turnPageWithKeyboard);
    }
    readerWindowsRef.current.clear();
  }, [clearActiveHighlight, turnPageWithKeyboard, turnPageWithWheel]);

  const updatePreferences = useCallback((nextPreferences: EpubReaderPreferences) => {
    saveReaderPreferences(bookId, nextPreferences);
    setPreferences(nextPreferences);
  }, [bookId]);

  const epubOptions = preferences.flow === "scrolled"
    ? { manager: "continuous", flow: "scrolled" }
    : { manager: "default", flow: "paginated" };

  function closeSelectionPanel() {
    setSelectionPanel(undefined);
    readerRoot.current?.focus({ preventScroll: true });
  }

  return (
    <div
      ref={readerRoot}
      className="source-reader source-reader-epub"
      aria-label="原书 EPUB 阅读器"
      tabIndex={0}
      onWheel={turnPageWithWheel as (event: ReactWheelEvent<HTMLDivElement>) => void}
      onKeyDown={turnPageWithKeyboard}
    >
      <EpubReaderToolbar
        preferences={preferences}
        onPreferencesChange={updatePreferences}
        onPrevious={previous}
        onNext={next}
        onOpenSearch={() => setSearchOpen(true)}
        activeTocLabel={currentLocation.tocLabel}
        page={currentLocation.page}
        total={currentLocation.total}
      />
      {searchOpen && <p className="epub-reader-search-note" role="status">原书搜索将在后续版本提供。</p>}
      <ReactReader
        key={preferences.flow}
        url={data}
        location={location}
        locationChanged={setLocation}
        epubOptions={epubOptions}
        showToc
        readerStyles={readerStyles}
        loadingView={<p role="status">正在解析 EPUB…</p>}
        errorView={<p role="alert">原书 EPUB 无法加载</p>}
        getRendition={(rendition) => {
          if (renditionRef.current !== rendition && discussion) {
            savedMarks.current = new Map();
            setAnnotationRendition(rendition);
          }
          renditionRef.current = rendition;
          const spine = rendition.book?.spine;
          if (spine && location === initialLocation && (locator.href || locator.spineIndex !== null)) {
            const resolvedDisplayTarget = epubResolvedDisplayTarget(locator, spine);
            resolvedDisplayTargetRef.current = resolvedDisplayTarget;
            if (resolvedDisplayTarget !== initialLocation) {
              setLocation(resolvedDisplayTarget);
            }
          }
          applyEpubTheme(rendition, readerColorScheme);
          rendition.themes.fontSize(`${preferences.fontScale}%`);
          rendition.themes.override("line-height", String(preferences.lineHeight), true);
          rendition.themes.override("padding-left", `${preferences.pageMargin}px`, true);
          rendition.themes.override("padding-right", `${preferences.pageMargin}px`, true);
          attachRenderedContentWheelListeners(rendition);
          void highlightEvidenceQuote();
          if (!subscribedRenditionsRef.current.has(rendition)) {
            rendition.hooks.content.register(attachContentWheelListeners);
            if (discussion) {
              rendition.on("selected", captureSelection);
              rendition.on("mousedown", () => setSelectionPanel((current) => current?.mode === "menu" ? undefined : current));
            }
            rendition.on("rendered", () => {
              attachRenderedContentWheelListeners(rendition);
              void highlightEvidenceQuote();
            });
            subscribedRenditionsRef.current.add(rendition);
          }
          rendition.on("displayError", () => onError("原书 EPUB 无法加载"));
          rendition.on("relocated", (nextLocation: Location) => {
            const cfi = nextLocation.start.cfi;
            if (!cfi) return;
            setSelectionPanel((current) => current?.mode === "menu" ? undefined : current);
            saveReaderProgress(bookId, cfi);
            setLocation(cfi);
            setCurrentLocation({
              cfi,
              href: nextLocation.start.href ?? null,
              tocLabel: nextLocation.start.href ? rendition.book?.navigation.get(nextLocation.start.href)?.label ?? null : null,
              page: nextLocation.start.displayed?.page ?? null,
              total: nextLocation.start.displayed?.total ?? null,
            });
          });
        }}
      />
      {discussion && selectionPanel && (
        <EpubSelectionPanel
          key={selectionPanel.passage.cfi}
          mode={selectionPanel.mode}
          anchor={selectionPanel.anchor}
          note={annotations[selectionPanel.passage.cfi]?.note}
          onChoose={(mode) => setSelectionPanel({ ...selectionPanel, mode })}
          onClose={closeSelectionPanel}
          onSaveNote={(note) => {
            setAnnotations(saveEpubAnnotation(bookId, selectionPanel.passage, () => ({ note })));
            setSelectionPanel(undefined);
          }}
        >
          <EpubSourceChat
            bookId={bookId}
            onBack={() => setSelectionPanel({ ...selectionPanel, mode: "menu" })}
            onClose={closeSelectionPanel}
            passage={selectionPanel.passage}
            chapterSummary={discussion.chapterSummary}
            turns={annotations[selectionPanel.passage.cfi]?.turns ?? []}
            onSave={(turn) => setAnnotations(saveEpubAnnotation(bookId, selectionPanel.passage, (current) => ({
              turns: [...(current?.turns ?? []), turn],
            })))}
          />
        </EpubSelectionPanel>
      )}
    </div>
  );
}

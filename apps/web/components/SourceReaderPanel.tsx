"use client";

import { useEffect, useRef, useState, type PointerEvent as ReactPointerEvent } from "react";
import { sourceReaderPresentation } from "../lib/source-reader";
import type { SourceReaderTarget } from "../lib/types";
import { SourceReaderContent } from "./SourceReaderContent";

type SourceReaderPanelProps = {
  bookId: string;
  target: SourceReaderTarget | null;
  isOpen: boolean;
  discussion?: { chapterSummary: string };
  onClose: () => void;
};

export function SourceReaderPanel({
  bookId,
  target,
  isOpen,
  discussion,
  onClose,
}: SourceReaderPanelProps) {
  const [sourceWidth, setSourceWidth] = useState(560);
  const closeButton = useRef<HTMLButtonElement>(null);
  const location = target === null ? null : sourceReaderPresentation(target).location;

  useEffect(() => {
    if (isOpen) closeButton.current?.focus({ preventScroll: true });
  }, [isOpen]);

  function applySourceWidth(width: number) {
    const nextWidth = Math.min(900, Math.max(420, width));
    setSourceWidth(nextWidth);
    document.documentElement.style.setProperty("--workspace-source-width", `${nextWidth}px`);
  }

  function startResize(event: ReactPointerEvent<HTMLDivElement>) {
    event.preventDefault();
    const startX = event.clientX;
    const startWidth = sourceWidth;

    function resize(moveEvent: PointerEvent) {
      applySourceWidth(startWidth - (moveEvent.clientX - startX));
    }

    function stopResize() {
      window.removeEventListener("pointermove", resize);
      window.removeEventListener("pointerup", stopResize);
    }

    window.addEventListener("pointermove", resize);
    window.addEventListener("pointerup", stopResize);
  }

  if (!isOpen) return null;

  return (
    <section className="source-reader-panel">
      <div
        className="source-reader-resizer"
        role="separator"
        aria-label="调整原文栏宽度"
        aria-orientation="vertical"
        aria-valuemin={420}
        aria-valuemax={900}
        aria-valuenow={sourceWidth}
        tabIndex={0}
        onPointerDown={startResize}
      />
      {target !== null && (
        <aside className="source-reader-panel-content" aria-label="原书阅读器">
          <header className="source-reader-header">
            <div>
              <span>作者原文</span>
              <strong>{location}</strong>
            </div>
            <button ref={closeButton} type="button" aria-label="收起原书阅读器" onClick={onClose}>
              ×
            </button>
          </header>
          <SourceReaderContent
            bookId={bookId}
            target={target}
            discussion={discussion}
          />
        </aside>
      )}
    </section>
  );
}

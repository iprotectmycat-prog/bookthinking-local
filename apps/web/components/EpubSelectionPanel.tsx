"use client";

import { useEffect, useRef, useState, type ReactNode } from "react";
import { ArrowLeft, ChatText, Sparkle, X } from "@phosphor-icons/react";

export function EpubSelectionPanel({ mode, anchor, note, onChoose, onClose, onSaveNote, children }: {
  mode: "menu" | "note" | "chat";
  anchor?: { left: number; top: number };
  note?: string;
  onChoose: (mode: "menu" | "note" | "chat") => void;
  onClose: () => void;
  onSaveNote: (note: string) => void;
  children: ReactNode;
}) {
  const [draft, setDraft] = useState(note ?? "");
  const [error, setError] = useState("");
  const panel = useRef<HTMLElement>(null);

  useEffect(() => {
    const target = panel.current?.querySelector<HTMLElement>(mode === "menu" ? "button" : "textarea");
    target?.focus({ preventScroll: true });
  }, [mode]);

  return (
    <section
      ref={panel}
      className={mode === "menu" ? "epub-source-chat epub-selection-menu" : "epub-source-chat"}
      style={mode === "menu" ? anchor : undefined}
      role={mode === "menu" ? "toolbar" : "dialog"}
      aria-label={mode === "menu" ? "选区操作" : mode === "note" ? "原文备注" : "原文问答"}
      onWheel={(event) => event.stopPropagation()}
      onKeyDown={(event) => {
        event.stopPropagation();
        if (event.key === "Escape") {
          event.preventDefault();
          onClose();
        }
      }}
    >
      {mode === "menu" ? (
        <>
          <button type="button" onClick={() => { setDraft(note ?? ""); onChoose("note"); }}>
            <ChatText size={18} aria-hidden="true" />评论或备注
          </button>
          <span className="epub-menu-divider" aria-hidden="true" />
          <button type="button" className="epub-ask-action" onClick={() => onChoose("chat")}>
            <Sparkle size={18} aria-hidden="true" />问 AI
          </button>
        </>
      ) : (
        <>
          {mode === "chat" ? children : (
            <>
              <EpubSelectionHeading title="评论或备注" onBack={() => onChoose("menu")} onClose={onClose} />
              <form className="epub-note-form" onSubmit={(event) => {
                event.preventDefault();
                if (!draft.trim()) return;
                try {
                  onSaveNote(draft.trim());
                } catch {
                  setError("备注未能保存，请检查浏览器存储后重试。");
                }
              }}>
                <textarea
                  aria-label="评论或备注"
                  placeholder="写下你对这段的想法…"
                  rows={4}
                  maxLength={4000}
                  value={draft}
                  onChange={(event) => setDraft(event.target.value)}
                  onKeyDown={(event) => {
                    if (event.key === "Enter" && (event.metaKey || event.ctrlKey) && !event.nativeEvent.isComposing) {
                      event.preventDefault();
                      event.currentTarget.form?.requestSubmit();
                    }
                  }}
                />
                <div className="epub-note-footer">
                  <span>保存后可点击原文高亮回看</span>
                  <button className="epub-primary-button" type="submit" disabled={!draft.trim()}>保存</button>
                </div>
              </form>
            </>
          )}
          {error && <p className="epub-chat-error" role="alert">{error}</p>}
        </>
      )}
    </section>
  );
}

export function EpubSelectionHeading({ title, onBack, onClose, children }: {
  title: string;
  onBack: () => void;
  onClose: () => void;
  children?: ReactNode;
}) {
  return (
    <div className="epub-source-chat-heading">
      <button className="epub-icon-button" type="button" aria-label="返回选区操作" title="返回选区操作" onClick={onBack}>
        <ArrowLeft size={18} aria-hidden="true" />
      </button>
      <strong>{title}</strong>
      {children}
      <button className="epub-icon-button epub-panel-close" type="button" aria-label="收起" title="收起 · Esc" onClick={onClose}>
        <X size={18} aria-hidden="true" />
      </button>
    </div>
  );
}

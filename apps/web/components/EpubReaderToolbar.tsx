"use client";

import { useState } from "react";
import type { EpubReaderPreferences } from "../lib/epub-reader-storage";

export function EpubReaderToolbar({
  preferences,
  onPreferencesChange,
  onPrevious,
  onNext,
  onOpenSearch,
  activeTocLabel,
  page,
  total,
}: {
  preferences: EpubReaderPreferences;
  onPreferencesChange: (preferences: EpubReaderPreferences) => void;
  onPrevious: () => void;
  onNext: () => void;
  onOpenSearch: () => void;
  activeTocLabel: string | null;
  page: number | null;
  total: number | null;
}) {
  const [settingsOpen, setSettingsOpen] = useState(false);
  const change = (updates: Partial<EpubReaderPreferences>) => {
    onPreferencesChange({ ...preferences, ...updates });
  };
  const fontScales = [80, 90, 100, 110, 120, 130, 140] as const;
  const lineHeights = [1.4, 1.55, 1.7, 1.85, 2] as const;
  const nextValue = <T,>(values: readonly T[], current: T, direction: -1 | 1) => {
    const index = values.indexOf(current);
    return values[Math.max(0, Math.min(values.length - 1, index + direction))];
  };

  return (
    <div className="epub-reader-toolbar-shell">
      <div className="epub-reader-toolbar" aria-label="EPUB 阅读控制">
        <div className="epub-reader-toolbar__group epub-reader-toolbar__navigation">
          <button type="button" aria-label="上一页" onClick={onPrevious}>上一页</button>
          <button type="button" aria-label="下一页" onClick={onNext}>下一页</button>
        </div>
        <div className="epub-reader-toolbar__group epub-reader-toolbar__flow" aria-label="阅读模式">
          <button
            type="button"
            aria-label="分页阅读"
            aria-pressed={preferences.flow === "paginated"}
            onClick={() => change({ flow: "paginated" })}
          >分页</button>
          <button
            type="button"
            aria-label="连续滚动"
            aria-pressed={preferences.flow === "scrolled"}
            onClick={() => change({ flow: "scrolled" })}
          >滚动</button>
        </div>
        <div className="epub-reader-toolbar__location" aria-live="polite">
          {activeTocLabel && <span className="epub-reader-toolbar__chapter">{activeTocLabel}</span>}
          {page !== null && total !== null && <span>第 {page} / {total} 页</span>}
        </div>
        <div className="epub-reader-toolbar__actions">
          <button
            type="button"
            className="epub-reader-toolbar__settings-trigger"
            aria-label="阅读设置"
            aria-expanded={settingsOpen}
            onClick={() => setSettingsOpen((open) => !open)}
          >Aa</button>
          <button type="button" className="epub-reader-toolbar__search" aria-label="搜索原书" onClick={onOpenSearch}>搜索</button>
        </div>
      </div>
      {settingsOpen && (
        <section className="epub-reader-settings" aria-label="EPUB 阅读设置">
          <div className="epub-reader-settings__item">
            <span>字体大小</span>
            <div className="epub-reader-settings__stepper">
              <button type="button" aria-label="减小字号" onClick={() => change({ fontScale: nextValue(fontScales, preferences.fontScale, -1) })} disabled={preferences.fontScale === fontScales[0]}>A−</button>
              <label>
                <select aria-label="字号" value={preferences.fontScale} onChange={(event) => change({ fontScale: Number(event.target.value) as EpubReaderPreferences["fontScale"] })}>
                  {fontScales.map((fontScale) => <option key={fontScale} value={fontScale}>{fontScale}%</option>)}
                </select>
              </label>
              <button type="button" aria-label="增大字号" onClick={() => change({ fontScale: nextValue(fontScales, preferences.fontScale, 1) })} disabled={preferences.fontScale === fontScales[fontScales.length - 1]}>A+</button>
            </div>
          </div>
          <div className="epub-reader-settings__item">
            <span>行距</span>
            <div className="epub-reader-settings__stepper">
              <button type="button" aria-label="减小行距" onClick={() => change({ lineHeight: nextValue(lineHeights, preferences.lineHeight, -1) })} disabled={preferences.lineHeight === lineHeights[0]}>−</button>
              <output>{preferences.lineHeight}</output>
              <button type="button" aria-label="增大行距" onClick={() => change({ lineHeight: nextValue(lineHeights, preferences.lineHeight, 1) })} disabled={preferences.lineHeight === lineHeights[lineHeights.length - 1]}>+</button>
            </div>
          </div>
          <label className="epub-reader-settings__item epub-reader-settings__theme">主题
            <select aria-label="阅读主题" value={preferences.theme} onChange={(event) => change({ theme: event.target.value as EpubReaderPreferences["theme"] })}>
              <option value="system">跟随系统</option>
              <option value="light">浅色</option>
              <option value="dark">深色</option>
            </select>
          </label>
        </section>
      )}
    </div>
  );
}

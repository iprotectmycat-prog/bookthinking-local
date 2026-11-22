"use client";

import { useState } from "react";

import { statusMessage } from "../lib/analysis-message";
import type { AnalysisStatus, ChapterOverview } from "../lib/types";

type ProgressTab = "ready" | "running" | "queued" | "issues";

const TABS: ProgressTab[] = ["ready", "running", "queued", "issues"];
const RETRYABLE_STATUSES = new Set<AnalysisStatus>(["failed", "insufficient_evidence", "stale"]);

const TAB_COPY: Record<ProgressTab, { label: string; empty: string }> = {
  ready: { label: "已可阅读", empty: "暂时还没有完成的章节。" },
  running: { label: "正在分析", empty: "当前没有正在调用模型的章节。" },
  queued: { label: "等待分析", empty: "没有等待处理的章节。" },
  issues: { label: "需要留意", empty: "目前没有需要留意的章节。" },
};

function tabForStatus(status: AnalysisStatus): ProgressTab | null {
  if (status === "ready" || status === "summary_only") return "ready";
  if (status === "generating") return "running";
  if (status === "pending" || status === "stale") return "queued";
  if (status === "failed" || status === "insufficient_evidence") return "issues";
  return null;
}

function statusNote(chapter: ChapterOverview, tab: ProgressTab): string {
  if (tab === "issues") return statusMessage(chapter.generation_status);
  if (tab === "queued") return chapter.generation_status === "stale" ? "章节划分已更新，等待重新分析。" : "将在当前任务完成后自动开始。";
  return chapter.generation_status === "summary_only" ? "仅作概述，不计入全书核心结论。" : "章节分析已完成，可以开始阅读。";
}

export function AnalysisProgressPanel({
  chapters,
  chapterCount,
  onRetry,
  retryingChapterId,
}: {
  chapters: ChapterOverview[];
  chapterCount: number;
  onRetry?: (chapterId: number) => void;
  retryingChapterId: number | null;
}) {
  const [activeTab, setActiveTab] = useState<ProgressTab>("ready");
  const groups = chapters.reduce<Record<ProgressTab, ChapterOverview[]>>((result, chapter) => {
    const tab = tabForStatus(chapter.generation_status);
    if (tab) result[tab].push(chapter);
    return result;
  }, { ready: [], running: [], queued: [], issues: [] });
  const readableCount = groups.ready.length;
  const trackedChapterCount = TABS.reduce((count, tab) => count + groups[tab].length, 0);
  const progressPercent = trackedChapterCount ? Math.round((readableCount / trackedChapterCount) * 100) : 0;
  const displayedChapters = groups[activeTab];

  function selectTab(tab: ProgressTab) {
    setActiveTab(tab);
    document.getElementById(`analysis-tab-${tab}`)?.focus();
  }

  function onTabKeyDown(event: React.KeyboardEvent<HTMLButtonElement>, tab: ProgressTab) {
    const currentIndex = TABS.indexOf(tab);
    const nextIndex = event.key === "ArrowRight" || event.key === "ArrowDown" ? (currentIndex + 1) % TABS.length
      : event.key === "ArrowLeft" || event.key === "ArrowUp" ? (currentIndex - 1 + TABS.length) % TABS.length
        : event.key === "Home" ? 0 : event.key === "End" ? TABS.length - 1 : null;
    if (nextIndex === null) return;
    event.preventDefault();
    selectTab(TABS[nextIndex]);
  }

  return (
    <section className="analysis-progress-panel" aria-labelledby="analysis-progress-title">
      <h2 id="analysis-progress-title">正在分析中</h2>
      <div
        className="book-analysis-progressbar"
        role="progressbar"
        aria-label="全书分析进度"
        aria-valuemin={0}
        aria-valuemax={100}
        aria-valuenow={progressPercent}
      >
        <span style={{ width: `${progressPercent}%` }} />
      </div>
      <div className="analysis-progress-measure"><strong>{progressPercent}% · {readableCount} / {trackedChapterCount || chapterCount} 章已完成</strong></div>
      <div className="analysis-status-tabs" role="tablist" aria-label="章节分析状态">
        {TABS.map((tab) => (
          <button
            key={tab}
            id={`analysis-tab-${tab}`}
            className={`analysis-status-tab is-${tab}${activeTab === tab ? " is-active" : ""}`}
            type="button"
            role="tab"
            aria-selected={activeTab === tab}
            aria-controls={`analysis-panel-${tab}`}
            tabIndex={activeTab === tab ? 0 : -1}
            onClick={() => setActiveTab(tab)}
            onKeyDown={(event) => onTabKeyDown(event, tab)}
          >
            <strong>{groups[tab].length}</strong>
            <span>{TAB_COPY[tab].label}</span>
          </button>
        ))}
      </div>
      <section id={`analysis-panel-${activeTab}`} className="analysis-status-list" role="tabpanel" aria-labelledby={`analysis-tab-${activeTab}`} aria-label={TAB_COPY[activeTab].label}>
        <div className="analysis-list-heading"><h3>{TAB_COPY[activeTab].label}</h3><span>{activeTab === "issues" ? "不影响其他章节继续分析" : ""}</span></div>
        {displayedChapters.length === 0 ? <p className="analysis-list-empty">{TAB_COPY[activeTab].empty}</p> : (
          <ol>
            {displayedChapters.map((chapter) => (
              <li key={chapter.id} className={`analysis-list-row is-${activeTab}`}>
                <span aria-hidden="true" className="analysis-list-marker" />
                <div>
                  <strong>{chapter.title}</strong>{activeTab !== "running" && <p>{statusNote(chapter, activeTab)}</p>}
                  {activeTab === "issues" && onRetry && RETRYABLE_STATUSES.has(chapter.generation_status) && <button className="secondary-button analysis-retry-button" type="button" disabled={retryingChapterId === chapter.id} onClick={() => onRetry(chapter.id)}>{retryingChapterId === chapter.id ? "正在重新分析…" : "重新分析本章"}</button>}
                </div>
                <span className="analysis-list-state">{activeTab === "ready" ? "已完成" : activeTab === "running" ? "处理中" : activeTab === "queued" ? "队列中" : "待处理"}</span>
              </li>
            ))}
          </ol>
        )}
      </section>
    </section>
  );
}

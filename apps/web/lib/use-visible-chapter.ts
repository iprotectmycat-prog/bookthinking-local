"use client";

import { useEffect, useState } from "react";

/**
 * 总览页有五十多张章节卡片、纵向两万多像素，侧栏此前没有任何「你在哪」的提示。
 * 这里用 IntersectionObserver 找出当前视口内最靠上的章节卡片，回传其 id
 * 供侧栏高亮。滚动本身不做监听，避免长页面上的高频重排。
 */
export function useVisibleChapter(chapterIds: number[]): number | undefined {
  const [visibleId, setVisibleId] = useState<number>();
  const key = chapterIds.join(",");

  useEffect(() => {
    if (typeof IntersectionObserver === "undefined") return;
    const ids = key ? key.split(",").map(Number) : [];
    if (ids.length === 0) return;

    const elements = ids
      .map((id) => document.getElementById(`chapter-${id}`))
      .filter((element): element is HTMLElement => element !== null);
    if (elements.length === 0) return;

    const intersecting = new Map<number, number>();
    const observer = new IntersectionObserver(
      (entries) => {
        for (const entry of entries) {
          const id = Number(entry.target.id.replace("chapter-", ""));
          if (entry.isIntersecting) {
            intersecting.set(id, entry.boundingClientRect.top);
          } else {
            intersecting.delete(id);
          }
        }
        if (intersecting.size === 0) return;
        // 视口内可能同时有多张卡片，取最靠上的那张作为「当前章节」。
        const topmost = [...intersecting.entries()].sort((a, b) => a[1] - b[1])[0];
        setVisibleId(topmost[0]);
      },
      // 顶部留出一块死区，避免刚滚进视口边缘的卡片就抢走高亮。
      { rootMargin: "-80px 0px -60% 0px", threshold: 0 },
    );

    elements.forEach((element) => observer.observe(element));
    return () => observer.disconnect();
  }, [key]);

  return visibleId;
}

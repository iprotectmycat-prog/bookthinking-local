"use client";

import { useEffect, useState } from "react";

import { apiJson } from "../lib/api";
import type { ExternalBookLink } from "../lib/types";

export function DoubanBookLink({ bookId, title }: { bookId: string; title: string }) {
  const [link, setLink] = useState<ExternalBookLink | null>(null);

  useEffect(() => {
    let active = true;
    apiJson<ExternalBookLink>(`/books/${bookId}/external-links/douban`)
      .then((result) => { if (active) setLink(result); })
      .catch(() => { if (active) setLink(null); });
    return () => { active = false; };
  }, [bookId]);

  if (link?.status !== "matched" || !link.url) return null;
  return (
    <>
      <span className="book-source-separator" aria-hidden="true">·</span>
      <a
        className="douban-book-link"
        href={link.url}
        target="_blank"
        rel="noreferrer"
        aria-label={`在豆瓣查看《${title}》`}
      >
        豆瓣 <span aria-hidden="true">↗</span>
      </a>
    </>
  );
}

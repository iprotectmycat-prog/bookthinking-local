"use client";
import { useEffect, useState } from "react";
import Link from "next/link";
import { useParams } from "next/navigation";
import { apiJson } from "../../../../lib/api";
import type { Book } from "../../../../lib/types";
import { ChapterEditor } from "../../../../components/ChapterEditor";
export default function ChaptersPage() {
  const { bookId } = useParams<{ bookId: string }>();
  const [book, setBook] = useState<Book>();
  const [error, setError] = useState("");
  useEffect(() => {
    apiJson<Book>(`/books/${bookId}`).then(setBook).catch((reason) => setError(reason.message || "无法读取章节草稿"));
  }, [bookId]);
  if (error) return <main className="state-page"><p role="alert">{error}</p><Link href="/">返回首页</Link></main>;
  if (book?.access_scope === "public") {
    return <main className="state-page"><Link href={`/books/${bookId}/overview`}>返回书籍导读</Link></main>;
  }
  return book ? <ChapterEditor book={book} /> : <main className="state-page"><p>正在读取章节草稿…</p></main>;
}

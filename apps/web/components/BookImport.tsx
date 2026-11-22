"use client";

import { useId, useRef, useState, type ReactNode } from "react";

import { API_BASE_URL } from "../lib/api";

// Kobo's KEPUB is a standard EPUB container, so it is accepted alongside .epub.
// Kindle and comic extensions are listed too, on purpose: the file picker would
// otherwise hide them, and the user would never see the API's format-specific hint
// telling them to convert the file first.
const ACCEPTED_FILES = [
  "application/pdf",
  "application/epub+zip",
  ".pdf",
  ".epub",
  ".kepub",
  ".mobi",
  ".azw",
  ".azw3",
].join(",");

type BookImportProps = {
  buttonClassName?: string;
  label?: ReactNode;
};

export function BookImport({ buttonClassName = "primary-button", label = "＋ 导入并分析" }: BookImportProps) {
  const inputRef = useRef<HTMLInputElement>(null);
  const messageId = useId();
  const [message, setMessage] = useState("");
  const [submitting, setSubmitting] = useState(false);

  async function submit(file: File) {
    const formData = new FormData();
    formData.append("file", file);
    setSubmitting(true);
    setMessage(`正在解析《${file.name}》…`);
    try {
      const response = await fetch(`${API_BASE_URL}/books`, { method: "POST", body: formData });
      const body = await response.json().catch(() => ({ detail: `导入失败（HTTP ${response.status}）` }));
      if (response.ok) window.location.assign(`/books/${body.id}/chapters`);
      else {
        setMessage(typeof body.detail === "string" ? body.detail : "导入失败，请稍后重试。");
        setSubmitting(false);
      }
    } catch {
      setMessage("暂时无法连接，请稍后重试。");
      setSubmitting(false);
    }
  }

  return (
    <div className="import-form" aria-busy={submitting}>
      <input
        ref={inputRef}
        aria-label="选择 PDF 或 EPUB 文件"
        type="file"
        tabIndex={-1}
        accept={ACCEPTED_FILES}
        disabled={submitting}
        onChange={(event) => {
          const file = event.target.files?.[0];
          event.target.value = "";
          setMessage("");
          if (file) void submit(file);
        }}
      />
      <button className={buttonClassName} type="button" aria-describedby={message ? messageId : undefined} disabled={submitting} onClick={() => inputRef.current?.click()}>
        {submitting ? "正在解析…" : label}
      </button>
      <p id={messageId} role="status" aria-live="polite">{message}</p>
    </div>
  );
}

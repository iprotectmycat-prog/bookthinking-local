"use client";

import { useEffect, useRef, useState, type FormEvent } from "react";
import { ArrowUp, Check, Copy, Sparkle, Stop } from "@phosphor-icons/react";
import { apiJson } from "../lib/api";
import type { EpubPassage, SourceChatTurn } from "../lib/epub-annotations";

import { EpubSelectionHeading } from "./EpubSelectionPanel";

function AnswerText({ text }: { text: string }) {
  // Render basic model formatting as React text, keeping HTML inert.
  function inline(line: string) {
    return line.split(/(\*\*[^*]+\*\*)/g).map((part, index) => part.startsWith("**")
      ? <strong key={index}>{part.slice(2, -2)}</strong>
      : part);
  }
  return <div className="epub-answer-text">{text.split(/\n\s*\n/).map((block, index) => {
    const lines = block.split("\n");
    if (lines.every((line) => /^[-*] /.test(line))) {
      return <ul key={index}>{lines.map((line, item) => <li key={item}>{inline(line.slice(2))}</li>)}</ul>;
    }
    if (lines.every((line) => /^\d+[.)] /.test(line))) {
      return <ol key={index}>{lines.map((line, item) => <li key={item}>{inline(line.replace(/^\d+[.)] /, ""))}</li>)}</ol>;
    }
    return <div className="epub-answer-paragraph" key={index}>{lines.map((line, item) => /^#{1,6} /.test(line)
      ? <h4 key={item}>{inline(line.replace(/^#{1,6} /, ""))}</h4>
      : <span className="epub-answer-line" key={item}>{inline(line)}{item < lines.length - 1 ? "\n" : ""}</span>)}</div>;
  })}</div>;
}

export function EpubSourceChat({ bookId, passage, chapterSummary, turns, onSave, onBack, onClose }: {
  bookId: string;
  passage: EpubPassage;
  chapterSummary: string;
  turns: SourceChatTurn[];
  onSave: (turn: SourceChatTurn) => void;
  onBack: () => void;
  onClose: () => void;
}) {
  const [question, setQuestion] = useState("");
  const [settings, setSettings] = useState<{ model: string }>();
  const [pendingQuestion, setPendingQuestion] = useState("");
  const [error, setError] = useState("");
  const [copied, setCopied] = useState<number>();
  const conversation = useRef<HTMLDivElement>(null);
  const input = useRef<HTMLTextAreaElement>(null);
  const request = useRef<AbortController | null>(null);
  const path = `/books/${encodeURIComponent(bookId)}/source-chat`;
  const pending = !!pendingQuestion;

  useEffect(() => {
    const controller = new AbortController();
    apiJson<{ model: string }>(path, { signal: controller.signal }, { redirectOnUnauthorized: false })
      .then(setSettings)
      .catch((reason) => {
        if (!controller.signal.aborted) setError(reason instanceof Error ? reason.message : "无法读取分析模型设置。");
      });
    return () => {
      controller.abort();
      request.current?.abort();
    };
  }, [path]);

  useEffect(() => {
    const element = conversation.current;
    if (element) element.scrollTop = element.scrollHeight;
  }, [turns, pendingQuestion, error]);

  useEffect(() => {
    if (!input.current) return;
    input.current.style.height = "auto";
    input.current.style.height = `${Math.min(input.current.scrollHeight, 132)}px`;
  }, [question]);

  useEffect(() => {
    if (copied === undefined) return;
    const timeout = window.setTimeout(() => setCopied(undefined), 2000);
    return () => window.clearTimeout(timeout);
  }, [copied]);

  async function send(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const currentQuestion = question.trim();
    if (!currentQuestion || request.current || !settings) return;
    const controller = new AbortController();
    request.current = controller;
    setPendingQuestion(currentQuestion);
    setQuestion("");
    setError("");
    try {
      const result = await apiJson<Omit<SourceChatTurn, "question">>(path, {
        method: "POST",
        signal: controller.signal,
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          quote: passage.quote,
          before: passage.before,
          after: passage.after,
          chapter_summary: chapterSummary.slice(0, 1500),
          turns: turns.slice(-4).map(({ question, answer }) => ({ question, answer: answer.slice(0, 4000) })),
          question: currentQuestion,
        }),
      }, { redirectOnUnauthorized: false });
      if (!controller.signal.aborted) onSave({ ...result, question: currentQuestion });
    } catch (reason) {
      if (!controller.signal.aborted) {
        setQuestion(currentQuestion);
        setError(reason instanceof Error && reason.name !== "TypeError" ? reason.message : "发送失败，问题已保留，请重试。");
      }
    } finally {
      if (request.current === controller) {
        request.current = null;
        setPendingQuestion("");
        input.current?.focus({ preventScroll: true });
      }
    }
  }

  function stopWaiting() {
    request.current?.abort();
    request.current = null;
    setQuestion(pendingQuestion);
    setPendingQuestion("");
    input.current?.focus({ preventScroll: true });
  }

  async function copyAnswer(answer: string, index: number) {
    try {
      await navigator.clipboard.writeText(answer);
      setCopied(index);
    } catch {
      setError("复制失败，请选中回答文字复制。");
    }
  }

  return (
    <>
      <EpubSelectionHeading title="问 AI" onBack={onBack} onClose={onClose}>
        <span className="epub-source-chat-model" title={settings?.model}>
          {settings?.model ?? (error ? "模型未连接" : "正在连接模型…")}
        </span>
      </EpubSelectionHeading>
      {(turns.length > 0 || pending) && (
        <div ref={conversation} className="epub-source-chat-turns" role="log" aria-label="问答内容" tabIndex={0}>
          {turns.map((turn, index) => (
            <div className="epub-chat-exchange" key={index}>
              <div className="epub-chat-user"><span className="visually-hidden">你</span>{turn.question}</div>
              <div className="epub-chat-assistant">
                {turn.thinking && <details className="epub-chat-thinking"><summary>查看思考内容</summary><p>{turn.thinking}</p></details>}
                <AnswerText text={turn.answer} />
                <button className="epub-icon-button epub-copy-answer" type="button" aria-label={copied === index ? "已复制" : "复制回答"} title={copied === index ? "已复制" : "复制回答"} onClick={() => void copyAnswer(turn.answer, index)}>
                  {copied === index ? <Check size={16} aria-hidden="true" /> : <Copy size={16} aria-hidden="true" />}
                </button>
              </div>
            </div>
          ))}
          {pending && <div className="epub-chat-exchange">
            <div className="epub-chat-user">{pendingQuestion}</div>
            <div className="epub-chat-waiting" role="status">
              <Sparkle size={18} aria-hidden="true" /><span>正在回复</span><span className="epub-waiting-dots" aria-hidden="true">•••</span>
            </div>
          </div>}
        </div>
      )}
      {error && <p className="epub-chat-error" role="alert">{error}</p>}
      <form className="epub-chat-composer" onSubmit={send}>
        <textarea
          ref={input}
          aria-label="向 AI 提问"
          placeholder={pending ? "正在等待回复…" : turns.length ? "继续追问…" : "你对这段有什么疑问？"}
          value={question}
          maxLength={1000}
          rows={2}
          readOnly={pending}
          onChange={(event) => setQuestion(event.target.value)}
          onKeyDown={(event) => {
            if (event.key === "Enter" && !event.shiftKey && !event.nativeEvent.isComposing && event.keyCode !== 229) {
              event.preventDefault();
              event.currentTarget.form?.requestSubmit();
            }
          }}
        />
        {pending ? (
          <button className="epub-send-button" type="button" aria-label="停止等待" title="停止等待" onClick={(event) => { event.preventDefault(); stopWaiting(); }}>
            <Stop size={16} weight="fill" aria-hidden="true" />
          </button>
        ) : (
          <button className="epub-send-button" type="submit" disabled={!settings || !question.trim()} aria-label="发送" title="发送 · Enter">
            <ArrowUp size={20} weight="bold" aria-hidden="true" />
          </button>
        )}
      </form>
    </>
  );
}

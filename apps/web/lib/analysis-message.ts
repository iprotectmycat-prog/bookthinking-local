import type { AnalysisStatus } from "./types";

const STATUS_MESSAGES: Record<AnalysisStatus, string> = {
  pending: "尚未开始分析。",
  generating: "正在分析这一章，请稍候。",
  ready: "",
  skipped: "这是书籍的结构页（如封面、版权页、目录或分卷标题），没有正文可分析。",
  summary_only:
    "这是正文之外的内容（如前言、后记、致谢），可以直接阅读原文，但它的观点不计入全书核心结论。",
  insufficient_evidence: "模型给出的观点无法在原文中逐字核对，为保证每条结论都可回查，本章分析已作废。可重新分析试试。",
  failed: "这一章分析没能完成。可以重新分析，若反复失败请检查模型设置。",
  stale: "章节划分已经改动过，本章分析需要重新生成。",
};

const TECHNICAL_PATTERNS = [
  /validation error/i,
  /\bpydantic\b/i,
  /\btraceback\b/i,
  /https?:\/\/errors\./i,
  /\[type=[^\]]+\]/i,
  /input_value=/i,
  /input_type=/i,
  /\b[A-Z][A-Za-z]*(Error|Exception)\b/,
];

/**
 * 面向读者的状态文案。绝不返回后端原始异常信息 —— 那些内容会泄漏
 * 模型 schema、依赖库版本和内部字段名，对读者也毫无意义。
 */
export function statusMessage(status: AnalysisStatus): string {
  return STATUS_MESSAGES[status] ?? "本章暂时无法阅读。";
}

/**
 * 判断一段后端返回的原因是否是给工程师看的技术细节。
 * 命中的内容只应折叠展示或写入日志，不能当作正文呈现给读者。
 */
export function isTechnicalDetail(reason: string | null | undefined): boolean {
  if (!reason) return false;
  return TECHNICAL_PATTERNS.some((pattern) => pattern.test(reason));
}

/**
 * 把后端 failure_reason 拆成「读者看的说明」与「工程师看的细节」两部分。
 * 技术性报错一律降级为可折叠的 detail，正文位置永远是人话。
 */
export function describeFailure(
  status: AnalysisStatus,
  reason: string | null | undefined,
): { message: string; detail: string | null } {
  const fallback = statusMessage(status);
  if (!reason) return { message: fallback, detail: null };
  if (isTechnicalDetail(reason)) return { message: fallback, detail: reason };
  // 后端有时给的是内部状态标签而非说明（如 skipped 章节的「结构标题」）。
  // 这类过短的词对读者几乎没有信息量，用完整文案替代。
  if (reason.trim().length <= 6) return { message: fallback, detail: null };
  return { message: reason, detail: null };
}

/**
 * 请求失败时的横幅文案。同样不能把原始异常直接贴给读者。
 */
export function describeRequestError(
  error: unknown,
  fallback: string,
): { message: string; detail: string | null } {
  const raw = error instanceof Error ? error.message : typeof error === "string" ? error : "";
  if (!raw) return { message: fallback, detail: null };
  if (isTechnicalDetail(raw)) return { message: fallback, detail: raw };
  return { message: raw, detail: null };
}

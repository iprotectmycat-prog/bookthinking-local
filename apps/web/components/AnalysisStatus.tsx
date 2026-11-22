import type { AnalysisStatus as Status } from "../lib/types";

const LABELS: Record<Status, string> = {
  pending: "等待分析",
  generating: "正在分析",
  ready: "可阅读",
  skipped: "未调用模型",
  summary_only: "仅作概述",
  insufficient_evidence: "证据不足",
  failed: "生成失败",
  stale: "需要更新",
};

export function AnalysisStatus({ status }: { status: Status }) {
  return <span className={`status status-${status}`}>{LABELS[status]}</span>;
}

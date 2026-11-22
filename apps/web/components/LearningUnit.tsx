"use client";

import { useState } from "react";
import { API_BASE_URL } from "../lib/api";

export type LearningUnitData = { id: string; question: string; options: Record<string, string>; evidence: { chapter: string; page: number; quote: string }[] };

export function LearningUnit({ unit }: { unit: LearningUnitData }) {
  const [result, setResult] = useState<{ prediction: { selected_answer: string; is_correct: boolean }; explanation: string } | null>(null);
  const [error, setError] = useState("");
  async function answer(answer: string) { try { const response = await fetch(`${API_BASE_URL}/learning-units/${unit.id}/predictions`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ answer }) }); const body = await response.json(); if (response.ok) setResult(body); else setError(body.detail); } catch { setError("无法连接本机 API。"); } }
  return <section><h2>{unit.question}</h2>{Object.entries(unit.options).map(([key, value]) => <button key={key} disabled={Boolean(result)} onClick={() => answer(key)}>选项 {key}：{value}</button>)}{error && <p role="alert">{error}</p>}{result && <section><h3>证据解释</h3><p>{result.prediction.is_correct ? "回答正确" : "需要再想想"}：{result.prediction.selected_answer}</p><p>{result.explanation}</p><p>第 {unit.evidence[0].page} 页：{unit.evidence[0].quote}</p></section>}</section>;
}

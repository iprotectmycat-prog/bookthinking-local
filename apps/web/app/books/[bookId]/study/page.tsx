"use client";
import { useEffect, useState } from "react";
import { useParams } from "next/navigation";
import { API_BASE_URL } from "../../../../lib/api";
import { LearningUnit, LearningUnitData } from "../../../../components/LearningUnit";
export default function StudyPage() { const { bookId } = useParams<{ bookId: string }>(); const [unit, setUnit] = useState<LearningUnitData>(); const [error, setError] = useState(""); useEffect(() => { fetch(`${API_BASE_URL}/books/${bookId}/learning-units`, { method: "POST" }).then(async r => { const body = await r.json(); if (!r.ok) throw new Error(body.detail); return body; }).then(setUnit).catch(error => setError(error.message || "无法生成学习单元")); }, [bookId]); if (error) return <p role="alert">{error}</p>; return unit ? <LearningUnit unit={unit} /> : <p>生成带原文证据的学习单元…</p>; }

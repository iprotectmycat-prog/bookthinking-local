import { describe, expect, it } from "vitest";

import { describeFailure, describeRequestError, isTechnicalDetail, statusMessage } from "../lib/analysis-message";

// 真实抓到的泄漏内容：总览页把它原样当正文渲染给了读者。
const PYDANTIC_LEAK =
  "模型返回的章节分析结构无效：1 validation error for ChapterAnalysisDraft role_in_book " +
  "Field required [type=missing, input_value={'chapter_question': '中美贸易…'}, input_type=dict] " +
  "For further information visit https://errors.pydantic.dev/2.13/v/missing";

describe("isTechnicalDetail", () => {
  it("recognises a pydantic validation dump", () => {
    expect(isTechnicalDetail(PYDANTIC_LEAK)).toBe(true);
  });

  it("recognises bare exception names and tracebacks", () => {
    expect(isTechnicalDetail("Traceback (most recent call last):")).toBe(true);
    expect(isTechnicalDetail("ConnectionError: timed out")).toBe(true);
  });

  it("treats a plain Chinese explanation as reader-facing", () => {
    expect(isTechnicalDetail("模型额度已用尽，请稍后再试。")).toBe(false);
    expect(isTechnicalDetail(null)).toBe(false);
  });
});

describe("describeFailure", () => {
  it("never puts a pydantic dump in the reader-facing message", () => {
    const { message, detail } = describeFailure("failed", PYDANTIC_LEAK);

    expect(message).not.toContain("validation error");
    expect(message).not.toContain("pydantic");
    expect(message).not.toContain("input_value");
    expect(message).toBe(statusMessage("failed"));
    // 细节仍然保留，只是降级为可折叠内容，排查问题时不丢信息。
    expect(detail).toBe(PYDANTIC_LEAK);
  });

  it("keeps a human-written reason as the message", () => {
    const { message, detail } = describeFailure("failed", "模型额度已用尽，请稍后再试。");

    expect(message).toBe("模型额度已用尽，请稍后再试。");
    expect(detail).toBeNull();
  });

  it("explains why a structural page has no analysis", () => {
    const { message } = describeFailure("skipped", null);

    expect(message).toContain("结构页");
    expect(message).not.toBe("");
  });

  it("replaces a terse internal label with the full explanation", () => {
    // 后端对 skipped 章节返回的 failure_reason 是「结构标题」四个字，
    // 原样显示等于没解释，读者仍然不知道这页为什么是空的。
    const { message, detail } = describeFailure("skipped", "结构标题");

    expect(message).toBe(statusMessage("skipped"));
    expect(message).toContain("结构页");
    expect(detail).toBeNull();
  });

  it("explains the evidence-first tradeoff for insufficient_evidence", () => {
    expect(describeFailure("insufficient_evidence", null).message).toContain("逐字核对");
  });
});

describe("describeRequestError", () => {
  it("hides a technical request failure behind the fallback text", () => {
    const { message, detail } = describeRequestError(new Error(PYDANTIC_LEAK), "章节分析启动失败。");

    expect(message).toBe("章节分析启动失败。");
    expect(detail).toBe(PYDANTIC_LEAK);
  });

  it("passes through a readable backend message", () => {
    const { message } = describeRequestError(new Error("请先在设置里配置 OpenAI 密钥。"), "启动失败。");

    expect(message).toBe("请先在设置里配置 OpenAI 密钥。");
  });

  it("falls back when the error carries no message", () => {
    expect(describeRequestError(new Error(""), "读取失败。").message).toBe("读取失败。");
    expect(describeRequestError(undefined, "读取失败。").message).toBe("读取失败。");
  });
});

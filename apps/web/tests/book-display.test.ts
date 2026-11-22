import { describe, expect, it } from "vitest";

import { getBookDisplay } from "../lib/book-display";

describe("getBookDisplay", () => {
  it("keeps a short formal title separate from a noisy course subtitle", () => {
    expect(
      getBookDisplay(
        "置身室内 中国政府与经济发展【复旦经院“毕业课”解读经济生活背后的政府角色】.epub",
        "epub",
      ),
    ).toEqual({ title: "置身室内", metadata: "EPUB" });
  });

  it("strips the download-site suffix instead of showing it as the author", () => {
    // 书架上原本显示成「兰小欢,非墨盟) (z-lib.org」，作者与站点标记糊在一起。
    expect(
      getBookDisplay(
        "置身事内 中国政府与经济发展【复旦经院“毕业课”解读经济生活背后的政府角色。罗永浩、刘格菘、张军、周黎安、王烁联袂推荐】 (兰小欢,非墨盟) (z-lib.org).epub",
        "epub",
      ),
    ).toEqual({ title: "置身事内", metadata: "兰小欢,非墨盟 · EPUB" });
  });

  it("keeps a plain title untouched", () => {
    expect(getBookDisplay("原则.epub", "epub")).toEqual({ title: "原则", metadata: "EPUB" });
  });

  it("reads the author group when there is no marketing subtitle", () => {
    expect(getBookDisplay("穷查理宝典 (查理·芒格).pdf", "pdf")).toEqual({
      title: "穷查理宝典",
      metadata: "查理·芒格 · PDF",
    });
  });

  it("drops a colon-separated subtitle", () => {
    expect(getBookDisplay("影响力：说服的心理学.epub", "epub")).toEqual({
      title: "影响力",
      metadata: "EPUB",
    });
  });

  it("leaves English titles with spaces alone", () => {
    // 英文书名天然含空格，不能按「空格后是副标题」的中文规则切开。
    expect(getBookDisplay("Thinking Fast and Slow.epub", "epub")).toEqual({
      title: "Thinking Fast and Slow",
      metadata: "EPUB",
    });
  });

  it("accepts kepub files", () => {
    expect(getBookDisplay("置身事内.kepub.epub", "epub")).toEqual({
      title: "置身事内",
      metadata: "EPUB",
    });
  });

  it("falls back to a placeholder when nothing is left", () => {
    expect(getBookDisplay(".epub", "epub")).toEqual({ title: "未命名书籍", metadata: "EPUB" });
  });
});

import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type { Book } from "../lib/types";

const { apiJson } = vi.hoisted(() => ({ apiJson: vi.fn() }));

vi.mock("next/link", () => ({ default: ({ children }: { children: React.ReactNode }) => <a>{children}</a> }));
vi.mock("../lib/api", () => ({ apiJson }));

import { ChapterEditor } from "../components/ChapterEditor";

const structuredEpubBook: Book = {
  id: "turtle",
  filename: "海龟交易法则.epub",
  source_format: "epub", access_scope: "owned",
  status: "awaiting_chapter_confirmation",
  chapters: [
    {
      title: "扉页",
      source_start_page: 1,
      source_end_page: 1,
      depth: 0,
      parent_title: null,
      nav_kind: "front_matter",
      in_body: false,
      structural_role: "front_matter",
      role_source: "publisher_landmark",
      role_confidence: "high",
    },
    {
      title: "第二章 揭秘海龟思维",
      source_start_page: 14,
      source_end_page: 14,
      depth: 0,
      parent_title: null,
      nav_kind: "chapter",
      in_body: true,
      structural_role: "body",
      role_source: "publisher_landmark",
      role_confidence: "high",
    },
    {
      title: "情绪陷阱",
      source_start_page: 15,
      source_end_page: 15,
      depth: 1,
      parent_title: "第二章 揭秘海龟思维",
      nav_kind: "chapter",
      in_body: true,
      structural_role: "body",
      role_source: "publisher_landmark",
      role_confidence: "high",
    },
    {
      title: "海龟交易策略",
      source_start_page: 16,
      source_end_page: 16,
      depth: 1,
      parent_title: "第二章 揭秘海龟思维",
      nav_kind: "chapter",
      in_body: true,
      structural_role: "body",
      role_source: "publisher_landmark",
      role_confidence: "high",
    },
    {
      title: "补充材料",
      source_start_page: 17,
      source_end_page: 17,
      depth: 0,
      parent_title: null,
      nav_kind: "plain",
      in_body: true,
      structural_role: "unknown",
      role_source: "unknown",
      role_confidence: "low",
    },
    {
      title: "后记",
      source_start_page: 18,
      source_end_page: 18,
      depth: 0,
      parent_title: null,
      nav_kind: "back_matter",
      in_body: false,
      structural_role: "back_matter",
      role_source: "title_fallback",
      role_confidence: "medium",
    },
    {
      title: "后记1",
      source_start_page: 19,
      source_end_page: 19,
      depth: 1,
      parent_title: "后记",
      nav_kind: "chapter",
      in_body: false,
      structural_role: "back_matter",
      role_source: "parent_inherited",
      role_confidence: "medium",
    },
  ],
};

const duplicateEndingBook: Book = {
  ...structuredEpubBook,
  chapters: [
    { title: "第一卷", source_start_page: 1, source_end_page: 1, depth: 0, nav_kind: "part" },
    { title: "第一章", source_start_page: 2, source_end_page: 2, depth: 1, parent_title: "第一卷", nav_kind: "chapter" },
    { title: "结语", source_start_page: 3, source_end_page: 3, depth: 2, parent_title: "第一章", nav_kind: "section" },
    { title: "第二卷", source_start_page: 4, source_end_page: 4, depth: 0, nav_kind: "part" },
    { title: "第一章", source_start_page: 5, source_end_page: 5, depth: 1, parent_title: "第二卷", nav_kind: "chapter" },
    { title: "结语", source_start_page: 6, source_end_page: 6, depth: 2, parent_title: "第一章", nav_kind: "section" },
  ],
};

describe("ChapterEditor hierarchy", () => {
  beforeEach(() => apiJson.mockReset());
  afterEach(() => {
    vi.restoreAllMocks();
    vi.unstubAllGlobals();
  });

  it("groups EPUB sections under collapsed publisher chapters", async () => {
    const user = userEvent.setup();
    render(<ChapterEditor book={structuredEpubBook} />);

    const toggle = screen.getByRole("button", { name: "展开「第二章 揭秘海龟思维」的小节" });
    expect(toggle).toHaveAttribute("aria-expanded", "false");
    expect(screen.queryByDisplayValue("情绪陷阱")).not.toBeInTheDocument();

    await user.click(toggle);

    expect(screen.getByDisplayValue("情绪陷阱")).toBeInTheDocument();
    expect(screen.getByDisplayValue("海龟交易策略")).toBeInTheDocument();
    expect(screen.getByText("2 个小节")).toBeInTheDocument();
    expect(toggle).toHaveAttribute("aria-expanded", "true");
  });

  it("uses parsed title and subtitle instead of the uploaded EPUB filename", () => {
    render(
      <ChapterEditor
        book={{
          ...structuredEpubBook,
          title: "反脆弱",
          subtitle: "从不确定性中获益",
          filename: "反脆弱：从不确定性中获益 = Antifragile Things That Gain from Disorder (Z-Library).epub",
        } as Book}
      />,
    );

    expect(screen.getByText("反脆弱：从不确定性中获益")).toBeInTheDocument();
    expect(screen.queryByText(/Antifragile Things That Gain from Disorder/)).not.toBeInTheDocument();
  });

  it("nests publisher chapters under their volume", async () => {
    const user = userEvent.setup();
    const volumeBook: Book = {
      ...structuredEpubBook,
      chapters: [
        {
          title: "第一卷 反脆弱性：介绍",
          source_start_page: 1,
          source_end_page: 1,
          depth: 0,
          parent_title: null,
          nav_kind: "part",
        },
        {
          title: "第1章 达摩克利斯之剑和九头蛇怪",
          source_start_page: 2,
          source_end_page: 2,
          depth: 1,
          parent_title: "第一卷 反脆弱性：介绍",
          nav_kind: "chapter",
        },
      ],
    };

    render(<ChapterEditor book={volumeBook} />);

    const toggle = screen.getByRole("button", { name: "展开「第一卷 反脆弱性：介绍」的章节" });
    expect(screen.queryByDisplayValue("第1章 达摩克利斯之剑和九头蛇怪")).not.toBeInTheDocument();

    await user.click(toggle);

    expect(screen.getByDisplayValue("第1章 达摩克利斯之剑和九头蛇怪")).toBeInTheDocument();
  });

  it("keeps every published outline level collapsible", async () => {
    const user = userEvent.setup();
    const threeLevelBook: Book = {
      ...structuredEpubBook,
      chapters: [
        {
          title: "第一部分 财富",
          source_start_page: 11,
          source_end_page: 11,
          depth: 0,
          parent_title: null,
          nav_kind: "part",
          structural_role: "body",
        },
        {
          title: "第一章 积累财富",
          source_start_page: 12,
          source_end_page: 12,
          depth: 1,
          parent_title: "第一部分 财富",
          nav_kind: "chapter",
          structural_role: "body",
        },
        {
          title: "认识财富创造的原理",
          source_start_page: 13,
          source_end_page: 13,
          depth: 2,
          parent_title: "第一章 积累财富",
          nav_kind: "section",
          structural_role: "body",
        },
      ],
    };

    render(<ChapterEditor book={threeLevelBook} />);

    expect(screen.getByDisplayValue("第一部分 财富")).toBeInTheDocument();
    const partToggle = screen.getByRole("button", { name: "展开「第一部分 财富」的章节" });
    expect(screen.queryByDisplayValue("认识财富创造的原理")).not.toBeInTheDocument();

    await user.click(partToggle);
    const chapterToggle = screen.getByRole("button", { name: "展开「第一章 积累财富」的小节" });
    await user.click(chapterToggle);

    expect(screen.getByDisplayValue("认识财富创造的原理")).toBeInTheDocument();
    expect(screen.getByText("1 个小节")).toBeInTheDocument();
  });

  it("folds classified front and back matter while keeping unknown entries visible", async () => {
    const user = userEvent.setup();
    render(<ChapterEditor book={structuredEpubBook} />);

    const frontToggle = screen.getByRole("button", { name: "展开前置内容" });
    const backToggle = screen.getByRole("button", { name: "展开后置内容" });
    expect(screen.queryByDisplayValue("扉页")).not.toBeInTheDocument();
    expect(screen.queryByDisplayValue("后记1")).not.toBeInTheDocument();
    expect(screen.getByDisplayValue("补充材料")).toBeInTheDocument();

    await user.click(frontToggle);
    await user.click(backToggle);

    expect(screen.getByDisplayValue("扉页")).toBeInTheDocument();
    expect(screen.getByDisplayValue("后记")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "展开「后记」的小节" }));
    expect(screen.getByDisplayValue("后记1")).toBeInTheDocument();
  });

  it("uses the ordinary expandable chapter treatment for front matter and preserves its hierarchy", async () => {
    const user = userEvent.setup();
    const book: Book = {
      ...structuredEpubBook,
      chapters: [
        { title: "序", source_start_page: 1, source_end_page: 1, nav_kind: "chapter" },
        { title: "致读者", source_start_page: 2, source_end_page: 2, depth: 1, parent_title: "序", nav_kind: "section" },
        { title: "第一章 正文", source_start_page: 3, source_end_page: 3, nav_kind: "chapter", structural_role: "body" },
      ],
    };

    render(<ChapterEditor book={book} />);

    const frontToggle = screen.getByRole("button", { name: "展开前置内容" });
    expect(frontToggle).toHaveClass("epub-chapter-toggle");
    await user.click(frontToggle);
    expect(screen.getByRole("button", { name: "展开「序」的小节" })).toBeInTheDocument();
    expect(screen.queryByDisplayValue("致读者")).not.toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "展开「序」的小节" }));
    expect(screen.getByDisplayValue("致读者")).toBeInTheDocument();
  });

  it("recognizes publisher title variants from the reported books without moving meaningful body entries", () => {
    const book: Book = {
      ...structuredEpubBook,
      chapters: [
        { title: "阅读提示", source_start_page: 1, source_end_page: 1, nav_kind: "plain" },
        { title: "序 财报是用来证伪的", source_start_page: 2, source_end_page: 2, nav_kind: "plain" },
        { title: "理想国译丛序", source_start_page: 3, source_end_page: 3, nav_kind: "plain" },
        { title: "图书在版编目（CIP）数据", source_start_page: 4, source_end_page: 4, nav_kind: "plain" },
        { title: "致《失控》中文版的读者们", source_start_page: 5, source_end_page: 5, nav_kind: "plain" },
        { title: "第一章 正文", source_start_page: 6, source_end_page: 6, nav_kind: "chapter", structural_role: "body" },
        { title: "翻译后记", source_start_page: 7, source_end_page: 7, nav_kind: "plain" },
        { title: "封底", source_start_page: 8, source_end_page: 8, nav_kind: "plain" },
        { title: "自我分析：你的财务状况如何", source_start_page: 9, source_end_page: 9, nav_kind: "plain" },
      ],
    };

    render(<ChapterEditor book={book} />);

    expect(screen.getByText("5 项")).toBeInTheDocument();
    expect(screen.getByText("2 项")).toBeInTheDocument();
    expect(screen.getByDisplayValue("自我分析：你的财务状况如何")).toBeInTheDocument();
  });

  it("keeps every volume of an EPUB collection in the main outline when landmark and content signals conflict", () => {
    const book: Book = {
      ...structuredEpubBook,
      chapters: [
        { title: "封面与前置页", source_start_page: 1, source_end_page: 2, nav_kind: "front_matter", in_body: false, structural_role: "front_matter" },
        { title: "魔鬼经济学1：揭示隐藏在表象之下的真实世界", source_start_page: 3, source_end_page: 20, nav_kind: "plain", in_body: true, structural_role: "front_matter", role_source: "publisher_landmark", role_confidence: "high" },
        { title: "魔鬼经济学2：拥有清晰思维的艺术", source_start_page: 21, source_end_page: 74, nav_kind: "plain", in_body: true, structural_role: "body" },
      ],
    };

    render(<ChapterEditor book={book} />);

    expect(screen.getByText("1 项")).toBeInTheDocument();
    expect(screen.getByDisplayValue("魔鬼经济学1：揭示隐藏在表象之下的真实世界")).toBeInTheDocument();
    expect(screen.getByDisplayValue("魔鬼经济学2：拥有清晰思维的艺术")).toBeInTheDocument();
  });

  it("does not use locally numbered parts to split an anthology into front and back matter", () => {
    const book: Book = {
      ...structuredEpubBook,
      chapters: [
        { title: "坟", source_start_page: 1, source_end_page: 1, nav_kind: "chapter", in_body: true, structural_role: "body" },
        { title: "第一篇 史家对于小说之著录及论述", source_start_page: 2, source_end_page: 2, depth: 2, nav_kind: "section", in_body: true, structural_role: "body" },
        { title: "第二篇 神话与传说", source_start_page: 3, source_end_page: 3, depth: 2, nav_kind: "section", in_body: true, structural_role: "body" },
        { title: "故事新编", source_start_page: 4, source_end_page: 4, nav_kind: "chapter", in_body: true, structural_role: "body" },
      ],
    };

    render(<ChapterEditor book={book} />);

    expect(screen.queryByRole("button", { name: "展开前置内容" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "展开后置内容" })).not.toBeInTheDocument();
    expect(screen.getByDisplayValue("坟")).toBeInTheDocument();
    expect(screen.getByDisplayValue("故事新编")).toBeInTheDocument();
  });

  it("keeps a publisher-declared introduction subtree in the body before chapter one", async () => {
    const user = userEvent.setup();
    const book: Book = {
      ...structuredEpubBook,
      chapters: [
        { title: "封面与前置页", source_start_page: 1, source_end_page: 1, nav_kind: "front_matter", in_body: false, structural_role: "front_matter" },
        { title: "前 言", source_start_page: 2, source_end_page: 2, nav_kind: "plain", in_body: true, structural_role: "body", role_source: "publisher_landmark" },
        { title: "导论 何为结构思考力?", source_start_page: 3, source_end_page: 3, nav_kind: "chapter", in_body: true, structural_role: "body", role_source: "publisher_landmark" },
        { title: "第一节 Why——结构思考力的作用非凡", source_start_page: 4, source_end_page: 4, depth: 1, parent_title: "导论 何为结构思考力?", nav_kind: "section", in_body: true, structural_role: "body", role_source: "publisher_landmark" },
        { title: "第一章 明确理念打基础", source_start_page: 5, source_end_page: 5, nav_kind: "chapter", in_body: true, structural_role: "body" },
        { title: "第二章 基于目标定主题", source_start_page: 6, source_end_page: 6, nav_kind: "chapter", in_body: true, structural_role: "body" },
      ],
    };

    render(<ChapterEditor book={book} />);

    const frontToggle = screen.getByRole("button", { name: "展开前置内容" });
    expect(screen.getByText("2 项")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "展开「导论 何为结构思考力?」的小节" })).toBeInTheDocument();

    await user.click(frontToggle);
    expect(screen.getByDisplayValue("前 言")).toBeInTheDocument();
  });

  it("groups explicit non-body titles for previously parsed EPUBs", async () => {
    const user = userEvent.setup();
    const book: Book = {
      ...structuredEpubBook,
      chapters: [
        { title: "中文版序言 书中自有黄金屋", source_start_page: 1, source_end_page: 1, nav_kind: "plain" },
        { title: "驳辞：芒格论巴菲特", source_start_page: 2, source_end_page: 2, nav_kind: "plain" },
        { title: "导读", source_start_page: 3, source_end_page: 3, nav_kind: "plain" },
        { title: "第一章 查理·芒格传略", source_start_page: 4, source_end_page: 4, nav_kind: "chapter", structural_role: "body" },
        { title: "第二章 芒格的生活、学习和决策方法", source_start_page: 5, source_end_page: 5, nav_kind: "chapter", structural_role: "body" },
        { title: "查理·芒格的推荐书目", source_start_page: 6, source_end_page: 6, nav_kind: "plain" },
        { title: "查理·芒格年谱", source_start_page: 7, source_end_page: 7, nav_kind: "plain" },
      ],
    };

    render(<ChapterEditor book={book} />);

    const frontToggle = screen.getByRole("button", { name: "展开前置内容" });
    const backToggle = screen.getByRole("button", { name: "展开后置内容" });
    expect(screen.getByDisplayValue("第一章 查理·芒格传略")).toBeInTheDocument();
    expect(screen.queryByDisplayValue("导读")).not.toBeInTheDocument();
    expect(screen.queryByDisplayValue("查理·芒格年谱")).not.toBeInTheDocument();

    await user.click(frontToggle);
    await user.click(backToggle);

    expect(screen.getByDisplayValue("导读")).toBeInTheDocument();
    expect(screen.getByDisplayValue("查理·芒格年谱")).toBeInTheDocument();

    vi.stubGlobal("location", { assign: vi.fn() });
    apiJson.mockResolvedValue({});
    await user.click(screen.getByRole("button", { name: "确认并生成章节导读" }));

    const request = apiJson.mock.calls[0][1];
    const body = JSON.parse(String(request?.body));
    expect(body.chapters[0]).toMatchObject({
      title: "中文版序言 书中自有黄金屋",
      structural_role: "front_matter",
      in_body: true,
    });
    expect(body.chapters[6]).toMatchObject({
      title: "查理·芒格年谱",
      structural_role: "back_matter",
      in_body: true,
    });
  });

  it("keeps child parent titles in sync when a parent is renamed and confirmed", async () => {
    const user = userEvent.setup();
    vi.stubGlobal("location", { assign: vi.fn() });
    apiJson.mockResolvedValue({});
    render(<ChapterEditor book={structuredEpubBook} />);

    const parent = screen.getByDisplayValue("第二章 揭秘海龟思维");
    await user.clear(parent);
    await user.type(parent, "第二章 新标题");
    expect(screen.getByDisplayValue("第二章 新标题")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "确认并生成章节导读" }));
    expect(screen.queryByText("请检查章节标题和页码范围。")).not.toBeInTheDocument();

    expect(apiJson).toHaveBeenCalledWith(
      `/books/${structuredEpubBook.id}/chapters`,
      expect.objectContaining({ method: "PUT" }),
    );
    const request = apiJson.mock.calls[0][1];
    const body = JSON.parse(String(request?.body));
    expect(body.chapters[2]).toMatchObject({
      title: "情绪陷阱",
      depth: 1,
      parent_title: "第二章 新标题",
      nav_kind: "chapter",
      in_body: true,
      structural_role: "body",
      role_source: "publisher_landmark",
      role_confidence: "high",
    });
  });

  it("keeps a nested section attached when its chapter is renamed", async () => {
    const user = userEvent.setup();
    render(
      <ChapterEditor
        book={{
          ...structuredEpubBook,
          chapters: [
            {
              title: "第一卷",
              source_start_page: 1,
              source_end_page: 1,
              depth: 0,
              nav_kind: "part",
            },
            {
              title: "第1章",
              source_start_page: 2,
              source_end_page: 2,
              depth: 1,
              parent_title: "第一卷",
              nav_kind: "chapter",
            },
            {
              title: "章内小节",
              source_start_page: 3,
              source_end_page: 3,
              depth: 2,
              parent_title: "第1章",
              nav_kind: "section",
            },
          ],
        }}
      />,
    );

    await user.click(screen.getByRole("button", { name: "展开「第一卷」的章节" }));
    const chapter = screen.getByDisplayValue("第1章");
    await user.clear(chapter);
    await user.type(chapter, "第1章（修订）");

    expect(screen.queryByDisplayValue("章内小节")).not.toBeInTheDocument();
  });

  it("keeps a same-titled section in another volume attached when a chapter is renamed", async () => {
    const user = userEvent.setup();
    render(<ChapterEditor book={duplicateEndingBook} />);

    await user.click(screen.getByRole("button", { name: "展开「第二卷」的章节" }));
    const chapter = screen.getByDisplayValue("第一章");
    await user.clear(chapter);
    await user.type(chapter, "第一章（修订）");

    expect(screen.queryByDisplayValue("结语")).not.toBeInTheDocument();
  });

  it("removes only the selected same-titled section", async () => {
    const user = userEvent.setup();
    render(<ChapterEditor book={duplicateEndingBook} />);

    await user.click(screen.getByRole("button", { name: "展开「第一卷」的章节" }));
    await user.click(screen.getByRole("button", { name: "展开「第一章」的小节" }));
    await user.click(screen.getByRole("button", { name: "移除「结语」" }));
    await user.click(screen.getByRole("button", { name: "展开「第二卷」的章节" }));
    await user.click(screen.getByRole("button", { name: "展开「第一章」的小节" }));

    expect(screen.getByDisplayValue("结语")).toBeInTheDocument();
  });

  it("removes one child without removing its sibling", async () => {
    const user = userEvent.setup();
    render(<ChapterEditor book={structuredEpubBook} />);
    await user.click(screen.getByRole("button", { name: "展开「第二章 揭秘海龟思维」的小节" }));

    await user.click(screen.getByRole("button", { name: "移除「情绪陷阱」" }));

    expect(screen.queryByDisplayValue("情绪陷阱")).not.toBeInTheDocument();
    expect(screen.getByDisplayValue("海龟交易策略")).toBeInTheDocument();
  });

  it("removes a parent together with its children", async () => {
    const user = userEvent.setup();
    render(<ChapterEditor book={structuredEpubBook} />);

    await user.click(screen.getByRole("button", { name: "移除「第二章 揭秘海龟思维」" }));

    expect(screen.queryByDisplayValue("第二章 揭秘海龟思维")).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /海龟思维.*小节/ })).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "展开前置内容" })).toBeInTheDocument();
  });

  it("keeps the complete PDF editor", () => {
    render(
      <ChapterEditor
        book={{
          ...structuredEpubBook,
          source_format: "pdf",
          chapters: structuredEpubBook.chapters.slice(0, 2),
        }}
      />,
    );

    expect(screen.getAllByText("起始页")).toHaveLength(2);
    expect(screen.getAllByText("结束页")).toHaveLength(2);
    expect(screen.getAllByRole("button", { name: "拆分" })).toHaveLength(2);
    expect(screen.getAllByRole("button", { name: "合并下一章" })).toHaveLength(2);
  });

  it("keeps EPUB page and split controls hidden", () => {
    render(<ChapterEditor book={structuredEpubBook} />);

    expect(screen.queryByText("起始页")).not.toBeInTheDocument();
    expect(screen.queryByText("结束页")).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "拆分" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "合并下一章" })).not.toBeInTheDocument();
  });

  it("keeps the EPUB structure repair action out of the confirmation flow", () => {
    render(<ChapterEditor book={structuredEpubBook} />);

    expect(screen.queryByLabelText("EPUB 结构诊断")).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "重新解析 EPUB 结构" })).not.toBeInTheDocument();
  });
});

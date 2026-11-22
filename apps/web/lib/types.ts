export type AnalysisJob = {
  id: string;
  book_id: string;
  status: "queued" | "running" | "succeeded" | "failed" | "interrupted" | "superseded";
  stage: "chapters" | "overview";
  target_chapter_ids: number[];
  completed_chapter_ids: number[];
  failed_chapter_ids: number[];
  error_code: string | null;
};

export type AnalysisStatus =
  | "pending"
  | "generating"
  | "ready"
  | "skipped"
  // 有真实内容但不属于作者核心论证的章节（前言、后记、致谢）。
  | "summary_only"
  | "insufficient_evidence"
  | "failed"
  | "stale";

export type SourceFormat = "pdf" | "epub";
export type BookAccessScope = "owned" | "public";
export type StructuralRole = "front_matter" | "body" | "back_matter" | "unknown";
export type RoleConfidence = "high" | "medium" | "low";

export type SourceSpan = {
  id: number;
  source_page: number;
  quote: string;
  surrounding_text: string;
  verification_status: string;
  source_chapter_id?: number | null;
  source_chapter_title?: string | null;
  source_locator?: string | null;
};

export type EpubLocator = {
  href: string | null;
  fragment: string | null;
  cfi: string | null;
  spineIndex: number | null;
};

export type SourceReaderTarget =
  | { format: "pdf"; page: number; quote: string | null; surroundingText?: string | null; requestId: number }
  | {
      format: "epub";
      locator: EpubLocator;
      quote: string | null;
      surroundingText: string | null;
      requestId: number;
    };

export type ContentType = "book_claim" | "book_example" | "ai_explanation" | "ai_inference" | "ai_synthesis";

export type StatementContentType = "book_summary" | "ai_synthesis" | "legacy_summary";

export type AttributedStatement = {
  text: string;
  content_type: StatementContentType;
  sources: SourceSpan[];
};

export type CoreIdea = {
  id: number;
  position: number;
  title: string;
  conclusion: string;
  importance: string;
  explanation: string;
  reasoning_steps: string[];
  examples: string[];
  /** Combined list kept for analyses stored before author/ai caveats were split. */
  caveats: string[];
  /** Boundaries the author stated themselves. */
  author_caveats?: string[];
  /** Limitations we identified that the author never raised. */
  ai_caveats?: string[];
  /** The unstated assumption bridging the author's grounds and conclusion. */
  warrant?: string;
  /**
   * Fields that exist only for this book's argument structure, e.g. action_steps
   * for a how-to book. Open-ended because the backend keeps them in one JSON
   * column; render through lib/genre-fields.ts rather than iterating directly,
   * so the order and the labels stay consistent between chapters.
   */
  genre_fields?: Record<string, unknown>;
  relations: string[];
  content_type: ContentType;
  confidence: number;
  sources: SourceSpan[];
};

export type ChapterOverview = {
  id: number;
  position: number;
  title: string;
  source_start_page: number;
  source_end_page: number;
  chapter_question: string;
  one_sentence_conclusion: string;
  core_idea_titles: string[];
  role_in_book: string;
  estimated_reading_minutes: number;
  generation_status: AnalysisStatus;
  failure_reason: string | null;
  // Structure the parser read from the source file. Optional because PDF imports and
  // records created before it exist; the tree falls back to title heuristics then.
  depth?: number;
  parent_title?: string | null;
  nav_kind?: string;
  in_body?: boolean;
  structural_role?: StructuralRole;
  role_source?: string;
  role_confidence?: RoleConfidence;
  analysis_role?: "outline_only" | "analysis_unit";
};

export type BookOverview = {
  synthesis?: BookSynthesis | null;
  analysis_job?: AnalysisJob | null;
  book_id: string;
  book_title: string;
  book_authors?: string | null;
  book_publisher?: string | null;
  book_composition?: string | null;
  source_format: SourceFormat;
  core_question: string;
  one_sentence_summary: string;
  estimated_reading_minutes: number;
  ready_chapter_count: number;
  chapter_count: number;
  top_level_chapter_count?: number;
  section_count?: number;
  chapters: ChapterOverview[];
  /** Which argument structure the chapter analyses were produced under. */
  genre?: string | null;
  access_scope: BookAccessScope;
};

export type ExternalBookLink = {
  provider: "douban";
  status: "matched" | "unavailable";
  url: string | null;
};

export type ChapterAnalysis = {
  reading_record?: ReadingRecord | null;
  analysis_job?: AnalysisJob | null;
  book_id: string;
  chapter_id: number;
  title: string;
  source_start_page: number;
  source_end_page: number;
  chapter_question: string;
  one_sentence_conclusion: string;
  short_summary: string;
  argument_chain: AttributedStatement[];
  role_in_book: AttributedStatement | null;
  estimated_reading_minutes: number;
  generation_status: AnalysisStatus;
  failure_reason: string | null;
  previous_chapter_id: number | null;
  next_chapter_id: number | null;
  core_ideas: CoreIdea[];
  source_locator?: string | null;
  /** Which argument structure produced this analysis; labels genre_fields. */
  genre?: string | null;
};

export type EditableChapter = {
  id?: number;
  title: string;
  source_start_page: number;
  source_end_page: number;
  depth?: number;
  parent_title?: string | null;
  nav_kind?: string;
  in_body?: boolean;
  structural_role?: StructuralRole;
  role_source?: string;
  role_confidence?: RoleConfidence;
  analysis_role?: "outline_only" | "analysis_unit";
};

export type StructurePreview = {
  chapters: Array<EditableChapter & {
    source_locator?: string | null;
    text_sha256?: string | null;
  }>;
  diagnostics: string[];
  provider: string;
  structure_hash: string;
};

export type Book = {
  id: string;
  filename: string;
  title?: string | null;
  subtitle?: string | null;
  source_format: SourceFormat;
  status: string;
  structure_version?: string | null;
  structure_diagnostics?: string[];
  access_scope: BookAccessScope;
  chapters: EditableChapter[];
};

export type AnalyzedBook = {
  id: string;
  filename: string;
  source_format: SourceFormat;
  title?: string | null;
  authors?: string | null;
  access_scope: BookAccessScope;
};

export type AdminBook = {
  id: string;
  title?: string | null;
  filename: string;
  source_format: SourceFormat;
  visibility: "private" | "public";
  overview_status: string;
  ready_chapter_count: number;
  public_at?: string | null;
  publication_blockers: string[];
};

export type ProviderSettings = {
  provider: string;
  model: string;
  configured: boolean;
  secondary_configured?: boolean;
};

export type ReadingTopic = {
  source_figure?: { src: string; caption: string; alt: string };
  source_figures?: Array<{ src: string; caption: string; alt: string }>;
  title: string;
  key_understanding: string;
  explanation: string;
  sources: SourceSpan[];
  citations?: Array<{ anchor: string; sources: SourceSpan[] }>;
  cases?: Array<{ title: string; description: string; illustrates: string; sources: SourceSpan[] }>;
};

export type ReadingRecord = {
  protocol: string;
  reading_route: string;
  units: Array<{ title: string; content_kind: string; explanation: string; steps: string[];
    examples: string[]; limitations: string[]; gaps: string[]; sources: SourceSpan[] }>;
  conclusion_sources: SourceSpan[];
  gaps: string[];
  support_review: string;
  teaching?: {
    chapter_summary: string;
    topics: ReadingTopic[];
    takeaway?: string;
    open_question?: {
      question: string;
      attribution: "author_question" | "ai_extension";
      sources: SourceSpan[];
    } | null;
  };
};
export type BookSynthesis = {
  reading_guide: string;
  development_route: string;
  themes: Array<{ text: string; evidence_refs: string[]; sources: SourceSpan[] }>;
  relations: Array<{ text: string; evidence_refs: string[]; sources: SourceSpan[] }>;
  open_questions: string[];
};

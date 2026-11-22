import type { ContentType, CoreIdea, SourceFormat, SourceSpan } from "../lib/types";
import { genreFieldEntries } from "../lib/genre-fields";
import { ArgumentChain } from "./ArgumentChain";
import { SourceEvidence } from "./SourceEvidence";

const TYPE_LABELS: Record<ContentType, string> = {
  book_claim: "原书观点",
  book_example: "书中案例",
  ai_explanation: "AI 解析",
  ai_inference: "AI 推断",
  ai_synthesis: "AI 推导",
};

function groupSourcesByChapter(sources: SourceSpan[]): Array<{ title: string; sources: SourceSpan[] }> {
  const groups: Array<{ key: string; title: string; sources: SourceSpan[] }> = [];
  for (const source of sources) {
    const key = String(source.source_chapter_id ?? "current");
    const title = source.source_chapter_title || "本节原文";
    const group = groups.find((item) => item.key === key);
    if (group) group.sources.push(source);
    else groups.push({ key, title, sources: [source] });
  }
  return groups.map(({ title, sources: groupedSources }) => ({ title, sources: groupedSources }));
}

export function CoreIdeaSection({
  idea,
  number,
  sourceFormat = "pdf",
  genre,
  onOpenSource,
}: {
  idea: CoreIdea;
  number: number;
  sourceFormat?: SourceFormat;
  genre?: string | null;
  onOpenSource: (source: SourceSpan) => void;
}) {
  const hasPrimary = Boolean(idea.conclusion || idea.explanation || idea.importance);
  // Older analyses only stored a combined `caveats` list, so fall back to it
  // rather than showing an empty boundaries section for previously read books.
  const authorCaveats = idea.author_caveats?.length ? idea.author_caveats : idea.caveats;
  const aiCaveats = idea.ai_caveats ?? [];
  const warrant = idea.warrant ?? "";
  const genreFields = genreFieldEntries(idea.genre_fields, genre);
  const sourceGroups = groupSourcesByChapter(idea.sources);
  const hasSecondary =
    idea.reasoning_steps.length > 0 ||
    idea.examples.length > 0 ||
    authorCaveats.length > 0 ||
    aiCaveats.length > 0 ||
    warrant.length > 0 ||
    genreFields.length > 0 ||
    idea.relations.length > 0;
  return (
    <article className="idea-unit" id={`topic-${number}`} tabIndex={-1}>
      <div className="idea-interpret">
        <div className="idea-topline">
          <span className="idea-index">{String(number).padStart(2, "0")}</span>
          <span className={`content-type type-${idea.content_type}`}>{TYPE_LABELS[idea.content_type]}</span>
        </div>
        <h3 className="idea-heading">{idea.title}</h3>
        {hasPrimary && (
          <div className="idea-primary">
            {idea.conclusion && <p className="idea-lead">{idea.conclusion}</p>}
            {idea.explanation && <p className="idea-explain">{idea.explanation}</p>}
            {idea.importance && <p className="idea-why">意义：{idea.importance}</p>}
          </div>
        )}
        {hasSecondary && (
          <details className="idea-more">
            <summary><span className="idea-more-toggle">论证 · 案例 · 边界</span></summary>
            <div className="idea-more-body">
              {idea.reasoning_steps.length > 0 && <section><h4>作者如何论证</h4><ArgumentChain steps={idea.reasoning_steps} /></section>}
              {genreFields.length > 0 && (
                <section className="idea-genre-fields">
                  {genreFields.map((entry) => (
                    <div key={entry.key} className="genre-field">
                      <h4>{entry.label}</h4>
                      {Array.isArray(entry.value) ? (
                        <ol>{entry.value.map((item) => <li key={item}>{item}</li>)}</ol>
                      ) : (
                        <p>{entry.value}</p>
                      )}
                    </div>
                  ))}
                </section>
              )}
              {warrant && (
                <section className="idea-warrant">
                  <h4>这个论证依赖的隐含前提</h4>
                  <p>{warrant}</p>
                  <p className="idea-attribution">由 AI 识别，作者未明说</p>
                </section>
              )}
              {idea.examples.length > 0 && <section><h4>书中案例</h4><ul>{idea.examples.map((item) => <li key={item}>{item}</li>)}</ul></section>}
              {authorCaveats.length > 0 && (
                <section className="caveat">
                  <h4>作者说明的边界</h4>
                  <ul>{authorCaveats.map((item) => <li key={item}>{item}</li>)}</ul>
                </section>
              )}
              {aiCaveats.length > 0 && (
                <section className="caveat caveat-ai">
                  <h4>需要注意的限制</h4>
                  <ul>{aiCaveats.map((item) => <li key={item}>{item}</li>)}</ul>
                  <p className="idea-attribution">由 AI 补充，作者未提到</p>
                </section>
              )}
              {idea.relations.length > 0 && <section><h4>与其他观点的关系</h4><ul>{idea.relations.map((item) => <li key={item}>{item}</li>)}</ul></section>}
            </div>
          </details>
        )}
      </div>
      {idea.sources.length > 0 && (
        <div className="idea-sources">
          {sourceGroups.map((group) => (
            <section className="idea-source-group" key={group.title}>
              {sourceGroups.length > 1 && <h4>{group.title}</h4>}
              {group.sources.map((source) => <SourceEvidence key={source.id} source={source} sourceFormat={sourceFormat} onOpenSource={onOpenSource} />)}
            </section>
          ))}
        </div>
      )}
    </article>
  );
}

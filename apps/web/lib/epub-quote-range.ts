type TextOffset = {
  node: Text;
  offset: number;
};

type NormalizedDocument = {
  text: string;
  offsets: TextOffset[];
};

type TextMatch = {
  start: number;
  end: number;
};

function normalizeText(value: string) {
  return value.replace(/\s+/g, "");
}

function buildNormalizedDocument(root: HTMLElement): NormalizedDocument {
  const offsets: TextOffset[] = [];
  let text = "";
  const walker = root.ownerDocument.createTreeWalker(root, NodeFilter.SHOW_TEXT);
  let currentNode = walker.nextNode();

  while (currentNode) {
    const textNode = currentNode as Text;
    for (let offset = 0; offset < textNode.data.length; offset += 1) {
      const character = textNode.data[offset];
      if (!/\s/.test(character)) {
        text += character;
        offsets.push({ node: textNode, offset });
      }
    }
    currentNode = walker.nextNode();
  }

  return { text, offsets };
}

function findNonOverlappingMatches(source: string, needle: string): TextMatch[] {
  const matches: TextMatch[] = [];
  let start = source.indexOf(needle);

  while (start !== -1) {
    matches.push({ start, end: start + needle.length });
    start = source.indexOf(needle, start + needle.length);
  }

  return matches;
}

export function findEpubQuoteRange(
  sourceDocument: Document,
  quote: string,
  surroundingText: string | null = null,
): Range | null {
  return findTextQuoteRange(sourceDocument.body, quote, surroundingText);
}

export function findTextQuoteRange(
  root: HTMLElement,
  quote: string,
  surroundingText: string | null = null,
): Range | null {
  const normalizedQuote = normalizeText(quote);
  if (!normalizedQuote) return null;

  const normalizedDocument = buildNormalizedDocument(root);
  let matches = findNonOverlappingMatches(normalizedDocument.text, normalizedQuote);

  if (matches.length > 1 && surroundingText) {
    const normalizedSurroundingText = normalizeText(surroundingText);
    const surroundingMatches = normalizedSurroundingText
      ? findNonOverlappingMatches(normalizedDocument.text, normalizedSurroundingText)
      : [];
    matches = matches.filter((quoteMatch) => (
      surroundingMatches.filter((surroundingMatch) => (
        surroundingMatch.start <= quoteMatch.start && quoteMatch.end <= surroundingMatch.end
      )).length === 1
    ));
  }

  if (matches.length !== 1) return null;

  const match = matches[0];
  const start = normalizedDocument.offsets[match.start];
  const end = normalizedDocument.offsets[match.end - 1];
  if (!start || !end) {
    return null;
  }

  const range = root.ownerDocument.createRange();
  range.setStart(start.node, start.offset);
  range.setEnd(end.node, end.offset + 1);
  return range;
}

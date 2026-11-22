export type EpubPassage = {
  cfi: string;
  quote: string;
  before: string;
  after: string;
};

export type SourceChatTurn = {
  question: string;
  answer: string;
  model?: string;
  thinking?: string;
};

export type PassageAnnotation = {
  passage: EpubPassage;
  note?: string;
  turns?: SourceChatTurn[];
};

type Annotations = Record<string, PassageAnnotation>;

function storageKey(bookId: string) {
  return `bookthinking:epub-annotations:v1:${bookId}`;
}

export function loadEpubAnnotations(bookId: string): Annotations {
  try {
    const saved: unknown = JSON.parse(window.localStorage.getItem(storageKey(bookId)) || "{}");
    if (!saved || typeof saved !== "object" || Array.isArray(saved)) return {};
    return saved as Annotations;
  } catch {
    return {};
  }
}

export function saveEpubAnnotation(bookId: string, passage: EpubPassage, update: (current?: PassageAnnotation) => Omit<PassageAnnotation, "passage">) {
  const annotations = loadEpubAnnotations(bookId);
  const current = annotations[passage.cfi];
  const next = { ...annotations, [passage.cfi]: { ...current, passage, ...update(current) } };
  window.localStorage.setItem(storageKey(bookId), JSON.stringify(next));
  return next;
}

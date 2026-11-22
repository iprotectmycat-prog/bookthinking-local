export type EpubReaderPreferences = {
  flow: "paginated" | "scrolled";
  fontScale: 80 | 90 | 100 | 110 | 120 | 130 | 140;
  lineHeight: 1.4 | 1.55 | 1.7 | 1.85 | 2;
  pageMargin: 16 | 24 | 32 | 40 | 48;
  theme: "system" | "light" | "dark";
};

export type EpubReaderStateV1 = {
  version: 1;
  progressCfi: string | null;
  preferences: EpubReaderPreferences;
};

const STORAGE_PREFIX = "bookthinking:epub-reader:v1:";

const defaultPreferences: EpubReaderPreferences = {
  flow: "paginated",
  fontScale: 100,
  lineHeight: 1.7,
  pageMargin: 24,
  theme: "system",
};

const allowedPreferences = {
  flow: ["paginated", "scrolled"],
  fontScale: [80, 90, 100, 110, 120, 130, 140],
  lineHeight: [1.4, 1.55, 1.7, 1.85, 2],
  pageMargin: [16, 24, 32, 40, 48],
  theme: ["system", "light", "dark"],
} as const;

function storageKey(bookId: string) {
  return `${STORAGE_PREFIX}${bookId}`;
}

function includes<T>(values: readonly T[], value: unknown): value is T {
  return values.includes(value as T);
}

export function defaultReaderState(): EpubReaderStateV1 {
  return { version: 1, progressCfi: null, preferences: { ...defaultPreferences } };
}

export function loadReaderState(bookId: string): EpubReaderStateV1 {
  if (typeof window === "undefined") return defaultReaderState();

  try {
    const saved: unknown = JSON.parse(window.localStorage.getItem(storageKey(bookId)) || "null");
    if (!saved || typeof saved !== "object") return defaultReaderState();

    const state = saved as Partial<EpubReaderStateV1>;
    if (state.version !== 1 || !state.preferences || typeof state.preferences !== "object") {
      return defaultReaderState();
    }

    const preferences = state.preferences as Partial<EpubReaderPreferences>;
    return {
      version: 1,
      progressCfi: typeof state.progressCfi === "string" ? state.progressCfi : null,
      preferences: {
        flow: includes(allowedPreferences.flow, preferences.flow) ? preferences.flow : defaultPreferences.flow,
        fontScale: includes(allowedPreferences.fontScale, preferences.fontScale) ? preferences.fontScale : defaultPreferences.fontScale,
        lineHeight: includes(allowedPreferences.lineHeight, preferences.lineHeight) ? preferences.lineHeight : defaultPreferences.lineHeight,
        pageMargin: includes(allowedPreferences.pageMargin, preferences.pageMargin) ? preferences.pageMargin : defaultPreferences.pageMargin,
        theme: includes(allowedPreferences.theme, preferences.theme) ? preferences.theme : defaultPreferences.theme,
      },
    };
  } catch {
    return defaultReaderState();
  }
}

function saveReaderState(bookId: string, state: EpubReaderStateV1) {
  if (typeof window === "undefined") return;
  window.localStorage.setItem(storageKey(bookId), JSON.stringify(state));
}

export function saveReaderPreferences(bookId: string, preferences: EpubReaderPreferences) {
  const state = loadReaderState(bookId);
  saveReaderState(bookId, { ...state, preferences });
}

export function saveReaderProgress(bookId: string, progressCfi: string) {
  const state = loadReaderState(bookId);
  saveReaderState(bookId, { ...state, progressCfi });
}

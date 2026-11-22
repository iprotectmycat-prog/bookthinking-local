import type Section from "epubjs/types/section";
import type Spine from "epubjs/types/spine";

import type { EpubLocator } from "./types";

export function parseEpubSourceLocator(
  value: string | null | undefined,
  legacyPosition: number,
): EpubLocator {
  const [href = "", fragment = ""] = (value || "").split("#", 2);
  return {
    href: href || null,
    fragment: fragment || null,
    cfi: null,
    spineIndex:
      Number.isInteger(legacyPosition) && legacyPosition > 0
        ? legacyPosition - 1
        : null,
  };
}

export function epubDisplayTarget(locator: EpubLocator): string | number {
  if (locator.href) {
    return locator.fragment
      ? `${locator.href}#${locator.fragment}`
      : locator.href;
  }
  if (locator.cfi) return locator.cfi;
  return locator.spineIndex ?? 0;
}

/**
 * An imported locator is relative to the EPUB archive, while epub.js resolves
 * hrefs relative to the package document. Use the saved position while the
 * rendition opens, then resolve the archive path against the EPUB spine.
 */
export function epubInitialDisplayTarget(locator: EpubLocator): string | number {
  return locator.spineIndex ?? epubDisplayTarget(locator);
}

export function epubDisplayTargetForSpine(
  locator: EpubLocator,
  spineHref: string | null | undefined,
): string | number {
  if (spineHref) {
    return locator.fragment ? `${spineHref}#${locator.fragment}` : spineHref;
  }
  return epubDisplayTarget(locator);
}

function normalizeArchivePath(path: string) {
  const relativePath = path.replace(/^\/+/, "");
  try {
    return decodeURI(relativePath);
  } catch {
    return relativePath;
  }
}

export function epubResolvedDisplayTarget(locator: EpubLocator, spine: Pick<Spine, "each" | "get">) {
  const sections: Section[] = [];
  if (locator.href) {
    spine.each((section: Section) => sections.push(section));
    const archivePath = normalizeArchivePath(locator.href);
    const section = sections.find(({ url }) => normalizeArchivePath(url) === archivePath)
      ?? sections.find(({ href }) => normalizeArchivePath(href) === archivePath);
    if (section) return epubDisplayTargetForSpine(locator, section.href);
  }
  const legacySection = locator.spineIndex === null ? undefined : spine.get(locator.spineIndex);
  return epubDisplayTargetForSpine(locator, legacySection?.href);
}

export function epubLocatorSearchParams(locator: EpubLocator): URLSearchParams {
  const params = new URLSearchParams();
  if (locator.href) params.set("href", locator.href);
  if (locator.fragment) params.set("fragment", locator.fragment);
  if (locator.spineIndex !== null) {
    params.set("spine", String(locator.spineIndex + 1));
  }
  return params;
}

import type { SourceReaderTarget } from "./types";

export function sourceReaderPresentation(target: SourceReaderTarget) {
  if (target.format === "epub") {
    return {
      location: `章节片段 ${(target.locator.spineIndex ?? 0) + 1}`,
      description: "这里显示你上传的原始 EPUB，证据位置按书内章节片段顺序标记。",
      openLabel: "在原书中阅读",
      embedded: true,
    };
  }
  return {
    location: `第 ${target.page} 页`,
    description: "这里显示你上传的原始 PDF，并已定位到该证据所在页。",
    openLabel: "打开原始 PDF",
    embedded: true,
  };
}

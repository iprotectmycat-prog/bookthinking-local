import type { SourceFormat } from "./types";

export type BookDisplay = {
  title: string;
  metadata: string;
};

const EXTENSIONS = /\.(pdf|epub|kepub|kepub\.epub)$/i;

/** 电子书站点与工具留下的下载后缀，对读者无意义。 */
const DOWNLOAD_SUFFIXES = [
  /\s*\(z-lib(rary)?(\.org)?\)\s*$/i,
  /\s*\(zlibrary\)\s*$/i,
  /\s*\(libgen(\.\w+)?\)\s*$/i,
  /\s*\(annas?-archive\)\s*$/i,
  /\s*[-_]\s*(mobi|epub|pdf|azw3)$/i,
];

/**
 * 营销性副标题：中文书名后常挂一串推荐语，被【】或（）包裹，
 * 或以「：」接一句长宣传。真正的副标题一般较短且不含推荐词。
 */
const MARKETING_MARKERS = /[【\[]|(联袂|倾力|重磅)?推荐|畅销|典藏|修订版说明|随书赠/;

/**
 * 从文件名里推断展示用的书名与副信息。
 *
 * 注意：这是**兜底路径**。EPUB 解析器已能从 `dc:title` / `dc:creator` 读出
 * 干净的书名、副标题与作者，一旦这些字段落库并由 API 透出，就应优先采用
 * 后端数据，这里只服务于 PDF 与缺失元数据的旧记录。
 */
export function getBookDisplay(filename: string, sourceFormat: SourceFormat): BookDisplay {
  let text = filename.replace(EXTENSIONS, "").trim();
  for (const suffix of DOWNLOAD_SUFFIXES) {
    text = text.replace(suffix, "").trim();
  }

  if (/^(btc\s*pdf|bitcoin)/i.test(text)) {
    return { title: "BTC", metadata: sourceFormat.toUpperCase() };
  }

  const author = extractAuthor(text);
  const withoutAuthor = author ? text.slice(0, text.search(/\s+\(/)).trim() : text;
  const title = conciseTitle(withoutAuthor);

  return {
    title,
    metadata: author ? `${author} · ${sourceFormat.toUpperCase()}` : sourceFormat.toUpperCase(),
  };
}

/** 文件名里的作者通常是末尾第一个括号组，如「(兰小欢,非墨盟)」。 */
function extractAuthor(value: string): string | null {
  const start = value.search(/\s+\(/);
  if (start < 0) return null;
  const raw = value.slice(start).trim();
  // 多个括号组时只取第一组，后面往往是下载站标记。
  const first = raw.match(/^\(([^)]*)\)/);
  const author = (first ? first[1] : raw.replace(/^\(|\)$/g, "")).trim();
  return author || null;
}

/**
 * 砍掉营销后缀，保留正式书名。
 *
 * 原实现把「 中国政府与经济发展」这一具体副标题硬编码在代码里，只能服务
 * 《置身事内》一本书。改为按分隔符与营销特征判断：先在【】等标记处截断，
 * 再把「书名 + 空格 + 长副标题」的形式收敛到书名。
 */
function conciseTitle(value: string): string {
  const beforeMarketing = value.split(/[【\[（]/u, 1)[0].trim();
  const beforeColon = beforeMarketing.split(/[:：]/u, 1)[0].trim() || beforeMarketing;

  // 「置身事内 中国政府与经济发展」：空格分隔且后段明显更长时，后段是副标题。
  const spaceSplit = beforeColon.match(/^(\S{2,10})\s+(\S{6,})$/u);
  if (spaceSplit && !/^[A-Za-z]/.test(beforeColon)) {
    return spaceSplit[1];
  }

  return beforeColon || value.trim() || "未命名书籍";
}

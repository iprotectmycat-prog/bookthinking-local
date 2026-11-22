#!/usr/bin/env node

const fs = require("fs");
const path = require("path");
const { JSDOM } = require("jsdom");

const dom = new JSDOM("<!doctype html><html><body></body></html>", { url: "http://localhost/" });
Object.assign(global, {
  window: dom.window,
  document: dom.window.document,
  DOMParser: dom.window.DOMParser,
  XMLSerializer: dom.window.XMLSerializer,
  Node: dom.window.Node,
  Blob: dom.window.Blob,
});
window.URL.createObjectURL ||= () => "blob:epub-structure";
window.URL.revokeObjectURL ||= () => {};
global.URL = window.URL;

const ePub = require("epubjs").default;

function localName(node) {
  return (node.localName || node.nodeName || "").split(":").pop();
}

function elementChildren(node) {
  return Array.from(node.children || []);
}

function descendants(node, name) {
  const results = [];
  for (const child of elementChildren(node)) {
    if (localName(child) === name) results.push(child);
    results.push(...descendants(child, name));
  }
  return results;
}

function tocNav(document) {
  const navigations = descendants(document.documentElement, "nav");
  return navigations.find((node) =>
    Array.from(node.attributes).some((attribute) => localName(attribute) === "type" && attribute.value.split(/\s+/).includes("toc")),
  ) || navigations[0];
}

function collectNavItems(orderedList, depth, parentTitle, entries) {
  for (const item of elementChildren(orderedList).filter((node) => localName(node) === "li")) {
    const anchor = elementChildren(item).find((node) => ["a", "span"].includes(localName(node)) && node.textContent.trim());
    const title = anchor ? anchor.textContent.replace(/\s+/g, " ").trim() : "";
    const href = anchor?.getAttribute("href") || "";
    if (title && href) entries.push({ title, href, depth, parent_title: parentTitle });
    for (const child of elementChildren(item).filter((node) => localName(node) === "ol")) {
      collectNavItems(child, depth + 1, title || parentTitle, entries);
    }
  }
}

function navEntries(xhtml) {
  const document = new JSDOM(xhtml, { contentType: "application/xhtml+xml" }).window.document;
  const navigation = tocNav(document);
  const orderedList = navigation && descendants(navigation, "ol")[0];
  const entries = [];
  if (orderedList) collectNavItems(orderedList, 0, null, entries);
  return entries;
}

function collectNcxPoints(parent, depth, parentTitle, entries) {
  for (const point of elementChildren(parent).filter((node) => localName(node) === "navPoint")) {
    const label = elementChildren(point).find((node) => localName(node) === "navLabel");
    const content = elementChildren(point).find((node) => localName(node) === "content");
    const title = label ? label.textContent.replace(/\s+/g, " ").trim() : "";
    const href = content?.getAttribute("src") || "";
    if (title && href) entries.push({ title, href, depth, parent_title: parentTitle });
    collectNcxPoints(point, depth + 1, title || parentTitle, entries);
  }
}

function ncxEntries(ncx) {
  const document = new JSDOM(ncx, { contentType: "text/xml" }).window.document;
  const navMap = descendants(document.documentElement, "navMap")[0];
  const entries = [];
  if (navMap) collectNcxPoints(navMap, 0, null, entries);
  return entries;
}

async function navigationEntries(book, resolveArchivePath) {
  const sources = [
    [book.packaging.navPath, navEntries, "nav"],
    [book.packaging.ncxPath, ncxEntries, "ncx"],
  ];
  const entries = [];
  for (const [sourcePath, parse, source] of sources) {
    if (!sourcePath) continue;
    const resolvedPath = resolveArchivePath(sourcePath);
    const text = await book.archive.getText(book.resolve(sourcePath));
    entries.push(...parse(text).map((entry) => ({ ...entry, source_path: resolvedPath, source })));
  }
  return entries;
}

async function extract(epubPath) {
  if (!path.isAbsolute(epubPath)) {
    throw new Error("EPUB path must be absolute");
  }
  const contents = fs.readFileSync(epubPath);
  const data = contents.buffer.slice(contents.byteOffset, contents.byteOffset + contents.byteLength);
  const book = ePub(data);
  await book.ready;
  const resolveArchivePath = (href) => book.resolve(href).replace(/^\//, "");

  return {
    spine: await Promise.all(book.spine.items.map(async (item) => ({
      path: resolveArchivePath(item.href),
      xhtml: await book.archive.getText(book.resolve(item.href)),
    }))),
    navigation: await navigationEntries(book, resolveArchivePath),
  };
}

let input = "";
process.stdin.setEncoding("utf8");
process.stdin.on("data", (chunk) => { input += chunk; });
process.stdin.on("end", async () => {
  try {
    const result = await extract(input.trim());
    process.stdout.write(JSON.stringify(result));
  } catch (error) {
    process.stderr.write(`${error.stack || error.message}\n`);
    process.exitCode = 1;
  }
});

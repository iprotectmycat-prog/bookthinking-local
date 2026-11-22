#!/usr/bin/env python3
"""Print local EPUB chapter-structure facts for a repair review."""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services.epub_parser import EpubParser  # noqa: E402
from app.services.pypdf_parser import ChapterDraft  # noqa: E402


CHINESE_DIGITS = {"零": 0, "〇": 0, "一": 1, "二": 2, "三": 3, "四": 4, "五": 5, "六": 6, "七": 7, "八": 8, "九": 9}
CHINESE_UNITS = {"十": 10, "百": 100, "千": 1000}
CHINESE_CHAPTER = re.compile(r"^第(?P<number>[一二三四五六七八九十百千零〇\d]+)章")
ENGLISH_CHAPTER = re.compile(r"^Chapter\s+(?P<number>\d+)\b", re.IGNORECASE)


def chapter_number(title: str) -> int | None:
    """Return the publisher-declared chapter number, if this title has one."""
    match = CHINESE_CHAPTER.match(title.strip()) or ENGLISH_CHAPTER.match(title.strip())
    if match is None:
        return None
    raw_number = match.group("number")
    if raw_number.isdecimal():
        return int(raw_number)

    total = 0
    current = 0
    for character in raw_number:
        if character in CHINESE_DIGITS:
            current = CHINESE_DIGITS[character]
            continue
        unit = CHINESE_UNITS.get(character)
        if unit is None:
            return None
        total += (current or 1) * unit
        current = 0
    return total + current


def numbered_chapters(chapters: list[ChapterDraft]) -> list[int]:
    return [
        number
        for chapter in chapters
        if chapter.nav_kind == "chapter" and (number := chapter_number(chapter.title)) is not None
    ]


def chapter_number_diagnostics(numbers: list[int]) -> list[str]:
    duplicates = sorted(number for number in set(numbers) if numbers.count(number) > 1)
    missing = sorted(set(range(1, max(numbers) + 1)).difference(numbers)) if numbers else []
    return [
        *(f"duplicate_numbered_chapter:{number}" for number in duplicates),
        *(f"missing_numbered_chapter:{number}" for number in missing),
    ]


def main() -> int:
    parser = argparse.ArgumentParser(description="Verify local EPUB chapter structure.")
    parser.add_argument("epub", type=Path, help="Path to a local, non-DRM EPUB file")
    args = parser.parse_args()

    parsed = EpubParser().parse_epub(args.epub)
    numbers = numbered_chapters(parsed.chapters)
    diagnostics = [*parsed.diagnostics, *chapter_number_diagnostics(numbers)]
    payload = {
        "numbered_chapters": numbers,
        "titles": [chapter.title for chapter in parsed.chapters],
        "diagnostics": diagnostics,
    }
    print(json.dumps(payload, ensure_ascii=False))
    return 1 if any(diagnostic.startswith(("duplicate_numbered_chapter:", "missing_numbered_chapter:")) for diagnostic in diagnostics) else 0


if __name__ == "__main__":
    raise SystemExit(main())

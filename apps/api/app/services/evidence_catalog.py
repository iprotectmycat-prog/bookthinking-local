"""Deterministic, literal evidence blocks supplied to analysis providers."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any


SOFT_BLOCK_CHARACTERS = 120
HARD_BLOCK_CHARACTERS = 240
DEFAULT_BLOCK_CHARACTERS = SOFT_BLOCK_CHARACTERS
_SENTENCE_BOUNDARY = re.compile(r"(?<=[。！？!?])")
_SEMICOLON_BOUNDARY = re.compile(r"(?<=[；;])")
_CLAUSE_BOUNDARY = re.compile(r"(?<=[，,、])")


@dataclass(frozen=True)
class EvidenceBlock:
    id: str
    chapter_id: int
    chapter_title: str
    page: int
    quote: str
    surrounding_text: str
    paragraph_id: str = ""


@dataclass(frozen=True)
class EvidenceResolution:
    blocks: tuple[EvidenceBlock, ...]
    unknown_ids: list[str]
    duplicate_ids: list[str]
    empty_id_count: int


@dataclass(frozen=True)
class EvidenceCatalogue:
    blocks: tuple[EvidenceBlock, ...]

    def resolve(self, evidence_ids: list[str]) -> EvidenceResolution:
        by_id = {block.id: block for block in self.blocks}
        selected: list[EvidenceBlock] = []
        unknown_ids: list[str] = []
        duplicate_ids: list[str] = []
        empty_id_count = 0
        seen: set[str] = set()
        for evidence_id in evidence_ids:
            normalized = evidence_id.strip()
            if not normalized:
                empty_id_count += 1
                continue
            if normalized in seen:
                duplicate_ids.append(normalized)
                continue
            seen.add(normalized)
            block = by_id.get(normalized)
            if block is None:
                unknown_ids.append(normalized)
                continue
            selected.append(block)
        return EvidenceResolution(
            blocks=tuple(selected),
            unknown_ids=unknown_ids,
            duplicate_ids=duplicate_ids,
            empty_id_count=empty_id_count,
        )


def build_evidence_catalogue(
    chapter: Any,
    *,
    prefix: str,
    max_characters: int = DEFAULT_BLOCK_CHARACTERS,
) -> EvidenceCatalogue:
    """Turn chapter pages into short, literal blocks with stable local IDs."""
    blocks: list[EvidenceBlock] = []
    pages = list(getattr(chapter, "pages", ()) or ())
    if not pages:
        pages = [
            type(
                "FallbackPage",
                (),
                {
                    "page_number": int(getattr(chapter, "source_start_page")),
                    "text": str(getattr(chapter, "text")),
                },
            )()
        ]
    paragraph_index = 0
    for page in pages:
        for paragraph in _paragraphs(str(page.text)):
            paragraph_index += 1
            for quote in _literal_groups(
                paragraph, soft_limit=min(max_characters, SOFT_BLOCK_CHARACTERS)
            ):
                blocks.append(
                    EvidenceBlock(
                        id=f"{prefix}{len(blocks) + 1}",
                        chapter_id=int(chapter.id),
                        chapter_title=str(chapter.title),
                        page=int(page.page_number),
                        quote=quote,
                        surrounding_text=paragraph,
                        paragraph_id=f"{prefix}p{paragraph_index}",
                    )
                )
    return EvidenceCatalogue(blocks=tuple(blocks))


def _paragraphs(text: str) -> list[str]:
    return [paragraph for paragraph in re.split(r"\n\s*\n", text) if paragraph.strip()]


def _literal_groups(paragraph: str, *, soft_limit: int) -> list[str]:
    sentences = [sentence for sentence in _SENTENCE_BOUNDARY.split(paragraph) if sentence]
    return _pack_sentence_groups(sentences, soft_limit=soft_limit)


def _pack_sentence_groups(sentences: list[str], *, soft_limit: int) -> list[str]:
    groups: list[str] = []
    current = ""
    for sentence in sentences:
        if len(sentence) > HARD_BLOCK_CHARACTERS:
            if current:
                groups.append(current)
                current = ""
            groups.extend(_split_oversize(sentence))
            continue
        if current and len(current) + len(sentence) > soft_limit:
            groups.append(current)
            current = sentence
        else:
            current += sentence
    if current:
        groups.append(current)
    return groups


def _split_oversize(text: str) -> list[str]:
    for boundary in (_SEMICOLON_BOUNDARY, _CLAUSE_BOUNDARY):
        pieces = [piece for piece in boundary.split(text) if piece]
        if len(pieces) > 1:
            return _pack_to_hard_limit(pieces)
    return _hard_split(text, HARD_BLOCK_CHARACTERS)


def _pack_to_hard_limit(pieces: list[str]) -> list[str]:
    groups: list[str] = []
    current = ""
    for piece in pieces:
        split_pieces = _split_oversize(piece) if len(piece) > HARD_BLOCK_CHARACTERS else [piece]
        for split_piece in split_pieces:
            if current and len(current) + len(split_piece) > HARD_BLOCK_CHARACTERS:
                groups.append(current)
                current = split_piece
            else:
                current += split_piece
    if current:
        groups.append(current)
    return groups


def _hard_split(text: str, limit: int) -> list[str]:
    return [text[index : index + limit] for index in range(0, len(text), limit)]

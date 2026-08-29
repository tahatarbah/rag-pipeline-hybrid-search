from __future__ import annotations

import re
from dataclasses import asdict, dataclass

from app.config import settings
from app.ingest.loaders import Document

SEPARATORS = ["\n\n", "\n", ". ", " ", ""]
_HEADING = re.compile(r"^(#{1,6}\s+\S.*)$", re.M)


@dataclass
class Chunk:
    id: str
    text: str
    source: str
    path: str
    title: str
    page: int | None
    chunk_index: int

    def metadata(self) -> dict:
        meta = asdict(self)
        meta.pop("text")
        if meta["page"] is None:
            meta.pop("page")
        return meta


def _split_with_separator(text: str, separator: str) -> list[str]:
    if separator == "":
        return list(text)
    parts = text.split(separator)
    return [p for p in parts if p != ""]


def overlap_prefix(prev: str, overlap: int) -> str:
    """Take the tail of the previous chunk, snapped to a word boundary."""
    if overlap <= 0 or not prev:
        return ""
    raw = prev[-overlap:] if len(prev) > overlap else prev
    if len(prev) > overlap:
        left = prev[-overlap - 1]
        start = raw[:1]
        if left.isalnum() and start.isalnum():
            cuts = [i for i in (raw.find(" "), raw.find("\n")) if i >= 0]
            if not cuts:
                return ""
            raw = raw[min(cuts) + 1 :]
    return raw.lstrip()


def recursive_split(
    text: str,
    chunk_size: int,
    overlap: int,
    separators: list[str] | None = None,
) -> list[str]:
    cleaned = text.strip()
    if not cleaned:
        return []
    if len(cleaned) <= chunk_size:
        return [cleaned]

    seps = separators if separators is not None else SEPARATORS
    separator = seps[0] if seps else ""
    rest = seps[1:] if len(seps) > 1 else [""]
    pieces = _split_with_separator(cleaned, separator)

    merged: list[str] = []
    current = ""
    joiner = separator
    for piece in pieces:
        candidate = piece if not current else f"{current}{joiner}{piece}"
        if len(candidate) <= chunk_size:
            current = candidate
            continue
        if current:
            merged.append(current)
        if len(piece) > chunk_size:
            merged.extend(recursive_split(piece, chunk_size, overlap, rest))
            current = ""
        else:
            current = piece
    if current:
        merged.append(current)

    if overlap <= 0 or len(merged) <= 1:
        return [m.strip() for m in merged if m.strip()]

    overlapped: list[str] = []
    for i, chunk in enumerate(merged):
        if i == 0:
            overlapped.append(chunk)
            continue
        prev = merged[i - 1]
        prefix = overlap_prefix(prev, overlap)
        if prefix and not chunk.startswith(prefix):
            combined = f"{prefix}{joiner}{chunk}" if joiner and not prefix.endswith(joiner) else f"{prefix}{chunk}"
        else:
            combined = chunk
        overlapped.append(
            combined[: chunk_size + overlap] if len(combined) > chunk_size + overlap else combined
        )
    return [m.strip() for m in overlapped if m.strip()]


def attach_section_headings(parts: list[str]) -> list[str]:
    """Prefix later chunks with the last markdown heading so IDs survive splits."""
    last = ""
    out: list[str] = []
    for part in parts:
        headings = [match.strip() for match in _HEADING.findall(part)]
        if last and last not in part:
            part = f"{last}\n\n{part}"
        out.append(part)
        if headings:
            last = headings[-1]
    return out


def chunk_documents(
    documents: list[Document],
    chunk_size: int | None = None,
    overlap: int | None = None,
) -> list[Chunk]:
    size = chunk_size if chunk_size is not None else settings.chunk_size
    ov = overlap if overlap is not None else settings.chunk_overlap
    chunks: list[Chunk] = []

    for doc in documents:
        parts = attach_section_headings(recursive_split(doc.text, size, ov))
        rel = str(doc.path)
        for i, part in enumerate(parts):
            page_bit = f"p{doc.page}" if doc.page is not None else "p0"
            chunk_id = f"{doc.source}::{page_bit}::{i}"
            chunks.append(
                Chunk(
                    id=chunk_id,
                    text=part,
                    source=doc.source,
                    path=rel,
                    title=doc.title,
                    page=doc.page,
                    chunk_index=i,
                )
            )
    return chunks

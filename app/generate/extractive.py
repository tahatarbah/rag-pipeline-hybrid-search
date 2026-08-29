from __future__ import annotations

import re

from app.retrieve.embedder import normalize_search_text

_TOKEN = re.compile(r"[a-z0-9]+(?:-[a-z0-9]+)*", re.I)
_SENTENCE = re.compile(r"(?<=[.!?])\s+|\n+")
_STOP = {
    "a",
    "an",
    "and",
    "are",
    "at",
    "be",
    "do",
    "for",
    "from",
    "how",
    "in",
    "is",
    "many",
    "of",
    "on",
    "or",
    "the",
    "to",
    "what",
    "who",
}


def _tokens(text: str) -> set[str]:
    return {m.group(0).lower() for m in _TOKEN.finditer(normalize_search_text(text))}


def _sentences(text: str) -> list[str]:
    parts = [p.strip() for p in _SENTENCE.split(text) if p and p.strip()]
    return [p for p in parts if len(p) > 20]


def _is_fragment(sentence: str) -> bool:
    stripped = sentence.lstrip("#*- ").strip()
    if not stripped:
        return True
    first = stripped[0]
    return first.islower() or first in ",;:"


def extractive_answer(question: str, sources: list[dict], max_sentences: int = 3) -> str:
    if not sources:
        return "No indexed passages matched that question."

    q_tokens = _tokens(question)
    q_content = q_tokens - _STOP
    if not q_content:
        q_content = q_tokens

    scored: list[tuple[int, int, int, int, str, str]] = []
    for src_i, src in enumerate(sources):
        filename = src.get("source") or "document"
        for sentence in _sentences(src.get("text") or ""):
            overlap = len(q_content & _tokens(sentence))
            if overlap == 0:
                continue
            fragment_penalty = 1 if _is_fragment(sentence) else 0
            scored.append((overlap, -fragment_penalty, -src_i, len(sentence), sentence, filename))

    if not scored:
        top = sources[0]
        snippet = " ".join((top.get("text") or "").split())[:420]
        return f"{snippet} [{top.get('source')}]"

    scored.sort(key=lambda row: (row[0], row[1], row[2], row[3]), reverse=True)
    has_complete = any(not _is_fragment(row[4]) for row in scored)
    seen: set[str] = set()
    lines: list[str] = []
    for _, __, ___, ____, sentence, filename in scored:
        if has_complete and _is_fragment(sentence):
            continue
        key = sentence.lower()
        if key in seen:
            continue
        seen.add(key)
        lines.append(f"{sentence} [{filename}]")
        if len(lines) >= max_sentences:
            break
    return "\n\n".join(lines)


def extractive_chunks(question: str, sources: list[dict], max_sentences: int = 3):
    text = extractive_answer(question, sources, max_sentences=max_sentences)
    parts = [p for p in text.split("\n\n") if p]
    if not parts:
        yield text
        return
    for i, part in enumerate(parts):
        yield part + ("\n\n" if i < len(parts) - 1 else "")

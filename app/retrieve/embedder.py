from __future__ import annotations

import hashlib
import re

import numpy as np

from app.config import settings

_TOKEN = re.compile(r"[a-z0-9]+(?:-[a-z0-9]+)*", re.I)
_SOC2 = re.compile(r"\bsoc[\s-]*2\b", re.I)
_STOP = frozenset(
    {
        "a",
        "an",
        "and",
        "are",
        "at",
        "be",
        "can",
        "do",
        "for",
        "from",
        "get",
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
)
DIM = 384


def normalize_search_text(text: str) -> str:
    """Treat SOC2 / SOC-2 / SOC 2 as the same identifier for dense and BM25."""
    return _SOC2.sub("soc 2 soc2", text)


def uses_ollama_embeddings() -> bool:
    model = settings.embedding_model.lower()
    return model not in {"hash", "local", "hashed", "all-minilm-l6-v2", "onnx"} and "minilm" not in model


def _content_tokens(text: str) -> list[str]:
    raw = _TOKEN.findall(normalize_search_text(text).lower())
    kept = [tok for tok in raw if tok not in _STOP and not tok.isdigit()]
    if not kept:
        kept = [tok for tok in raw if tok not in _STOP] or raw
    tokens: list[str] = []
    for tok in kept:
        tokens.append(tok)
        if "-" in tok:
            head = tok.split("-", 1)[0]
            if head and not head.isdigit() and head not in _STOP:
                tokens.append(head)
    return tokens


def _hash_embed(text: str) -> list[float]:
    vec = np.zeros(DIM, dtype=np.float32)
    for tok in _content_tokens(text):
        digest = hashlib.md5(tok.encode("utf-8")).digest()
        idx = int.from_bytes(digest[:4], "little") % DIM
        sign = 1.0 if digest[4] % 2 == 0 else -1.0
        vec[idx] += sign
    norm = float(np.linalg.norm(vec))
    if norm:
        vec /= norm
    return vec.tolist()


def embed_documents(texts: list[str], batch_size: int = 32) -> list[list[float]]:
    if uses_ollama_embeddings():
        try:
            return [_ollama_embed(t) for t in texts]
        except Exception:
            pass
    return [_hash_embed(t) for t in texts]


def embed_query(text: str) -> list[float]:
    if uses_ollama_embeddings():
        try:
            return _ollama_embed(text)
        except Exception:
            pass
    return _hash_embed(text)


def _ollama_embed(text: str) -> list[float]:
    import httpx

    url = f"{settings.ollama_host.rstrip('/')}/api/embeddings"
    response = httpx.post(
        url,
        json={"model": settings.embedding_model, "prompt": text},
        timeout=60.0,
    )
    response.raise_for_status()
    vec = response.json().get("embedding") or []
    if not vec:
        raise RuntimeError("empty embedding")
    arr = np.asarray(vec, dtype=np.float32)
    norm = float(np.linalg.norm(arr))
    if norm:
        arr /= norm
    return arr.tolist()

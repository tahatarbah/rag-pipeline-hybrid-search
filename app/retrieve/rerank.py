from __future__ import annotations

from app.config import settings


def rerank(query: str, results: list[dict], top_k: int) -> list[dict]:
    if not results or not settings.rerank_enabled:
        return results[:top_k]
    if len(results) == 1:
        return results[:top_k]
    try:
        from sentence_transformers import CrossEncoder
    except ImportError:
        return results[:top_k]

    model = CrossEncoder(settings.rerank_model)
    pairs = [(query, item["text"]) for item in results]
    scores = model.predict(pairs)
    ranked = sorted(
        zip(results, scores, strict=True),
        key=lambda pair: float(pair[1]),
        reverse=True,
    )
    out: list[dict] = []
    for item, score in ranked[:top_k]:
        enriched = dict(item)
        enriched["rerank_score"] = float(score)
        out.append(enriched)
    return out

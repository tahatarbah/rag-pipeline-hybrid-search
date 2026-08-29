from __future__ import annotations

import json
import os
import re
import threading
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal

from app.config import settings
from app.ingest.chunker import chunk_documents
from app.ingest.loaders import load_documents
from app.retrieve.embedder import normalize_search_text

_ID_RE = re.compile(r"\b[a-z]{2,}(?:-[a-z0-9]+)*-\d+\b", re.I)
_SOC_RE = re.compile(r"\bsoc[\s-]*2\b", re.I)

os.environ.setdefault("ANONYMIZED_TELEMETRY", "False")

SearchMode = Literal["dense", "bm25", "hybrid"]
CHUNKS_FILE = "chunks.json"
META_FILE = "index_meta.json"


def _bm25_index_dir(bm25_dir: Path) -> Path:
    return bm25_dir / "index"


def reciprocal_rank_fusion(
    rank_lists: list[list[str]],
    k: int = 60,
    weights: list[float] | None = None,
) -> dict[str, float]:
    scores: dict[str, float] = defaultdict(float)
    fused_weights = weights or [1.0] * len(rank_lists)
    for ranking, weight in zip(rank_lists, fused_weights, strict=False):
        for rank, doc_id in enumerate(ranking, start=1):
            scores[doc_id] += weight / (k + rank)
    return dict(scores)


def looks_lexical(question: str) -> bool:
    return bool(_ID_RE.search(question) or _SOC_RE.search(question))


def _fusion_weights(question: str) -> list[float]:
    if looks_lexical(question):
        return [0.7, 1.35]
    return [1.15, 0.9]


def _retrieval_text(source: str, title: str, text: str) -> str:
    return f"{source} {title}\n{text}"


def _bm25_query(question: str) -> str:
    boosted = normalize_search_text(question)
    ids = _ID_RE.findall(question)
    if ids:
        boosted = f"{boosted} {' '.join(ids)}"
    return boosted


def diversify_by_source(
    results: list[dict],
    top_k: int,
    max_per_source: int,
) -> list[dict]:
    if max_per_source <= 0 or top_k <= 0:
        return results[:top_k]
    counts: dict[str, int] = defaultdict(int)
    picked: list[dict] = []
    overflow: list[dict] = []
    for item in results:
        source = item.get("source") or ""
        if counts[source] < max_per_source:
            picked.append(item)
            counts[source] += 1
        else:
            overflow.append(item)
        if len(picked) >= top_k:
            return picked
    for item in overflow:
        if len(picked) >= top_k:
            break
        picked.append(item)
    return picked


class HybridIndex:
    def __init__(self, root: Path | None = None) -> None:
        self._lock = threading.Lock()
        self._bm25 = None
        self._chunks: dict[str, dict] = {}
        self._ids: list[str] = []
        self._meta: dict = {}
        self._dense_matrix = None
        if root is None:
            self.docs_dir = settings.docs_dir
            self.bm25_dir = settings.bm25_dir
            self.dense_dir = settings.data_dir / "dense"
        else:
            self.docs_dir = root / "docs"
            self.bm25_dir = root / "bm25"
            self.dense_dir = root / "dense"

    @property
    def chunk_count(self) -> int:
        if self._ids:
            return len(self._ids)
        chunks_path = self.bm25_dir / CHUNKS_FILE
        if chunks_path.exists():
            payload = json.loads(chunks_path.read_text(encoding="utf-8"))
            return len(payload.get("ids", []))
        return 0

    @property
    def indexed_files(self) -> list[str]:
        self._ensure_chunks_loaded()
        return sorted({c["source"] for c in self._chunks.values()})

    def _ensure_chunks_loaded(self) -> None:
        if self._chunks:
            return
        chunks_path = self.bm25_dir / CHUNKS_FILE
        if not chunks_path.exists():
            return
        payload = json.loads(chunks_path.read_text(encoding="utf-8"))
        self._ids = payload.get("ids", [])
        self._chunks = {item["id"]: item for item in payload.get("chunks", [])}

    def _load_bm25(self):
        if self._bm25 is not None:
            return self._bm25
        index_path = _bm25_index_dir(self.bm25_dir)
        if not index_path.exists() or not any(index_path.iterdir()):
            return None
        try:
            import bm25s

            self._bm25 = bm25s.BM25.load(str(index_path), load_corpus=False)
            return self._bm25
        except Exception:
            return None

    def _load_dense(self):
        path = self.dense_dir / "embeddings.npy"
        if not path.exists():
            return None
        import numpy as np

        return np.load(path)

    def ingest(self, docs_dir: Path | None = None) -> dict:
        from app.retrieve.embedder import embed_documents

        with self._lock:
            documents = load_documents(docs_dir or self.docs_dir)
            chunks = chunk_documents(documents)
            if not chunks:
                raise ValueError("No documents found to ingest.")

            ids = [c.id for c in chunks]
            texts = [_retrieval_text(c.source, c.title, c.text) for c in chunks]

            embeddings = embed_documents(texts)
            import numpy as np

            dense_dir = self.dense_dir
            dense_dir.mkdir(parents=True, exist_ok=True)
            matrix = np.asarray(embeddings, dtype=np.float32)
            np.save(dense_dir / "embeddings.npy", matrix)
            self._dense_matrix = matrix

            import bm25s

            self.bm25_dir.mkdir(parents=True, exist_ok=True)
            index_dir = _bm25_index_dir(self.bm25_dir)
            index_dir.mkdir(parents=True, exist_ok=True)
            tokens = bm25s.tokenize(
                [normalize_search_text(t) for t in texts],
                stopwords="en",
                show_progress=False,
            )
            retriever = bm25s.BM25()
            retriever.index(tokens, show_progress=False)
            retriever.save(str(index_dir))

            chunk_payload = {
                "ids": ids,
                "chunks": [
                    {
                        "id": c.id,
                        "text": c.text,
                        "source": c.source,
                        "path": c.path,
                        "title": c.title,
                        "page": c.page,
                        "chunk_index": c.chunk_index,
                    }
                    for c in chunks
                ],
            }
            (self.bm25_dir / CHUNKS_FILE).write_text(
                json.dumps(chunk_payload, indent=2),
                encoding="utf-8",
            )

            sources = sorted({c.source for c in chunks})
            self._meta = {
                "ingested_at": datetime.now(timezone.utc).isoformat(),
                "chunk_count": len(chunks),
                "document_count": len(documents),
                "files": sources,
                "embedding_model": settings.embedding_model,
            }
            (self.bm25_dir / META_FILE).write_text(
                json.dumps(self._meta, indent=2),
                encoding="utf-8",
            )

            self._bm25 = retriever
            self._ids = ids
            self._chunks = {item["id"]: item for item in chunk_payload["chunks"]}
            return self._meta

    def query(
        self,
        question: str,
        mode: SearchMode = "hybrid",
        top_k: int | None = None,
        retrieve_k: int | None = None,
    ) -> list[dict]:
        self._ensure_chunks_loaded()
        if not self._chunks:
            raise ValueError("Index is empty. Ingest documents first.")

        k_final = top_k or settings.top_k
        k_ret = retrieve_k or settings.retrieve_k
        k_ret = max(k_ret, k_final)

        dense_ranking: list[str] = []
        bm25_ranking: list[str] = []
        dense_scores: dict[str, float] = {}
        bm25_scores: dict[str, float] = {}

        if mode in {"dense", "hybrid"}:
            dense_ranking, dense_scores = self._dense_search(question, k_ret)
        if mode in {"bm25", "hybrid"}:
            bm25_ranking, bm25_scores = self._bm25_search(question, k_ret)

        if mode == "dense":
            ordered_ids = dense_ranking
            fused: dict[str, float] = {i: dense_scores.get(i, 0.0) for i in dense_ranking}
        elif mode == "bm25":
            ordered_ids = bm25_ranking
            fused = {i: bm25_scores.get(i, 0.0) for i in bm25_ranking}
        else:
            fused = reciprocal_rank_fusion(
                [dense_ranking, bm25_ranking],
                k=settings.rrf_k,
                weights=_fusion_weights(question),
            )
            ordered_ids = sorted(fused, key=lambda doc_id: fused[doc_id], reverse=True)

        dense_rank = {doc_id: i for i, doc_id in enumerate(dense_ranking, start=1)}
        bm25_rank = {doc_id: i for i, doc_id in enumerate(bm25_ranking, start=1)}

        fused_window = ordered_ids[: max(k_ret, k_final)]
        results: list[dict] = []
        for doc_id in fused_window:
            chunk = self._chunks.get(doc_id)
            if not chunk:
                continue
            item = dict(chunk)
            item["dense_rank"] = dense_rank.get(doc_id)
            item["bm25_rank"] = bm25_rank.get(doc_id)
            item["dense_score"] = dense_scores.get(doc_id)
            item["bm25_score"] = bm25_scores.get(doc_id)
            item["fused_score"] = fused.get(doc_id)
            results.append(item)

        from app.retrieve.rerank import rerank

        diversified = diversify_by_source(
            results,
            k_final,
            settings.max_chunks_per_source,
        )
        return rerank(question, diversified, k_final)

    def _dense_search(self, question: str, k: int) -> tuple[list[str], dict[str, float]]:
        from app.retrieve.embedder import embed_query
        import numpy as np

        matrix = getattr(self, "_dense_matrix", None)
        if matrix is None:
            matrix = self._load_dense()
            self._dense_matrix = matrix
        if matrix is None or not self._ids:
            self._ensure_chunks_loaded()
            matrix = self._load_dense()
            self._dense_matrix = matrix
        if matrix is None or not len(self._ids):
            return [], {}

        query_vec = np.asarray(embed_query(question), dtype=np.float32)
        scores = matrix @ query_vec
        n = min(k, len(self._ids))
        top = np.argsort(scores)[::-1][:n]
        ranking = [self._ids[int(i)] for i in top]
        score_map = {self._ids[int(i)]: float(scores[int(i)]) for i in top}
        return ranking, score_map

    def _bm25_search(self, question: str, k: int) -> tuple[list[str], dict[str, float]]:
        import bm25s

        retriever = self._load_bm25()
        if retriever is None or not self._ids:
            return [], {}
        n = min(k, len(self._ids))
        tokens = bm25s.tokenize(
            [_bm25_query(question)],
            stopwords="en",
            show_progress=False,
        )
        results, scores = retriever.retrieve(tokens, k=n, show_progress=False)
        ranking: list[str] = []
        score_map: dict[str, float] = {}
        row = results[0]
        score_row = scores[0]
        for idx, score in zip(row, score_row, strict=False):
            index = int(idx)
            if index < 0 or index >= len(self._ids):
                continue
            doc_id = self._ids[index]
            ranking.append(doc_id)
            score_map[doc_id] = float(score)
        return ranking, score_map

    def meta(self) -> dict:
        path = self.bm25_dir / META_FILE
        if path.exists():
            return json.loads(path.read_text(encoding="utf-8"))
        return {
            "chunk_count": self.chunk_count,
            "files": self.indexed_files,
        }


_INDEX: HybridIndex | None = None


def get_index() -> HybridIndex:
    global _INDEX
    if _INDEX is None:
        _INDEX = HybridIndex()
    return _INDEX

from __future__ import annotations

import time
from pathlib import Path
from typing import Literal

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from app.auth import current_user, require_space
from app.config import settings
from app.db import setup_complete
from app.generate.extractive import extractive_answer
from app.generate.ollama_client import (
    OllamaError,
    generate_answer,
    ollama_available,
    ollama_model_ready,
)
from app.ingest.loaders import SUPPORTED_SUFFIXES, safe_filename
from app.retrieve.embedder import uses_ollama_embeddings
from app.retrieve.hybrid import SearchMode, get_index, looks_lexical
from app.spaces import get_space_index

router = APIRouter()

MODES: tuple[SearchMode, ...] = ("dense", "bm25", "hybrid")


class QueryRequest(BaseModel):
    question: str = Field(min_length=1)
    mode: Literal["dense", "bm25", "hybrid"] = "hybrid"
    top_k: int | None = Field(default=None, ge=1, le=20)
    space_id: str | None = None


class SourceOut(BaseModel):
    chunk_id: str
    source: str
    title: str
    page: int | None = None
    text: str
    snippet: str
    dense_rank: int | None = None
    bm25_rank: int | None = None
    fused_score: float | None = None
    dense_score: float | None = None
    bm25_score: float | None = None
    rerank_score: float | None = None


class ModeTop(BaseModel):
    mode: str
    source: str | None = None
    snippet: str | None = None


class QueryResponse(BaseModel):
    answer: str
    sources: list[SourceOut]
    mode: str
    answer_kind: Literal["llm", "extractive"] = "llm"
    generation_error: str | None = None
    top_by_mode: list[ModeTop] = Field(default_factory=list)
    retrieve_ms: float | None = None
    total_ms: float | None = None
    lexical: bool = False


def _snippet(text: str, limit: int = 280) -> str:
    compact = " ".join(text.split())
    if len(compact) <= limit:
        return compact
    return compact[: limit - 1] + "…"


def _serialize_source(item: dict) -> SourceOut:
    return SourceOut(
        chunk_id=item["id"],
        source=item["source"],
        title=item.get("title") or item["source"],
        page=item.get("page"),
        text=item["text"],
        snippet=_snippet(item["text"]),
        dense_rank=item.get("dense_rank"),
        bm25_rank=item.get("bm25_rank"),
        fused_score=item.get("fused_score"),
        dense_score=item.get("dense_score"),
        bm25_score=item.get("bm25_score"),
        rerank_score=item.get("rerank_score"),
    )


def _lab_index(request: Request, space_id: str | None):
    if space_id:
        user = current_user(request)
        if not user:
            raise HTTPException(status_code=401, detail="Sign in required.")
        require_space(user, space_id)
        return get_space_index(space_id)
    if setup_complete():
        raise HTTPException(status_code=400, detail="Choose a space_id for lab queries.")
    return get_index()


def _top_by_mode(index, question: str, active_mode: str, active_hits: list[dict]) -> list[ModeTop]:
    rows: list[ModeTop] = []
    for mode in MODES:
        if mode == active_mode and active_hits:
            hit = active_hits[0]
        else:
            extra = index.query(question, mode=mode, top_k=1)
            hit = extra[0] if extra else None
        rows.append(
            ModeTop(
                mode=mode,
                source=hit["source"] if hit else None,
                snippet=_snippet(hit["text"]) if hit else None,
            )
        )
    return rows


@router.get("/health")
def health() -> dict:
    from app.catalog import ops_health
    from app.db import init_db

    init_db()
    payload = ops_health()
    index = get_index()
    chunk_count = index.chunk_count
    meta = index.meta() if chunk_count else {}
    payload.update(
        {
            "ollama_model_ready": ollama_model_ready(),
            "ollama_model": settings.ollama_model,
            "embeddings_via_ollama": uses_ollama_embeddings(),
            "indexed_chunks": chunk_count,
            "indexed_files": index.indexed_files if chunk_count else [],
            "ingested_at": meta.get("ingested_at"),
            "rerank_enabled": settings.rerank_enabled,
        }
    )
    return payload


@router.get("/docs")
def list_docs(request: Request, space_id: str | None = None) -> dict:
    index = _lab_index(request, space_id)
    meta = index.meta()
    return {
        "files": index.indexed_files,
        "chunk_count": index.chunk_count,
        "ingested_at": meta.get("ingested_at"),
        "docs_dir": str(index.docs_dir),
    }


@router.post("/ingest")
async def ingest(request: Request, space_id: str | None = None) -> dict:
    index = _lab_index(request, space_id)
    saved: list[str] = []
    content_type = request.headers.get("content-type", "")
    if content_type.startswith("multipart/form-data"):
        form = await request.form()
        index.docs_dir.mkdir(parents=True, exist_ok=True)
        for upload in form.getlist("files"):
            filename = getattr(upload, "filename", None)
            if not filename:
                continue
            suffix = Path(filename).suffix.lower()
            if suffix not in SUPPORTED_SUFFIXES:
                raise HTTPException(
                    status_code=400,
                    detail=f"Unsupported file type: {suffix or '(none)'}. Use pdf, docx, md, or txt.",
                )
            dest = index.docs_dir / safe_filename(filename)
            dest.write_bytes(await upload.read())
            saved.append(dest.name)
    try:
        meta = index.ingest()
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except OllamaError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    return {"saved": saved, **meta}


@router.post("/query", response_model=QueryResponse)
def query(body: QueryRequest, request: Request) -> QueryResponse:
    started = time.perf_counter()
    index = _lab_index(request, body.space_id)
    if index.chunk_count == 0:
        raise HTTPException(
            status_code=400,
            detail="Index is empty. Ingest the docs folder first.",
        )
    try:
        hits = index.query(body.question, mode=body.mode, top_k=body.top_k)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except OllamaError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    retrieve_ms = (time.perf_counter() - started) * 1000

    sources = [_serialize_source(h) for h in hits]
    generation_error = None
    if ollama_model_ready():
        try:
            answer = generate_answer(body.question, hits)
            kind: Literal["llm", "extractive"] = "llm"
        except OllamaError as exc:
            generation_error = str(exc)
            answer = extractive_answer(body.question, hits)
            kind = "extractive"
    else:
        generation_error = (
            f"Chat model {settings.ollama_model} is not installed. "
            f"Showing passages from the index. Run `ollama pull {settings.ollama_model}` for a written answer."
        )
        answer = extractive_answer(body.question, hits)
        kind = "extractive"
    compare = _top_by_mode(index, body.question, body.mode, hits)
    return QueryResponse(
        answer=answer,
        sources=sources,
        mode=body.mode,
        answer_kind=kind,
        generation_error=generation_error,
        top_by_mode=compare,
        retrieve_ms=round(retrieve_ms, 1),
        total_ms=round((time.perf_counter() - started) * 1000, 1),
        lexical=looks_lexical(body.question),
    )

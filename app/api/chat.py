from __future__ import annotations

import json
import time
from typing import Any

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from app.auth import allowed_space_ids, require_space, require_user
from app.catalog import get_model, models_for_user
from app.db import get_db
from app.generate.extractive import extractive_answer, extractive_chunks
from app.generate.llm import complete, stream_complete
from app.generate.ollama_client import OllamaError
from app.retrieve.hybrid import looks_lexical
from app.security import iso, new_id
from app.ratelimit import check_rate
from app.spaces import query_allowed_spaces, spaces_for_user
from app.usage import audit, record_usage

router = APIRouter(prefix="/chat", tags=["chat"])


class ThreadBody(BaseModel):
    space_id: str | None = None


class MessageBody(BaseModel):
    content: str = Field(min_length=1)
    model_id: str | None = None
    space_id: str | None = None


def _visible_content(content: str) -> str:
    if "<!--" in content:
        return content.split("<!--", 1)[0].rstrip()
    return content


def _followup_query(question: str, history: list[dict]) -> str:
    prior = [_visible_content(m["content"]) for m in history if m.get("role") == "user"]
    if prior:
        return f"{prior[-1]}\n{question}"
    return question


def _pick_model(user: dict, model_id: str | None) -> dict[str, Any]:
    allowed = models_for_user(user["tier"])
    if not allowed:
        raise HTTPException(status_code=400, detail="No chat models are enabled.")
    if model_id:
        match = next((m for m in allowed if m["id"] == model_id), None)
        if not match:
            raise HTTPException(status_code=403, detail="That model is not available on your plan.")
        full = get_model(model_id)
        if not full:
            raise HTTPException(status_code=404, detail="Model not found.")
        return full
    return get_model(allowed[0]["id"]) or allowed[0]


def _sse(payload: dict) -> str:
    return f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"


def _source_rows(hits: list[dict]) -> list[dict]:
    return [
        {
            "chunk_id": h["id"],
            "source": h["source"],
            "title": h.get("title") or h["source"],
            "space_id": h.get("space_id"),
            "space_name": h.get("space_name"),
            "snippet": " ".join((h.get("text") or "").split())[:280],
        }
        for h in hits[:6]
    ]


def _load_turn(thread_id: str, request: Request, body: MessageBody) -> dict[str, Any]:
    user = require_user(request)
    check_rate(f"chat:{user['id']}", limit=40, window_s=60)
    with get_db() as conn:
        thread = conn.execute(
            "SELECT * FROM threads WHERE id = ? AND user_id = ?",
            (thread_id, user["id"]),
        ).fetchone()
        if not thread:
            raise HTTPException(status_code=404, detail="Thread not found.")
        history_rows = conn.execute(
            "SELECT role, content FROM messages WHERE thread_id = ? ORDER BY created_at",
            (thread_id,),
        ).fetchall()
    history = [{"role": r["role"], "content": _visible_content(r["content"])} for r in history_rows]
    space_id = body.space_id or thread["space_id"]
    if space_id:
        require_space(user, space_id)
        space_ids = [space_id]
    else:
        space_ids = allowed_space_ids(user["id"])
    if not space_ids:
        raise HTTPException(status_code=400, detail="You are not a member of any space.")
    names = {s["id"]: s["name"] for s in spaces_for_user(user["id"], user["org_role"])}
    model = _pick_model(user, body.model_id)
    return {
        "user": user,
        "thread": thread,
        "history": history,
        "space_id": space_id,
        "space_ids": space_ids,
        "names": names,
        "model": model,
    }


def _persist_turn(
    thread_id: str,
    ctx: dict[str, Any],
    body: MessageBody,
    answer: str,
    kind: str,
    gen_error: str | None,
    hits: list[dict],
    started: float,
) -> dict[str, Any]:
    user = ctx["user"]
    model = ctx["model"]
    space_id = ctx["space_id"]
    title = body.content[:72]
    now = iso()
    sources = _source_rows(hits)
    payload = json.dumps({"sources": sources, "kind": kind, "error": gen_error})
    with get_db() as conn:
        conn.execute(
            "INSERT INTO messages(id, thread_id, role, content, model_id, created_at) VALUES (?, ?, 'user', ?, ?, ?)",
            (new_id("msg_"), thread_id, body.content, model["id"], now),
        )
        conn.execute(
            "INSERT INTO messages(id, thread_id, role, content, model_id, created_at) VALUES (?, ?, 'assistant', ?, ?, ?)",
            (new_id("msg_"), thread_id, answer + "\n<!--" + payload + "-->", model["id"], now),
        )
        conn.execute(
            "UPDATE threads SET title = ?, space_id = ?, updated_at = ? WHERE id = ?",
            (title, space_id, now, thread_id),
        )
    latency = (time.perf_counter() - started) * 1000
    prompt_tokens = max(1, len(body.content) // 4)
    completion_tokens = max(1, len(answer) // 4)
    record_usage(
        user["id"],
        space_id,
        model["id"],
        prompt_tokens,
        completion_tokens,
        float(model.get("cost_per_1k_in") or 0),
        float(model.get("cost_per_1k_out") or 0),
        latency,
    )
    cited = ", ".join(sorted({s["source"] for s in sources}))
    audit(user["id"], space_id, "chat", f"{body.content[:180]} | cites: {cited}")
    return {
        "answer": answer,
        "answer_kind": kind,
        "generation_error": gen_error,
        "sources": sources,
        "model": {"id": model["id"], "display_name": model["display_name"], "tier": model["tier"]},
        "lexical": looks_lexical(body.content),
        "latency_ms": round(latency, 1),
    }


@router.get("/models")
def chat_models(request: Request) -> dict:
    user = require_user(request)
    return {"models": models_for_user(user["tier"]), "tier": user["tier"]}


@router.get("/threads")
def list_threads(request: Request) -> dict:
    user = require_user(request)
    with get_db() as conn:
        rows = conn.execute(
            "SELECT * FROM threads WHERE user_id = ? ORDER BY updated_at DESC",
            (user["id"],),
        ).fetchall()
    return {"threads": [dict(r) for r in rows]}


@router.post("/threads")
def create_thread(request: Request, body: ThreadBody) -> dict:
    user = require_user(request)
    if body.space_id:
        require_space(user, body.space_id)
    thread_id = new_id("t_")
    now = iso()
    with get_db() as conn:
        conn.execute(
            """
            INSERT INTO threads(id, user_id, space_id, title, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (thread_id, user["id"], body.space_id, "New chat", now, now),
        )
    return {"id": thread_id, "space_id": body.space_id, "title": "New chat"}


@router.get("/threads/{thread_id}")
def get_thread(thread_id: str, request: Request) -> dict:
    user = require_user(request)
    with get_db() as conn:
        thread = conn.execute(
            "SELECT * FROM threads WHERE id = ? AND user_id = ?",
            (thread_id, user["id"]),
        ).fetchone()
        if not thread:
            raise HTTPException(status_code=404, detail="Thread not found.")
        messages = conn.execute(
            "SELECT * FROM messages WHERE thread_id = ? ORDER BY created_at",
            (thread_id,),
        ).fetchall()
    return {"thread": dict(thread), "messages": [dict(m) for m in messages]}


@router.delete("/threads/{thread_id}")
def delete_thread(thread_id: str, request: Request) -> dict:
    user = require_user(request)
    with get_db() as conn:
        thread = conn.execute(
            "SELECT id FROM threads WHERE id = ? AND user_id = ?",
            (thread_id, user["id"]),
        ).fetchone()
        if not thread:
            raise HTTPException(status_code=404, detail="Thread not found.")
        conn.execute("DELETE FROM messages WHERE thread_id = ?", (thread_id,))
        conn.execute("DELETE FROM threads WHERE id = ?", (thread_id,))
    return {"ok": True}


@router.post("/threads/{thread_id}/messages")
def post_message(thread_id: str, request: Request, body: MessageBody) -> dict:
    started = time.perf_counter()
    ctx = _load_turn(thread_id, request, body)
    retrieval_q = _followup_query(body.content, ctx["history"])
    hits = query_allowed_spaces(ctx["space_ids"], retrieval_q, names=ctx["names"])
    model = ctx["model"]
    try:
        result = complete(model, body.content, hits, ctx["history"])
        answer = result["answer"]
        kind = result["kind"]
        gen_error = None
    except OllamaError as exc:
        answer = extractive_answer(body.content, hits)
        kind = "extractive"
        gen_error = str(exc)
    return _persist_turn(thread_id, ctx, body, answer, kind, gen_error, hits, started)


@router.post("/threads/{thread_id}/messages/stream")
def stream_message(thread_id: str, request: Request, body: MessageBody) -> StreamingResponse:
    ctx = _load_turn(thread_id, request, body)

    def events():
        started = time.perf_counter()
        yield _sse({"status": "retrieving"})
        retrieval_q = _followup_query(body.content, ctx["history"])
        hits = query_allowed_spaces(ctx["space_ids"], retrieval_q, names=ctx["names"])
        yield _sse({"status": "generating", "sources": _source_rows(hits)})
        pieces: list[str] = []
        kind = "extractive" if ctx["model"]["provider"] == "extractive" else "llm"
        gen_error = None
        try:
            for delta in stream_complete(ctx["model"], body.content, hits, ctx["history"]):
                pieces.append(delta)
                yield _sse({"delta": delta})
        except OllamaError as exc:
            gen_error = str(exc)
            kind = "extractive"
            pieces = []
            for delta in extractive_chunks(body.content, hits):
                pieces.append(delta)
                yield _sse({"delta": delta})
        answer = "".join(pieces)
        data = _persist_turn(thread_id, ctx, body, answer, kind, gen_error, hits, started)
        yield _sse({"done": True, **{k: v for k, v in data.items() if k != "answer"}})

    return StreamingResponse(
        events(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )

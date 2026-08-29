from __future__ import annotations

from typing import Any

from app.config import settings
from app.db import get_db, kv_get, setup_complete
from app.generate.llm import model_ready
from app.generate.ollama_client import ollama_available, ollama_model_names
from app.security import iso, new_id
from app.spaces import list_spaces


def seed_default_models() -> None:
    with get_db() as conn:
        count = conn.execute("SELECT COUNT(*) AS n FROM models").fetchone()["n"]
        if count:
            return
        now = iso()
        conn.execute(
            """
            INSERT INTO models(id, display_name, provider, model_id, tier, enabled, created_at)
            VALUES (?, ?, 'extractive', 'extractive', 'free', 1, ?)
            """,
            (new_id("m_"), "Quote from documents (free)", now),
        )
        conn.execute(
            """
            INSERT INTO models(id, display_name, provider, model_id, tier, enabled, created_at)
            VALUES (?, ?, 'ollama', ?, 'free', 1, ?)
            """,
            (new_id("m_"), f"Local {settings.ollama_model} (free)", settings.ollama_model, now),
        )


def list_models(enabled_only: bool = False) -> list[dict[str, Any]]:
    seed_default_models()
    sql = "SELECT * FROM models ORDER BY tier, display_name"
    with get_db() as conn:
        rows = conn.execute(sql).fetchall()
    out = []
    for row in rows:
        item = dict(row)
        if enabled_only and not item["enabled"]:
            continue
        ready, note = model_ready(item)
        item["ready"] = ready
        item["status"] = note
        item.pop("api_key", None)
        item["has_api_key"] = bool(row["api_key"])
        out.append(item)
    return out


def get_model(model_pk: str) -> dict[str, Any] | None:
    seed_default_models()
    with get_db() as conn:
        row = conn.execute("SELECT * FROM models WHERE id = ?", (model_pk,)).fetchone()
    return dict(row) if row else None


def models_for_user(tier: str) -> list[dict[str, Any]]:
    allowed = {"free", "premium"} if tier == "premium" else {"free"}
    return [m for m in list_models(enabled_only=True) if m["tier"] in allowed]


def disk_free_mb() -> float | None:
    try:
        usage = __import__("shutil").disk_usage(settings.data_dir)
        return round(usage.free / (1024 * 1024), 1)
    except OSError:
        return None


def ops_health() -> dict[str, Any]:
    spaces = list_spaces()
    models = list_models()
    ollama = ollama_available()
    return {
        "ok": True,
        "setup_complete": setup_complete(),
        "org_name": kv_get("org_name") or settings.app_name,
        "app_name": settings.app_name,
        "ollama": ollama,
        "ollama_host": settings.ollama_host,
        "ollama_models": ollama_model_names() if ollama else [],
        "embedding_model": settings.embedding_model,
        "disk_free_mb": disk_free_mb(),
        "spaces": spaces,
        "models": models,
        "needs_ingest": all(s["chunk_count"] == 0 for s in spaces) if spaces else True,
    }

from __future__ import annotations

from typing import Any

from app.db import get_db
from app.security import iso, new_id


def record_usage(
    user_id: str | None,
    space_id: str | None,
    model_id: str | None,
    prompt_tokens: int,
    completion_tokens: int,
    cost_in: float = 0.0,
    cost_out: float = 0.0,
    latency_ms: float | None = None,
) -> None:
    estimated = (prompt_tokens / 1000.0) * cost_in + (completion_tokens / 1000.0) * cost_out
    with get_db() as conn:
        conn.execute(
            """
            INSERT INTO usage_events(
                id, user_id, space_id, model_id, prompt_tokens, completion_tokens,
                estimated_cost, latency_ms, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                new_id("us_"),
                user_id,
                space_id,
                model_id,
                prompt_tokens,
                completion_tokens,
                estimated,
                latency_ms,
                iso(),
            ),
        )


def audit(user_id: str | None, space_id: str | None, action: str, detail: str = "") -> None:
    with get_db() as conn:
        conn.execute(
            "INSERT INTO audit_events(id, user_id, space_id, action, detail, created_at) VALUES (?, ?, ?, ?, ?, ?)",
            (new_id("a_"), user_id, space_id, action, detail, iso()),
        )


def usage_summary() -> dict[str, Any]:
    with get_db() as conn:
        totals = conn.execute(
            """
            SELECT COALESCE(SUM(prompt_tokens), 0) AS prompt,
                   COALESCE(SUM(completion_tokens), 0) AS completion,
                   COALESCE(SUM(estimated_cost), 0) AS cost,
                   COUNT(*) AS calls
            FROM usage_events
            """
        ).fetchone()
        by_model = conn.execute(
            """
            SELECT model_id,
                   SUM(prompt_tokens + completion_tokens) AS tokens,
                   SUM(estimated_cost) AS cost,
                   COUNT(*) AS calls
            FROM usage_events
            GROUP BY model_id
            ORDER BY tokens DESC
            """
        ).fetchall()
        by_user = conn.execute(
            """
            SELECT user_id,
                   SUM(prompt_tokens + completion_tokens) AS tokens,
                   SUM(estimated_cost) AS cost,
                   COUNT(*) AS calls
            FROM usage_events
            GROUP BY user_id
            ORDER BY tokens DESC
            LIMIT 20
            """
        ).fetchall()
        by_day = conn.execute(
            """
            SELECT substr(created_at, 1, 10) AS day,
                   SUM(prompt_tokens + completion_tokens) AS tokens,
                   SUM(estimated_cost) AS cost,
                   COUNT(*) AS calls
            FROM usage_events
            GROUP BY day
            ORDER BY day DESC
            LIMIT 30
            """
        ).fetchall()
        by_space = conn.execute(
            """
            SELECT space_id,
                   SUM(prompt_tokens + completion_tokens) AS tokens,
                   COUNT(*) AS calls
            FROM usage_events
            GROUP BY space_id
            ORDER BY tokens DESC
            """
        ).fetchall()
    return {
        "prompt_tokens": totals["prompt"],
        "completion_tokens": totals["completion"],
        "estimated_cost": round(float(totals["cost"] or 0), 6),
        "calls": totals["calls"],
        "by_model": [dict(r) for r in by_model],
        "by_user": [dict(r) for r in by_user],
        "by_day": [dict(r) for r in by_day],
        "by_space": [dict(r) for r in by_space],
    }


def list_audit(limit: int = 500) -> list[dict[str, Any]]:
    with get_db() as conn:
        rows = conn.execute(
            "SELECT * FROM audit_events ORDER BY created_at DESC LIMIT ?",
            (limit,),
        ).fetchall()
    return [dict(r) for r in rows]

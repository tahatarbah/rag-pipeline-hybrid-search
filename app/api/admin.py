from __future__ import annotations

import csv
import io

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from app.auth import create_user, require_org_admin
from app.catalog import get_model, list_models, ops_health, seed_default_models
from app.db import get_db
from app.security import iso, new_id
from app.usage import audit, list_audit, usage_summary

router = APIRouter(prefix="/admin", tags=["admin"])


class UserBody(BaseModel):
    email: str
    name: str
    password: str = Field(min_length=8)
    org_role: str = "member"
    tier: str = "free"


class ModelBody(BaseModel):
    display_name: str
    provider: str
    model_id: str
    tier: str = "free"
    enabled: bool = True
    api_base: str | None = None
    api_key: str | None = None
    cost_per_1k_in: float = 0
    cost_per_1k_out: float = 0


class ModelPatch(BaseModel):
    display_name: str | None = None
    enabled: bool | None = None
    tier: str | None = None
    api_base: str | None = None
    api_key: str | None = None
    cost_per_1k_in: float | None = None
    cost_per_1k_out: float | None = None


class UserPatch(BaseModel):
    tier: str | None = None
    org_role: str | None = None


@router.get("/ops")
def ops(request: Request) -> dict:
    require_org_admin(request)
    return {"health": ops_health(), "usage": usage_summary()}


@router.get("/users")
def users(request: Request) -> dict:
    require_org_admin(request)
    with get_db() as conn:
        rows = conn.execute(
            "SELECT id, email, name, org_role, tier, created_at FROM users ORDER BY email"
        ).fetchall()
    return {"users": [dict(r) for r in rows]}


@router.post("/users")
def add_user(request: Request, body: UserBody) -> dict:
    admin = require_org_admin(request)
    try:
        user = create_user(body.email, body.name, body.password, body.org_role, body.tier)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"Could not create user: {exc}") from exc
    audit(admin["id"], None, "create_user", body.email)
    return user


@router.patch("/users/{user_id}")
def patch_user(user_id: str, request: Request, body: UserPatch) -> dict:
    require_org_admin(request)
    with get_db() as conn:
        if body.tier:
            conn.execute("UPDATE users SET tier = ? WHERE id = ?", (body.tier, user_id))
        if body.org_role:
            conn.execute("UPDATE users SET org_role = ? WHERE id = ?", (body.org_role, user_id))
    return {"ok": True}


@router.get("/models")
def models(request: Request) -> dict:
    require_org_admin(request)
    seed_default_models()
    return {"models": list_models()}


@router.post("/models")
def add_model(request: Request, body: ModelBody) -> dict:
    require_org_admin(request)
    model_pk = new_id("m_")
    with get_db() as conn:
        conn.execute(
            """
            INSERT INTO models(
                id, display_name, provider, model_id, tier, enabled,
                api_base, api_key, cost_per_1k_in, cost_per_1k_out, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                model_pk,
                body.display_name,
                body.provider,
                body.model_id,
                body.tier,
                1 if body.enabled else 0,
                body.api_base,
                body.api_key,
                body.cost_per_1k_in,
                body.cost_per_1k_out,
                iso(),
            ),
        )
    return {"id": model_pk}


@router.patch("/models/{model_pk}")
def patch_model(model_pk: str, request: Request, body: ModelPatch) -> dict:
    require_org_admin(request)
    row = get_model(model_pk)
    if not row:
        raise HTTPException(status_code=404, detail="Model not found.")
    fields = body.model_dump(exclude_none=True)
    if "enabled" in fields:
        fields["enabled"] = 1 if fields["enabled"] else 0
    allowed = {
        "display_name",
        "enabled",
        "tier",
        "api_base",
        "api_key",
        "cost_per_1k_in",
        "cost_per_1k_out",
        "model_id",
        "provider",
    }
    fields = {k: v for k, v in fields.items() if k in allowed}
    if not fields:
        return {"ok": True}
    assignments = ", ".join(f"{k} = ?" for k in fields)
    with get_db() as conn:
        conn.execute(f"UPDATE models SET {assignments} WHERE id = ?", (*fields.values(), model_pk))
    return {"ok": True}


@router.get("/audit.csv")
def audit_csv(request: Request) -> StreamingResponse:
    require_org_admin(request)
    rows = list_audit(2000)
    buf = io.StringIO()
    writer = csv.DictWriter(
        buf,
        fieldnames=["id", "created_at", "user_id", "space_id", "action", "detail"],
    )
    writer.writeheader()
    writer.writerows(rows)
    buf.seek(0)
    return StreamingResponse(
        iter([buf.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=audit.csv"},
    )

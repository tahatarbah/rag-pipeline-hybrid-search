from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from app.auth import require_org_admin, require_space, require_user
from app.db import get_db
from app.jobs import delete_document, enqueue_ingest, latest_job, save_upload, start_ingest_worker
from app.spaces import add_member, create_space, list_spaces, load_demo_docs, spaces_for_user
from app.usage import audit

router = APIRouter(prefix="/spaces", tags=["spaces"])


class SpaceBody(BaseModel):
    name: str = Field(min_length=1)


class MemberBody(BaseModel):
    email: str
    role: str = "viewer"


@router.get("")
def list_mine(request: Request) -> dict:
    user = require_user(request)
    return {"spaces": spaces_for_user(user["id"], user["org_role"])}


@router.post("")
def create(request: Request, body: SpaceBody) -> dict:
    admin = require_org_admin(request)
    space = create_space(body.name)
    add_member(space["id"], admin["id"], "admin")
    audit(admin["id"], space["id"], "create_space", body.name)
    return space


@router.post("/{space_id}/members")
def add_space_member(space_id: str, request: Request, body: MemberBody) -> dict:
    user = require_user(request)
    require_space(user, space_id, write=True)
    with get_db() as conn:
        row = conn.execute(
            "SELECT id FROM users WHERE email = ?", (body.email.strip().lower(),)
        ).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="No user with that email. Create the account first.")
    add_member(space_id, row["id"], body.role)
    audit(user["id"], space_id, "add_member", body.email)
    return {"ok": True}


@router.delete("/{space_id}/members/{email:path}")
def remove_space_member(space_id: str, email: str, request: Request) -> dict:
    user = require_user(request)
    require_space(user, space_id, write=True)
    with get_db() as conn:
        row = conn.execute(
            "SELECT id FROM users WHERE email = ?", (email.strip().lower(),)
        ).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="No user with that email.")
        conn.execute(
            "DELETE FROM memberships WHERE user_id = ? AND space_id = ?",
            (row["id"], space_id),
        )
    audit(user["id"], space_id, "remove_member", email)
    return {"ok": True}


@router.get("/{space_id}/members")
def list_members(space_id: str, request: Request) -> dict:
    user = require_user(request)
    require_space(user, space_id)
    with get_db() as conn:
        rows = conn.execute(
            """
            SELECT u.email, u.name, u.tier, m.role
            FROM memberships m JOIN users u ON u.id = m.user_id
            WHERE m.space_id = ?
            """,
            (space_id,),
        ).fetchall()
    return {"members": [dict(r) for r in rows]}


@router.post("/{space_id}/upload")
async def upload(space_id: str, request: Request) -> dict:
    user = require_user(request)
    require_space(user, space_id, write=True)
    form = await request.form()
    saved: list[str] = []
    for upload in form.getlist("files"):
        filename = getattr(upload, "filename", None)
        if not filename:
            continue
        try:
            saved.append(save_upload(space_id, filename, await upload.read()))
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
    job_id = enqueue_ingest(space_id)
    start_ingest_worker()
    audit(user["id"], space_id, "upload", ", ".join(saved))
    return {"saved": saved, "job_id": job_id}


@router.post("/{space_id}/ingest")
def reindex(space_id: str, request: Request) -> dict:
    user = require_user(request)
    require_space(user, space_id, write=True)
    job_id = enqueue_ingest(space_id)
    start_ingest_worker()
    audit(user["id"], space_id, "reindex", "")
    return {"job_id": job_id}


@router.get("/{space_id}/ingest")
def ingest_status(space_id: str, request: Request) -> dict:
    user = require_user(request)
    require_space(user, space_id)
    return {"job": latest_job(space_id)}


@router.post("/{space_id}/demo")
def demo(space_id: str, request: Request) -> dict:
    user = require_user(request)
    require_space(user, space_id, write=True)
    with get_db() as conn:
        row = conn.execute("SELECT slug FROM spaces WHERE id = ?", (space_id,)).fetchone()
    pack = row["slug"] if row else None
    copied = load_demo_docs(space_id, pack=pack)
    job_id = enqueue_ingest(space_id)
    start_ingest_worker()
    return {"copied": copied, "job_id": job_id}


@router.delete("/{space_id}/documents/{filename}")
def remove_doc(space_id: str, filename: str, request: Request) -> dict:
    user = require_user(request)
    require_space(user, space_id, write=True)
    delete_document(space_id, filename)
    job_id = enqueue_ingest(space_id)
    start_ingest_worker()
    audit(user["id"], space_id, "delete_document", filename)
    return {"ok": True, "job_id": job_id}

from __future__ import annotations

from typing import Any

from fastapi import HTTPException, Request, Response

from app.config import settings
from app.db import get_db, kv_get, setup_complete
from app.security import hash_password, iso, later, new_id, verify_password

COOKIE = "docs_session"
SESSION_HOURS = 24 * 14


def row_user(row) -> dict[str, Any]:
    return {
        "id": row["id"],
        "email": row["email"],
        "name": row["name"],
        "org_role": row["org_role"],
        "tier": row["tier"],
    }


def current_user(request: Request) -> dict[str, Any] | None:
    token = request.cookies.get(COOKIE)
    if not token:
        return None
    with get_db() as conn:
        row = conn.execute(
            """
            SELECT u.* FROM sessions s
            JOIN users u ON u.id = s.user_id
            WHERE s.token = ? AND s.expires_at > ?
            """,
            (token, iso()),
        ).fetchone()
    return row_user(row) if row else None


def require_user(request: Request) -> dict[str, Any]:
    user = current_user(request)
    if not user:
        raise HTTPException(status_code=401, detail="Sign in required.")
    return user


def require_org_admin(request: Request) -> dict[str, Any]:
    user = require_user(request)
    if user["org_role"] != "org_admin":
        raise HTTPException(status_code=403, detail="Organization admin required.")
    return user


def set_session(response: Response, user_id: str) -> None:
    token = new_id("s_")
    with get_db() as conn:
        conn.execute(
            "INSERT INTO sessions(token, user_id, expires_at) VALUES (?, ?, ?)",
            (token, user_id, later(SESSION_HOURS)),
        )
    response.set_cookie(
        COOKIE,
        token,
        httponly=True,
        samesite="lax",
        path="/",
        max_age=SESSION_HOURS * 3600,
    )


def clear_session(request: Request, response: Response) -> None:
    token = request.cookies.get(COOKIE)
    if token:
        with get_db() as conn:
            conn.execute("DELETE FROM sessions WHERE token = ?", (token,))
    response.delete_cookie(COOKIE)


def authenticate(email: str, password: str) -> dict[str, Any] | None:
    with get_db() as conn:
        row = conn.execute(
            "SELECT * FROM users WHERE email = ?", (email.strip().lower(),)
        ).fetchone()
    if not row or not verify_password(password, row["password_hash"]):
        return None
    return row_user(row)


def create_user(
    email: str,
    name: str,
    password: str | None,
    org_role: str = "member",
    tier: str = "free",
) -> dict[str, Any]:
    user_id = new_id("u_")
    hashed = hash_password(password) if password else None
    with get_db() as conn:
        conn.execute(
            """
            INSERT INTO users(id, email, name, password_hash, org_role, tier, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (user_id, email.strip().lower(), name.strip(), hashed, org_role, tier, iso()),
        )
    return {
        "id": user_id,
        "email": email.strip().lower(),
        "name": name.strip(),
        "org_role": org_role,
        "tier": tier,
    }


def allowed_space_ids(user_id: str) -> list[str]:
    with get_db() as conn:
        admin = conn.execute(
            "SELECT org_role FROM users WHERE id = ?", (user_id,)
        ).fetchone()
        if admin and admin["org_role"] == "org_admin":
            rows = conn.execute("SELECT id FROM spaces").fetchall()
            return [r["id"] for r in rows]
        rows = conn.execute(
            "SELECT space_id FROM memberships WHERE user_id = ?", (user_id,)
        ).fetchall()
    return [r["space_id"] for r in rows]


def membership(user_id: str, space_id: str) -> str | None:
    with get_db() as conn:
        admin = conn.execute(
            "SELECT org_role FROM users WHERE id = ?", (user_id,)
        ).fetchone()
        if admin and admin["org_role"] == "org_admin":
            return "admin"
        row = conn.execute(
            "SELECT role FROM memberships WHERE user_id = ? AND space_id = ?",
            (user_id, space_id),
        ).fetchone()
    return row["role"] if row else None


def require_space(user: dict[str, Any], space_id: str, write: bool = False) -> str:
    role = membership(user["id"], space_id)
    if not role:
        raise HTTPException(status_code=403, detail="You cannot access that space.")
    if write and role == "viewer":
        raise HTTPException(status_code=403, detail="Editors or admins can change this space.")
    return role


def org_name() -> str:
    return kv_get("org_name") or settings.org_name or settings.app_name

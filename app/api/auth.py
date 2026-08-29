from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request, Response
from fastapi.responses import RedirectResponse
from pydantic import BaseModel, Field

from app.auth import (
    authenticate,
    clear_session,
    create_user,
    current_user,
    org_name,
    require_user,
    set_session,
)
from app.catalog import seed_default_models
from app.config import settings
from app.db import get_db, kv_set, setup_complete
from app.demo import seed_demo_users, seed_space_docs
from app.jobs import start_ingest_worker
from app.ratelimit import check_rate, client_ip
from app.spaces import add_member, create_space
from app.usage import audit

router = APIRouter(prefix="/auth", tags=["auth"])


class SetupBody(BaseModel):
    org_name: str = Field(min_length=1)
    admin_email: str = Field(min_length=3)
    admin_name: str = Field(min_length=1)
    password: str = Field(min_length=8)
    load_demo: bool = True


class LoginBody(BaseModel):
    email: str
    password: str


@router.get("/status")
def status(request: Request) -> dict:
    user = current_user(request)
    return {
        "setup_complete": setup_complete(),
        "org_name": org_name(),
        "oidc_enabled": bool(settings.oidc_issuer and settings.oidc_client_id),
        "user": user,
    }


@router.post("/setup")
def setup(body: SetupBody, response: Response) -> dict:
    if setup_complete():
        raise HTTPException(status_code=400, detail="This appliance is already set up.")
    admin = create_user(
        body.admin_email,
        body.admin_name,
        body.password,
        org_role="org_admin",
        tier="premium",
    )
    kv_set("org_name", body.org_name.strip())
    kv_set("setup_complete", "1")
    seed_default_models()
    created = []
    for name in ("HR", "Engineering", "Finance"):
        space = create_space(name)
        add_member(space["id"], admin["id"], "admin")
        created.append(space)
    if body.load_demo:
        seed_space_docs(created)
        seed_demo_users(created)
    start_ingest_worker()
    set_session(response, admin["id"])
    audit(admin["id"], None, "setup", body.org_name)
    return {"ok": True, "user": admin, "spaces": created}


@router.post("/login")
def login(request: Request, body: LoginBody, response: Response) -> dict:
    check_rate(f"login:{client_ip(request)}", limit=10, window_s=60)
    user = authenticate(body.email, body.password)
    if not user:
        raise HTTPException(status_code=401, detail="Invalid email or password.")
    set_session(response, user["id"])
    audit(user["id"], None, "login", user["email"])
    return {"ok": True, "user": user}


@router.post("/logout")
def logout(request: Request, response: Response) -> dict:
    clear_session(request, response)
    return {"ok": True}


@router.get("/me")
def me(request: Request) -> dict:
    return {"user": require_user(request), "org_name": org_name()}


@router.get("/oidc/start")
def oidc_start() -> dict:
    if not (settings.oidc_issuer and settings.oidc_client_id):
        raise HTTPException(status_code=400, detail="OIDC is not configured.")
    import httpx

    issuer = settings.oidc_issuer.rstrip("/")
    try:
        discovery = httpx.get(f"{issuer}/.well-known/openid-configuration", timeout=10).json()
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"OIDC discovery failed: {exc}") from exc
    authorize = discovery.get("authorization_endpoint")
    if not authorize:
        raise HTTPException(status_code=502, detail="OIDC issuer has no authorization_endpoint.")
    redirect = settings.public_origin.rstrip("/") + settings.oidc_redirect_path
    url = (
        f"{authorize}?response_type=code&client_id={settings.oidc_client_id}"
        f"&redirect_uri={redirect}&scope=openid%20email%20profile"
    )
    return {"url": url}


@router.get("/oidc/callback")
def oidc_callback(request: Request, code: str | None = None) -> RedirectResponse:
    if not code:
        raise HTTPException(status_code=400, detail="Missing OIDC code.")
    if not (settings.oidc_issuer and settings.oidc_client_id):
        raise HTTPException(status_code=400, detail="OIDC is not configured.")
    import httpx

    issuer = settings.oidc_issuer.rstrip("/")
    discovery = httpx.get(f"{issuer}/.well-known/openid-configuration", timeout=10).json()
    token_url = discovery.get("token_endpoint")
    redirect = settings.public_origin.rstrip("/") + settings.oidc_redirect_path
    token_res = httpx.post(
        token_url,
        data={
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": redirect,
            "client_id": settings.oidc_client_id,
            "client_secret": settings.oidc_client_secret,
        },
        timeout=20,
    )
    if token_res.status_code >= 400:
        raise HTTPException(status_code=401, detail="OIDC token exchange failed.")
    tokens = token_res.json()
    access = tokens.get("access_token")
    userinfo_url = discovery.get("userinfo_endpoint")
    info = httpx.get(userinfo_url, headers={"Authorization": f"Bearer {access}"}, timeout=10).json()
    email = (info.get("email") or "").lower()
    name = info.get("name") or email.split("@")[0]
    if not email:
        raise HTTPException(status_code=401, detail="OIDC profile has no email.")
    with get_db() as conn:
        row = conn.execute("SELECT * FROM users WHERE email = ?", (email,)).fetchone()
    if row:
        user = {"id": row["id"], "email": row["email"], "name": row["name"], "org_role": row["org_role"], "tier": row["tier"]}
    else:
        user = create_user(email, name, password=None, org_role="member", tier="free")
    redirect = RedirectResponse("/", status_code=302)
    set_session(redirect, user["id"])
    audit(user["id"], None, "oidc_login", email)
    return redirect

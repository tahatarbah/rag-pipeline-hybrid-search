from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, PlainTextResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles

from app.api.admin import router as admin_router
from app.api.auth import router as auth_router
from app.api.chat import router as chat_router
from app.api.routes import router
from app.api.spaces import router as spaces_router
from app.config import settings
from app.db import init_db, setup_complete
from app.jobs import start_ingest_worker
from app.metrics import prometheus_metrics
from app.security import CSRF_COOKIE, csrf_ok, new_csrf

STATIC_DIR = Path(__file__).parent / "static"

_CSRF_EXEMPT = (
    "/api/auth/setup",
    "/api/auth/login",
    "/api/auth/oidc",
)


@asynccontextmanager
async def lifespan(_app: FastAPI):
    init_db()
    start_ingest_worker()
    yield


app = FastAPI(
    title="Internal Docs",
    description="Self-hosted RAG chatbot with hybrid search over internal documents.",
    version="1.0.0",
    lifespan=lifespan,
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list or ["http://127.0.0.1:8765"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.include_router(router, prefix="/api")
app.include_router(auth_router, prefix="/api")
app.include_router(spaces_router, prefix="/api")
app.include_router(chat_router, prefix="/api")
app.include_router(admin_router, prefix="/api")
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


@app.middleware("http")
async def check_origin(request: Request, call_next):
    if request.method in {"POST", "PUT", "PATCH", "DELETE"}:
        origin = request.headers.get("origin")
        allowed = set(settings.cors_origin_list) | {settings.public_origin.rstrip("/")}
        if origin and origin.rstrip("/") not in {o.rstrip("/") for o in allowed}:
            return JSONResponse({"detail": "Origin not allowed."}, status_code=403)
        path = request.url.path
        exempt = any(path.startswith(p) for p in _CSRF_EXEMPT)
        if request.cookies.get("docs_session") and not exempt:
            if not csrf_ok(request.cookies.get(CSRF_COOKIE), request.headers.get("x-csrf-token")):
                return JSONResponse({"detail": "CSRF token missing or invalid."}, status_code=403)
    response = await call_next(request)
    token = request.cookies.get(CSRF_COOKIE) or new_csrf()
    response.set_cookie(
        CSRF_COOKIE,
        token,
        httponly=False,
        samesite="lax",
        path="/",
        max_age=14 * 24 * 3600,
    )
    return response


@app.get("/health")
def probe() -> dict:
    return {"status": "ok"}


@app.get("/metrics", response_model=None)
def metrics() -> PlainTextResponse:
    return PlainTextResponse(prometheus_metrics(), media_type="text/plain; version=0.0.4")


@app.get("/", response_model=None)
def home():
    if not setup_complete():
        return RedirectResponse("/setup")
    return FileResponse(STATIC_DIR / "index.html")


@app.get("/setup", response_model=None)
def setup_page() -> FileResponse:
    return FileResponse(STATIC_DIR / "setup.html")


@app.get("/login", response_model=None)
def login_page() -> FileResponse:
    return FileResponse(STATIC_DIR / "login.html")


@app.get("/admin", response_model=None)
def admin_page() -> FileResponse:
    return FileResponse(STATIC_DIR / "admin.html")


@app.get("/lab", response_model=None)
def lab_page() -> FileResponse:
    return FileResponse(STATIC_DIR / "lab.html")

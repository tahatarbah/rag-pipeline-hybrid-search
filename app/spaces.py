from __future__ import annotations

import shutil
from pathlib import Path
from typing import Any

from app.config import ROOT_DIR, settings
from app.db import get_db
from app.retrieve.hybrid import HybridIndex
from app.security import iso, new_id

_INDEXES: dict[str, HybridIndex] = {}


def space_root(space_id: str) -> Path:
    root = settings.space_root(space_id)
    (root / "docs").mkdir(parents=True, exist_ok=True)
    (root / "inbox").mkdir(parents=True, exist_ok=True)
    return root


def get_space_index(space_id: str) -> HybridIndex:
    if space_id not in _INDEXES:
        _INDEXES[space_id] = HybridIndex(root=space_root(space_id))
    return _INDEXES[space_id]


def drop_space_index(space_id: str) -> None:
    _INDEXES.pop(space_id, None)


def list_spaces() -> list[dict[str, Any]]:
    with get_db() as conn:
        rows = conn.execute("SELECT * FROM spaces ORDER BY name").fetchall()
    out = []
    for row in rows:
        index = get_space_index(row["id"])
        out.append(
            {
                "id": row["id"],
                "slug": row["slug"],
                "name": row["name"],
                "chunk_count": index.chunk_count,
                "files": index.indexed_files,
            }
        )
    return out


def spaces_for_user(user_id: str, org_role: str) -> list[dict[str, Any]]:
    all_spaces = list_spaces()
    if org_role == "org_admin":
        return [{**space, "role": "admin"} for space in all_spaces]
    with get_db() as conn:
        rows = conn.execute(
            "SELECT space_id, role FROM memberships WHERE user_id = ?", (user_id,)
        ).fetchall()
    roles = {r["space_id"]: r["role"] for r in rows}
    return [{**space, "role": roles[space["id"]]} for space in all_spaces if space["id"] in roles]


def create_space(name: str, slug: str | None = None) -> dict[str, Any]:
    space_id = new_id("sp_")
    clean_slug = (slug or name).strip().lower().replace(" ", "-")
    with get_db() as conn:
        conn.execute(
            "INSERT INTO spaces(id, slug, name, created_at) VALUES (?, ?, ?, ?)",
            (space_id, clean_slug, name.strip(), iso()),
        )
    space_root(space_id)
    return {"id": space_id, "slug": clean_slug, "name": name.strip()}


def add_member(space_id: str, user_id: str, role: str = "viewer") -> None:
    with get_db() as conn:
        conn.execute(
            """
            INSERT INTO memberships(user_id, space_id, role) VALUES (?, ?, ?)
            ON CONFLICT(user_id, space_id) DO UPDATE SET role = excluded.role
            """,
            (user_id, space_id, role),
        )


def query_allowed_spaces(
    space_ids: list[str],
    question: str,
    mode: str = "hybrid",
    top_k: int | None = None,
    names: dict[str, str] | None = None,
) -> list[dict]:
    from app.retrieve.hybrid import diversify_by_source

    hits: list[dict] = []
    for space_id in space_ids:
        index = get_space_index(space_id)
        if index.chunk_count == 0:
            continue
        try:
            results = index.query(question, mode=mode, top_k=top_k)
        except ValueError:
            continue
        for item in results:
            item["space_id"] = space_id
            item["space_name"] = (names or {}).get(space_id)
            hits.append(item)
    hits.sort(key=lambda row: float(row.get("fused_score") or 0), reverse=True)
    return diversify_by_source(hits, top_k or settings.top_k, settings.max_chunks_per_source)


def load_demo_docs(space_id: str, pack: str | None = None) -> list[str]:
    if pack:
        candidates = [
            ROOT_DIR / "data" / "demo" / pack,
            ROOT_DIR / "seed-demo" / pack,
        ]
    else:
        candidates = [ROOT_DIR / "seed-docs", settings.docs_dir]
    src = next((p for p in candidates if p.exists() and any(p.iterdir())), None)
    dest = space_root(space_id) / "docs"
    dest.mkdir(parents=True, exist_ok=True)
    copied = []
    if src is None or not src.exists():
        return copied
    for path in src.iterdir():
        if path.is_file() and path.suffix.lower() in {".md", ".txt", ".pdf", ".docx"}:
            shutil.copy2(path, dest / path.name)
            copied.append(path.name)
            with get_db() as conn:
                conn.execute(
                    "INSERT INTO documents(id, space_id, filename, created_at) VALUES (?, ?, ?, ?)",
                    (new_id("d_"), space_id, path.name, iso()),
                )
    return copied

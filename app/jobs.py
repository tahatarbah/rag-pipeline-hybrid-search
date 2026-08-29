from __future__ import annotations

import threading
import time
from pathlib import Path

from app.db import get_db
from app.ingest.loaders import SUPPORTED_SUFFIXES
from app.security import iso, new_id
from app.spaces import drop_space_index, get_space_index, space_root

_WORKER_STARTED = False


def enqueue_ingest(space_id: str) -> str:
    job_id = new_id("j_")
    now = iso()
    with get_db() as conn:
        conn.execute(
            """
            INSERT INTO ingest_jobs(id, space_id, status, progress, percent, error, created_at, updated_at)
            VALUES (?, ?, 'queued', 'Waiting…', 0, NULL, ?, ?)
            """,
            (job_id, space_id, now, now),
        )
    _ensure_worker()
    return job_id


def _set_job(
    job_id: str,
    status: str,
    progress: str,
    error: str | None = None,
    percent: int = 0,
) -> None:
    with get_db() as conn:
        conn.execute(
            """
            UPDATE ingest_jobs
            SET status = ?, progress = ?, error = ?, percent = ?, updated_at = ?
            WHERE id = ?
            """,
            (status, progress, error, percent, iso(), job_id),
        )


def _run_job(job_id: str, space_id: str) -> None:
    _set_job(job_id, "running", "Reading documents…", percent=15)
    try:
        drop_space_index(space_id)
        index = get_space_index(space_id)
        _set_job(job_id, "running", "Building BM25 and dense indexes…", percent=40)
        meta = index.ingest()
        _set_job(
            job_id,
            "done",
            f"Indexed {meta.get('chunk_count', 0)} chunks",
            percent=100,
        )
    except Exception as exc:
        _set_job(job_id, "error", "Ingest failed", error=str(exc), percent=0)


def scan_inboxes() -> None:
    """Move files dropped into a space inbox/ folder into docs and reindex."""
    with get_db() as conn:
        rows = conn.execute("SELECT id FROM spaces").fetchall()
    for row in rows:
        space_id = row["id"]
        inbox = space_root(space_id) / "inbox"
        inbox.mkdir(parents=True, exist_ok=True)
        moved = False
        for path in list(inbox.iterdir()):
            if not path.is_file():
                continue
            if path.suffix.lower() not in SUPPORTED_SUFFIXES:
                continue
            try:
                save_upload(space_id, path.name, path.read_bytes())
                path.unlink(missing_ok=True)
                moved = True
            except (OSError, ValueError):
                continue
        if moved:
            enqueue_ingest(space_id)


def _loop() -> None:
    idle = 0
    while True:
        with get_db() as conn:
            row = conn.execute(
                "SELECT id, space_id FROM ingest_jobs WHERE status = 'queued' ORDER BY created_at LIMIT 1"
            ).fetchone()
        if row:
            _run_job(row["id"], row["space_id"])
            idle = 0
        else:
            idle += 1
            if idle % 8 == 0:
                try:
                    scan_inboxes()
                except Exception:
                    pass
            time.sleep(0.5)


def _ensure_worker() -> None:
    global _WORKER_STARTED
    if _WORKER_STARTED:
        return
    thread = threading.Thread(target=_loop, daemon=True, name="ingest-worker")
    thread.start()
    _WORKER_STARTED = True


def start_ingest_worker() -> None:
    _ensure_worker()


def save_upload(space_id: str, filename: str, data: bytes) -> str:
    from app.ingest.loaders import safe_filename

    dest_dir = space_root(space_id) / "docs"
    dest_dir.mkdir(parents=True, exist_ok=True)
    name = safe_filename(filename)
    suffix = Path(name).suffix.lower()
    if suffix not in SUPPORTED_SUFFIXES:
        raise ValueError(f"Unsupported file type: {suffix or '(none)'}. Use pdf, docx, md, or txt.")
    (dest_dir / name).write_bytes(data)
    with get_db() as conn:
        conn.execute(
            "DELETE FROM documents WHERE space_id = ? AND filename = ?",
            (space_id, name),
        )
        conn.execute(
            "INSERT INTO documents(id, space_id, filename, created_at) VALUES (?, ?, ?, ?)",
            (new_id("d_"), space_id, name, iso()),
        )
    return name


def delete_document(space_id: str, filename: str) -> None:
    path = space_root(space_id) / "docs" / Path(filename).name
    if path.exists():
        path.unlink()
    with get_db() as conn:
        conn.execute(
            "DELETE FROM documents WHERE space_id = ? AND filename = ?",
            (space_id, Path(filename).name),
        )


def latest_job(space_id: str) -> dict | None:
    with get_db() as conn:
        row = conn.execute(
            "SELECT * FROM ingest_jobs WHERE space_id = ? ORDER BY created_at DESC LIMIT 1",
            (space_id,),
        ).fetchone()
    return dict(row) if row else None

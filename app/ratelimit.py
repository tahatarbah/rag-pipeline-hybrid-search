from __future__ import annotations

import time
from collections import defaultdict

from fastapi import HTTPException, Request

_HITS: dict[str, list[float]] = defaultdict(list)


def client_ip(request: Request) -> str:
    forwarded = request.headers.get("x-forwarded-for", "")
    if forwarded:
        return forwarded.split(",")[0].strip()
    if request.client:
        return request.client.host
    return "unknown"


def check_rate(key: str, limit: int, window_s: float = 60.0) -> None:
    now = time.monotonic()
    recent = [t for t in _HITS[key] if now - t < window_s]
    if len(recent) >= limit:
        raise HTTPException(status_code=429, detail="Too many requests. Wait a minute and try again.")
    recent.append(now)
    _HITS[key] = recent

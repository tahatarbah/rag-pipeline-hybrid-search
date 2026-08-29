"""Shared CSRF header helper for cookie-authenticated TestClient calls."""


def csrf_headers(client) -> dict[str, str]:
    token = client.cookies.get("docs_csrf")
    if not token:
        client.get("/api/auth/status")
        token = client.cookies.get("docs_csrf")
    return {"X-CSRF-Token": token} if token else {}

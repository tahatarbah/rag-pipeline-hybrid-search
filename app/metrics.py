from __future__ import annotations

from app.db import get_db
from app.generate.ollama_client import ollama_available
from app.spaces import list_spaces


def prometheus_metrics() -> str:
    lines = [
        "# HELP docs_up 1 if the app is serving",
        "# TYPE docs_up gauge",
        "docs_up 1",
        "# HELP docs_ollama_up 1 if Ollama responds",
        "# TYPE docs_ollama_up gauge",
        f"docs_ollama_up {1 if ollama_available() else 0}",
    ]
    with get_db() as conn:
        usage = conn.execute(
            """
            SELECT COALESCE(SUM(prompt_tokens + completion_tokens), 0) AS tokens,
                   COUNT(*) AS calls
            FROM usage_events
            """
        ).fetchone()
        users = conn.execute("SELECT COUNT(*) AS n FROM users").fetchone()["n"]
    lines += [
        "# HELP docs_tokens_total Prompt plus completion tokens",
        "# TYPE docs_tokens_total counter",
        f"docs_tokens_total {usage['tokens']}",
        "# HELP docs_chat_calls_total Chat completions",
        "# TYPE docs_chat_calls_total counter",
        f"docs_chat_calls_total {usage['calls']}",
        "# HELP docs_users User accounts",
        "# TYPE docs_users gauge",
        f"docs_users {users}",
    ]
    for space in list_spaces():
        name = space["slug"].replace('"', "")
        lines.append(f'docs_space_chunks{{space="{name}"}} {space["chunk_count"]}')
    return "\n".join(lines) + "\n"

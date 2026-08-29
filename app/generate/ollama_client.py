from __future__ import annotations

import json

import httpx

from app.config import settings
from app.generate.prompts import SYSTEM_PROMPT, build_user_prompt


class OllamaError(RuntimeError):
    pass


def ollama_available(timeout: float = 2.0) -> bool:
    try:
        response = httpx.get(f"{settings.ollama_host.rstrip('/')}/api/tags", timeout=timeout)
        return response.status_code == 200
    except httpx.HTTPError:
        return False


def ollama_model_names(timeout: float = 2.0) -> list[str]:
    try:
        response = httpx.get(f"{settings.ollama_host.rstrip('/')}/api/tags", timeout=timeout)
        response.raise_for_status()
    except httpx.HTTPError:
        return []
    models = response.json().get("models") or []
    return [str(m.get("name") or "") for m in models if m.get("name")]


def ollama_model_ready(timeout: float = 2.0) -> bool:
    want = settings.ollama_model.lower()
    for name in ollama_model_names(timeout=timeout):
        lowered = name.lower()
        if lowered == want or lowered.startswith(f"{want}:") or want in lowered:
            return True
    return False


def generate_answer(
    question: str,
    sources: list[dict],
    history: list[dict] | None = None,
    model: str | None = None,
) -> str:
    payload = {
        "model": model or settings.ollama_model,
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": build_user_prompt(question, sources, history)},
        ],
        "stream": False,
        "options": {"temperature": 0.1},
    }
    url = f"{settings.ollama_host.rstrip('/')}/api/chat"
    try:
        response = httpx.post(url, json=payload, timeout=120.0)
    except httpx.HTTPError as exc:
        raise OllamaError(
            f"Ollama is unreachable at {settings.ollama_host}. "
            "Install Ollama, run `ollama pull "
            f"{settings.ollama_model}`, and start the app."
        ) from exc

    if response.status_code >= 400:
        detail = ""
        try:
            detail = (response.json().get("error") or "").strip()
        except ValueError:
            detail = response.text[:300]
        raise OllamaError(
            detail
            or (
                f"Ollama rejected model {settings.ollama_model}. "
                f"Run `ollama pull {settings.ollama_model}`."
            )
        )

    data = response.json()
    message = data.get("message") or {}
    content = (message.get("content") or "").strip()
    if not content:
        raise OllamaError("Ollama returned an empty response.")
    return content


def stream_answer(
    question: str,
    sources: list[dict],
    history: list[dict] | None = None,
    model: str | None = None,
):
    payload = {
        "model": model or settings.ollama_model,
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": build_user_prompt(question, sources, history)},
        ],
        "stream": True,
        "options": {"temperature": 0.1},
    }
    url = f"{settings.ollama_host.rstrip('/')}/api/chat"
    try:
        with httpx.stream("POST", url, json=payload, timeout=120.0) as response:
            if response.status_code >= 400:
                raise OllamaError(
                    f"Ollama rejected model {model or settings.ollama_model}. "
                    f"Run `ollama pull {settings.ollama_model}`."
                )
            for line in response.iter_lines():
                if not line:
                    continue
                try:
                    data = json.loads(line)
                except ValueError:
                    continue
                piece = ((data.get("message") or {}).get("content")) or ""
                if piece:
                    yield piece
                if data.get("done"):
                    break
    except httpx.HTTPError as exc:
        raise OllamaError(
            f"Ollama is unreachable at {settings.ollama_host}."
        ) from exc

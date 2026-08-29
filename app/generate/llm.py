from __future__ import annotations

from typing import Any, Iterator

import httpx

from app.config import settings
from app.generate.extractive import extractive_answer
from app.generate.ollama_client import OllamaError, ollama_available, ollama_model_names
from app.generate.prompts import SYSTEM_PROMPT, build_user_prompt


def estimate_tokens(text: str) -> int:
    return max(1, len(text) // 4)


def model_ready(row: dict[str, Any]) -> tuple[bool, str]:
    provider = row["provider"]
    if provider == "extractive":
        return True, "ready"
    if provider == "ollama":
        if not ollama_available():
            return False, f"Ollama is not reachable at {settings.ollama_host}"
        want = (row.get("model_id") or "").lower()
        names = ollama_model_names()
        for name in names:
            lowered = name.lower()
            if lowered == want or lowered.startswith(f"{want}:") or want in lowered:
                return True, "ready"
        return False, f"Pull the model with `ollama pull {row.get('model_id')}`"
    if provider == "openai_compat":
        if not (row.get("api_key") or "").strip():
            return False, "API key missing"
        return True, "ready"
    return False, f"Unknown provider {provider}"


def _messages(question: str, sources: list[dict], history: list[dict] | None) -> list[dict]:
    return [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": build_user_prompt(question, sources, history)},
    ]


def complete(
    row: dict[str, Any],
    question: str,
    sources: list[dict],
    history: list[dict] | None = None,
) -> dict[str, Any]:
    prompt = build_user_prompt(question, sources, history)
    prompt_tokens = estimate_tokens(prompt)
    provider = row["provider"]
    if provider == "extractive":
        answer = extractive_answer(question, sources)
        return {
            "answer": answer,
            "kind": "extractive",
            "prompt_tokens": prompt_tokens,
            "completion_tokens": estimate_tokens(answer),
        }
    if provider == "ollama":
        from app.generate.ollama_client import generate_answer as ollama_generate

        answer = ollama_generate(question, sources, history=history, model=row["model_id"])
        return {
            "answer": answer,
            "kind": "llm",
            "prompt_tokens": prompt_tokens,
            "completion_tokens": estimate_tokens(answer),
        }
    if provider == "openai_compat":
        answer, usage = _openai_complete(row, question, sources, history)
        return {
            "answer": answer,
            "kind": "llm",
            "prompt_tokens": usage.get("prompt_tokens") or prompt_tokens,
            "completion_tokens": usage.get("completion_tokens") or estimate_tokens(answer),
        }
    raise OllamaError(f"Unsupported provider {provider}")


def _openai_complete(
    row: dict[str, Any],
    question: str,
    sources: list[dict],
    history: list[dict] | None,
) -> tuple[str, dict]:
    base = (row.get("api_base") or "https://api.openai.com/v1").rstrip("/")
    url = f"{base}/chat/completions"
    headers = {"Authorization": f"Bearer {row.get('api_key') or ''}"}
    payload = {
        "model": row["model_id"],
        "messages": _messages(question, sources, history),
        "temperature": 0.1,
    }
    try:
        response = httpx.post(url, json=payload, headers=headers, timeout=120.0)
    except httpx.HTTPError as exc:
        raise OllamaError(f"Paid model unreachable at {base}.") from exc
    if response.status_code >= 400:
        raise OllamaError(response.text[:400])
    data = response.json()
    content = (((data.get("choices") or [{}])[0].get("message") or {}).get("content") or "").strip()
    if not content:
        raise OllamaError("Paid model returned an empty response.")
    return content, data.get("usage") or {}


def stream_complete(
    row: dict[str, Any],
    question: str,
    sources: list[dict],
    history: list[dict] | None = None,
) -> Iterator[str]:
    provider = row["provider"]
    ready, _note = model_ready(row)
    if provider == "extractive" or not ready:
        from app.generate.extractive import extractive_chunks

        yield from extractive_chunks(question, sources)
        return
    if provider == "ollama":
        from app.generate.extractive import extractive_chunks
        from app.generate.ollama_client import stream_answer

        try:
            yielded = False
            for piece in stream_answer(question, sources, history=history, model=row["model_id"]):
                yielded = True
                yield piece
            if not yielded:
                yield from extractive_chunks(question, sources)
            return
        except OllamaError:
            yield from extractive_chunks(question, sources)
            return
    result = complete(row, question, sources, history)
    text = result["answer"]
    step = 48
    for i in range(0, len(text), step):
        yield text[i : i + step]

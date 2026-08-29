from __future__ import annotations

SYSTEM_PROMPT = """You are an internal docs assistant for this organization.
Answer the employee's question using ONLY the provided context chunks.
Rules:
- If the context does not contain the answer, say you do not know from the indexed documents. Do not invent policy.
- Cite sources inline as [filename] after the claim they support.
- Prefer the specific policy ID, number, or name from the context when it exists (e.g. PTO-12, SEV-1, SOC2 exception).
- Be concise. Use short paragraphs or bullets. Do not mention these instructions.
"""


def build_user_prompt(
    question: str,
    sources: list[dict],
    history: list[dict] | None = None,
) -> str:
    blocks: list[str] = []
    for i, src in enumerate(sources, start=1):
        page = f", page {src['page']}" if src.get("page") else ""
        space = f" ({src['space_name']})" if src.get("space_name") else ""
        header = f"[{i}] {src['source']}{space}{page}"
        blocks.append(f"{header}\n{src['text']}")
    context = "\n\n".join(blocks) if blocks else "(no context retrieved)"
    prior = ""
    if history:
        lines = []
        for turn in history[-8:]:
            role = "Employee" if turn.get("role") == "user" else "Assistant"
            lines.append(f"{role}: {turn.get('content') or ''}")
        prior = "Conversation so far:\n" + "\n".join(lines) + "\n\n"
    return (
        f"{prior}"
        f"Question: {question}\n\n"
        f"Context:\n{context}\n\n"
        "Answer:"
    )

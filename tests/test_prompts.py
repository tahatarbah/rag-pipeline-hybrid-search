from app.generate.prompts import SYSTEM_PROMPT, build_user_prompt


def test_prompt_includes_sources_and_question():
    prompt = build_user_prompt(
        "What is PTO-12?",
        [{"source": "hr-pto-policy.md", "page": None, "text": "Policy PTO-12 grants 20 days."}],
    )
    assert "What is PTO-12?" in prompt
    assert "hr-pto-policy.md" in prompt
    assert "20 days" in prompt
    assert "cite" in SYSTEM_PROMPT.lower() or "Cite" in SYSTEM_PROMPT

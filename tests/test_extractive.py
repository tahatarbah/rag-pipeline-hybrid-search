from app.generate.extractive import extractive_answer, extractive_chunks


def test_extractive_cites_policy_id():
    answer = extractive_answer(
        "What is PTO-12?",
        [
            {
                "source": "hr-pto-policy.md",
                "text": (
                    "Policy PTO-12 is the canonical paid-time-off policy. "
                    "Full-time employees accrue 20 vacation days per calendar year. "
                    "The cafeteria serves lunch until 2pm."
                ),
            }
        ],
    )
    assert "PTO-12" in answer
    assert "canonical" in answer
    assert "[hr-pto-policy.md]" in answer
    assert "cafeteria" not in answer.lower()


def test_extractive_ignores_stopword_only_overlap():
    answer = extractive_answer(
        "What is PTO-12?",
        [
            {
                "source": "hr-pto-policy.md",
                "text": "Policy PTO-12 is the canonical paid-time-off policy.",
            },
            {
                "source": "security-soc2.md",
                "text": "There is currently one open exception on the billing exporter.",
            },
        ],
    )
    assert "PTO-12" in answer
    assert "billing exporter" not in answer


def test_extractive_empty_sources():
    assert "No indexed" in extractive_answer("hello", [])


def test_extractive_prefers_earlier_source_on_overlap_tie():
    answer = extractive_answer(
        "PTO-12 vacation",
        [
            {"source": "hr-pto-policy.md", "text": "Policy PTO-12 sets the vacation bank."},
            {"source": "wellness-leave-culture.md", "text": "Hallway talk about PTO-12 vacation is not policy."},
        ],
    )
    assert answer.index("hr-pto-policy.md") < answer.index("wellness-leave-culture.md")


def test_extractive_skips_lowercase_fragments():
    answer = extractive_answer(
        "PTO-12",
        [
            {
                "source": "hr-pto-policy.md",
                "text": (
                    "he full bank is unused leftover overlap. "
                    "Policy PTO-12 is the canonical paid-time-off policy."
                ),
            }
        ],
    )
    assert "canonical" in answer
    assert not answer.startswith("he full")


def test_extractive_chunks_yield_sentences():
    sources = [
        {
            "source": "hr-pto-policy.md",
            "text": (
                "Policy PTO-12 is the canonical paid-time-off policy. "
                "Full-time employees accrue 20 vacation days per calendar year."
            ),
        }
    ]
    parts = list(extractive_chunks("What is PTO-12?", sources))
    assert parts
    assert "PTO-12" in "".join(parts)

from pathlib import Path

from app.ingest.chunker import (
    attach_section_headings,
    chunk_documents,
    overlap_prefix,
    recursive_split,
)
from app.ingest.loaders import Document


def test_short_text_is_single_chunk():
    text = "Short policy line."
    assert recursive_split(text, chunk_size=800, overlap=120) == [text]


def test_empty_text_returns_nothing():
    assert recursive_split("   ", chunk_size=100, overlap=20) == []


def test_split_prefers_paragraphs_and_keeps_content():
    paragraphs = [f"Paragraph {i} discusses policy PTO-12 in some detail." for i in range(12)]
    text = "\n\n".join(paragraphs)
    chunks = recursive_split(text, chunk_size=120, overlap=20)
    assert len(chunks) > 1
    joined = " ".join(chunks)
    assert "Paragraph 0" in joined
    assert "Paragraph 11" in joined
    assert all(len(c) <= 160 for c in chunks)


def test_overlap_repeats_tail_of_previous_chunk():
    text = "alpha beta gamma delta epsilon zeta eta theta iota kappa"
    chunks = recursive_split(text, chunk_size=24, overlap=10, separators=[" ", ""])
    assert len(chunks) >= 2
    prefix = chunks[0][-10:]
    assert prefix.strip() in chunks[1] or any(
        token in chunks[1] for token in chunks[0].split()[-2:]
    )


def test_overlap_prefix_snaps_to_word_boundary():
    prev = "receive the full bank"
    assert overlap_prefix(prev, 10) == "full bank"
    assert overlap_prefix(prev, 10).split()[0] in prev.split()


def test_attach_section_headings_prefixes_later_chunks():
    parts = [
        "# Handbook\n\n## PTO-12: Paid Time Off\n\nFull-time employees accrue 20 days.",
        "Unused days roll over up to a cap of 5 days.",
    ]
    attached = attach_section_headings(parts)
    assert "PTO-12" in attached[1]
    assert attached[1].startswith("## PTO-12")


def test_chunk_documents_keeps_heading_on_overflow():
    body = "Full-time employees accrue twenty vacation days per calendar year. " * 30
    text = f"# Handbook\n\n## PTO-12: Paid Time Off\n\n{body}"
    docs = [
        Document(path=Path("hr-pto-policy.md"), source="hr-pto-policy.md", title="Handbook", text=text)
    ]
    chunks = chunk_documents(docs, chunk_size=160, overlap=20)
    assert len(chunks) >= 2
    assert any("PTO-12" in chunk.text for chunk in chunks[1:])

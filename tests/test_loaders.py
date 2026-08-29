from pathlib import Path

from app.ingest.loaders import load_documents, load_file


def test_load_seed_markdown():
    docs_dir = Path(__file__).resolve().parent.parent / "data" / "docs"
    docs = load_documents(docs_dir)
    sources = {d.source for d in docs}
    assert "hr-pto-policy.md" in sources
    assert "security-soc2.md" in sources
    pto = next(d for d in docs if d.source == "hr-pto-policy.md")
    assert "PTO-12" in pto.text


def test_load_txt_roundtrip(tmp_path: Path):
    path = tmp_path / "note.txt"
    path.write_text("Title line\n\nBody of the note.", encoding="utf-8")
    docs = load_file(path)
    assert len(docs) == 1
    assert docs[0].title == "Title line"
    assert "Body of the note." in docs[0].text

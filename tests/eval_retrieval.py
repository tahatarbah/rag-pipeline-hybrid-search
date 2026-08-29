"""Compare dense vs BM25 vs hybrid Hit@5 / Hit@1 on the Northstar corpus."""

from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

GOLD = [
    {
        "question": "What is PTO-12?",
        "relevant_files": ["hr-pto-policy.md"],
        "kind": "lexical",
    },
    {
        "question": "PTO-12",
        "relevant_files": ["hr-pto-policy.md"],
        "kind": "lexical",
    },
    {
        "question": "How many vacation days do full-time employees get?",
        "relevant_files": ["hr-pto-policy.md"],
        "kind": "semantic",
    },
    {
        "question": "SOC2 exception",
        "relevant_files": ["security-soc2.md"],
        "kind": "lexical",
    },
    {
        "question": "Who can approve a SOC 2 control exception?",
        "relevant_files": ["security-soc2.md"],
        "kind": "semantic",
    },
    {
        "question": "Who is on-call for production incidents?",
        "relevant_files": ["eng-oncall.md"],
        "kind": "semantic",
    },
    {
        "question": "What is the severity ladder for incidents?",
        "relevant_files": ["eng-oncall.md"],
        "kind": "semantic",
    },
    {
        "question": "expense report deadline",
        "relevant_files": ["finance-expenses.md"],
        "kind": "lexical",
    },
]


def first_relevant_rank(results: list[dict], relevant_files: list[str]) -> int | None:
    wanted = set(relevant_files)
    for i, item in enumerate(results, start=1):
        if item["source"] in wanted:
            return i
    return None


def evaluate() -> dict[str, float]:
    from app.retrieve.hybrid import HybridIndex

    index = HybridIndex()
    index.ingest()
    modes = ("dense", "bm25", "hybrid")
    print(f"{'question':<44} {'kind':<10} {'dense@1':<22} {'bm25@1':<22} {'hybrid@1'}")
    print("-" * 110)
    hit5 = {mode: 0 for mode in modes}
    hit1 = {mode: 0 for mode in modes}
    for item in GOLD:
        tops = []
        for mode in modes:
            results = index.query(item["question"], mode=mode, top_k=5)
            rank = first_relevant_rank(results, item["relevant_files"])
            top = results[0]["source"] if results else "—"
            if rank is not None:
                hit5[mode] += 1
                if rank == 1:
                    hit1[mode] += 1
            mark = f"{top}" + ("" if rank == 1 else f" (#{rank})")
            tops.append(mark[:20])
        print(
            f"{item['question'][:44]:<44} {item['kind']:<10} {tops[0]:<22} {tops[1]:<22} {tops[2]}"
        )
    n = len(GOLD)
    scores = {mode: hit5[mode] / n for mode in modes}
    for mode in modes:
        print(f"Hit@1 {mode:8} {hit1[mode]}/{n}   Hit@5 {hit5[mode]}/{n} = {scores[mode]:.0%}")
    return scores


def evaluate_space_acl() -> dict[str, bool]:
    """A Finance-only index must not return HR handbook chunks."""
    import shutil
    import tempfile

    hr_src = ROOT / "data" / "docs" / "hr-pto-policy.md"
    fin_src = ROOT / "data" / "docs" / "finance-expenses.md"
    from app.retrieve.hybrid import HybridIndex

    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        hr_root = tmp_path / "hr"
        fin_root = tmp_path / "fin"
        (hr_root / "docs").mkdir(parents=True)
        (fin_root / "docs").mkdir(parents=True)
        shutil.copy2(hr_src, hr_root / "docs" / hr_src.name)
        shutil.copy2(fin_src, fin_root / "docs" / fin_src.name)
        hr_index = HybridIndex(root=hr_root)
        fin_index = HybridIndex(root=fin_root)
        hr_index.ingest()
        fin_index.ingest()
        hr_hits = hr_index.query("What is PTO-12?", mode="hybrid", top_k=5)
        fin_hits = fin_index.query("What is PTO-12?", mode="hybrid", top_k=5)
        hr_ok = any(h["source"] == "hr-pto-policy.md" for h in hr_hits)
        fin_isolated = all(h["source"] != "hr-pto-policy.md" for h in fin_hits)
        return {"hr_finds_pto": hr_ok, "finance_cannot_see_hr": fin_isolated}


def main() -> None:
    evaluate()
    acl = evaluate_space_acl()
    print("ACL hr_finds_pto", acl["hr_finds_pto"], "finance_cannot_see_hr", acl["finance_cannot_see_hr"])


if __name__ == "__main__":
    main()


def test_eval_hybrid_hit_rate():
    if not os.getenv("RUN_EVAL"):
        import pytest

        pytest.skip("set RUN_EVAL=1 to run the embedding-backed retrieval eval")
    scores = evaluate()
    assert scores["hybrid"] >= scores["dense"]
    assert scores["hybrid"] >= 0.75


def test_eval_space_acl_isolation():
    acl = evaluate_space_acl()
    assert acl["hr_finds_pto"]
    assert acl["finance_cannot_see_hr"]

from app.retrieve.hybrid import diversify_by_source, looks_lexical, reciprocal_rank_fusion


def test_rrf_promotes_docs_that_rank_in_both_lists():
    dense = ["a", "b", "c"]
    bm25 = ["c", "d", "a"]
    scores = reciprocal_rank_fusion([dense, bm25], k=60)
    ordered = sorted(scores, key=scores.get, reverse=True)
    assert ordered[0] == "a"
    assert scores["a"] > scores["b"]
    assert scores["a"] > scores["d"]
    assert scores["c"] > scores["b"]


def test_rrf_single_list_preserves_order():
    ranking = ["x", "y", "z"]
    scores = reciprocal_rank_fusion([ranking], k=60)
    assert sorted(scores, key=scores.get, reverse=True) == ranking
    assert scores["x"] == 1 / 61
    assert scores["y"] == 1 / 62


def test_rrf_empty_lists():
    assert reciprocal_rank_fusion([[], []], k=60) == {}


def test_rrf_weights_promote_the_boosted_list():
    dense = ["finance", "hr"]
    bm25 = ["hr", "finance"]
    equal = reciprocal_rank_fusion([dense, bm25], k=60)
    lexical = reciprocal_rank_fusion([dense, bm25], k=60, weights=[0.7, 1.35])
    assert sorted(equal, key=equal.get, reverse=True)[0] in {"finance", "hr"}
    assert sorted(lexical, key=lexical.get, reverse=True)[0] == "hr"


def test_looks_lexical_detects_policy_ids():
    assert looks_lexical("What is PTO-12?")
    assert looks_lexical("SOC2 exception")
    assert looks_lexical("Who can approve a SOC 2 control exception?")
    assert not looks_lexical("How many vacation days do full-time employees get?")


def test_diversify_caps_chunks_per_source():
    results = [
        {"id": "a0", "source": "hr.md"},
        {"id": "a1", "source": "hr.md"},
        {"id": "a2", "source": "hr.md"},
        {"id": "b0", "source": "sec.md"},
    ]
    picked = diversify_by_source(results, top_k=4, max_per_source=2)
    assert [item["id"] for item in picked] == ["a0", "a1", "b0", "a2"]
    assert sum(1 for item in picked[:3] if item["source"] == "hr.md") == 2

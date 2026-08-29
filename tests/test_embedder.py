import numpy as np

from app.retrieve.embedder import embed_query, normalize_search_text


def test_normalize_aligns_soc2_spellings():
    compact = normalize_search_text("SOC2 exception").lower()
    spaced = normalize_search_text("SOC 2 control exception").lower()
    assert "soc2" in compact and "soc 2" in compact
    assert "soc2" in spaced and "soc 2" in spaced


def test_hash_embed_soc2_query_matches_compact_policy_id():
    query = np.asarray(embed_query("Who can approve a SOC 2 control exception?"))
    handbook = np.asarray(embed_query("SOC2 exception Dana Okonkwo Security Director"))
    vendor = np.asarray(embed_query("shipping exceptions invoice exceptions catalog exceptions"))
    assert float(query @ handbook) > float(query @ vendor)


def test_hash_embed_ignores_question_stopwords():
    query = np.asarray(embed_query("What is PTO-12?"))
    handbook = np.asarray(embed_query("Policy PTO-12 is the canonical paid-time-off policy"))
    finance = np.asarray(
        embed_query("Reimbursement is via the next payroll ACH. There is no petty cash.")
    )
    assert float(query @ handbook) > float(query @ finance)

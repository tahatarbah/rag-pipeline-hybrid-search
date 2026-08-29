from app.api.chat import _followup_query
from app.config import settings
from app.jobs import scan_inboxes
from app.spaces import drop_space_index, get_space_index, load_demo_docs, query_allowed_spaces, space_root
from tests.conftest import csrf_headers


def test_followup_query_includes_prior_turn():
    q = _followup_query("how many days?", [{"role": "user", "content": "What is PTO-12?"}])
    assert "PTO-12" in q
    assert "how many days?" in q


def test_setup_spaces_acl_and_usage(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "data_dir", tmp_path)
    import app.db as dbmod
    import app.spaces as spacesmod

    dbmod._INIT = False
    dbmod._INIT_PATH = None
    spacesmod._INDEXES.clear()

    from fastapi.testclient import TestClient
    from app.main import app

    client = TestClient(app)
    setup = client.post(
        "/api/auth/setup",
        json={
            "org_name": "Acme",
            "admin_email": "admin@acme.test",
            "admin_name": "Admin",
            "password": "password1",
            "load_demo": False,
        },
    )
    assert setup.status_code == 200, setup.text
    csrf = csrf_headers(client)
    spaces = setup.json()["spaces"]
    hr = next(s for s in spaces if s["name"] == "HR")
    eng = next(s for s in spaces if s["name"] == "Engineering")

    created = client.post(
        "/api/admin/users",
        headers=csrf,
        json={
            "email": "hr@acme.test",
            "name": "HR user",
            "password": "password1",
            "tier": "free",
        },
    )
    assert created.status_code == 200, created.text
    add = client.post(
        f"/api/spaces/{hr['id']}/members",
        headers=csrf,
        json={"email": "hr@acme.test", "role": "viewer"},
    )
    assert add.status_code == 200

    missing_csrf = client.post("/api/chat/threads", json={"space_id": hr["id"]})
    assert missing_csrf.status_code == 403

    login = client.post("/api/auth/login", json={"email": "hr@acme.test", "password": "password1"})
    assert login.status_code == 200
    csrf = csrf_headers(client)
    listed = client.get("/api/spaces").json()["spaces"]
    ids = {s["id"] for s in listed}
    assert hr["id"] in ids
    assert eng["id"] not in ids

    denied = client.get(f"/api/spaces/{eng['id']}/members")
    assert denied.status_code == 403

    copied = load_demo_docs(hr["id"])
    assert copied
    drop_space_index(hr["id"])
    get_space_index(hr["id"]).ingest()
    hr_hits = query_allowed_spaces([hr["id"]], "What is PTO-12?")
    assert any(h["source"] == "hr-pto-policy.md" for h in hr_hits)
    eng_hits = query_allowed_spaces([eng["id"]], "What is PTO-12?")
    assert not any(h.get("source") == "hr-pto-policy.md" for h in eng_hits)

    inbox = space_root(hr["id"]) / "inbox"
    inbox.mkdir(parents=True, exist_ok=True)
    (inbox / "watch-note.md").write_text("# Watch\nInbox file about PTO-12 extra.", encoding="utf-8")
    scan_inboxes()
    assert not (inbox / "watch-note.md").exists()
    assert (space_root(hr["id"]) / "docs" / "watch-note.md").exists()

    admin_login = client.post("/api/auth/login", json={"email": "admin@acme.test", "password": "password1"})
    assert admin_login.status_code == 200
    csrf = csrf_headers(client)
    ops = client.get("/api/admin/ops")
    assert ops.status_code == 200
    assert "usage" in ops.json()
    assert "health" in ops.json()

    premium = client.post(
        "/api/admin/models",
        headers=csrf,
        json={
            "display_name": "Paid demo",
            "provider": "extractive",
            "model_id": "extractive",
            "tier": "premium",
        },
    )
    assert premium.status_code == 200
    premium_id = premium.json()["id"]

    models = client.get("/api/admin/models").json()["models"]
    extractive = next(m for m in models if m["provider"] == "extractive")
    thread = client.post("/api/chat/threads", headers=csrf, json={"space_id": hr["id"]}).json()
    msg = client.post(
        f"/api/chat/threads/{thread['id']}/messages",
        headers=csrf,
        json={"content": "Hello docs", "model_id": extractive["id"], "space_id": hr["id"]},
    )
    assert msg.status_code == 200, msg.text
    audit_csv = client.get("/api/admin/audit.csv").text
    assert "cites:" in audit_csv
    stream = client.post(
        f"/api/chat/threads/{thread['id']}/messages/stream",
        headers=csrf,
        json={"content": "What is PTO-12?", "model_id": extractive["id"], "space_id": hr["id"]},
    )
    assert stream.status_code == 200, stream.text
    assert "data:" in stream.text

    gone = client.delete(f"/api/chat/threads/{thread['id']}", headers=csrf)
    assert gone.status_code == 200
    assert client.get(f"/api/chat/threads/{thread['id']}").status_code == 404

    usage = client.get("/api/admin/ops").json()["usage"]
    assert usage["calls"] >= 1

    csv = client.get("/api/admin/audit.csv")
    assert csv.status_code == 200
    assert "action" in csv.text

    removed = client.delete(
        f"/api/spaces/{hr['id']}/members/hr@acme.test",
        headers=csrf,
    )
    assert removed.status_code == 200

    client.post("/api/auth/login", json={"email": "hr@acme.test", "password": "password1"})
    csrf = csrf_headers(client)
    listed = client.get("/api/spaces").json()["spaces"]
    assert hr["id"] not in {s["id"] for s in listed}

    client.post("/api/auth/login", json={"email": "admin@acme.test", "password": "password1"})
    csrf = csrf_headers(client)
    client.post(
        f"/api/spaces/{hr['id']}/members",
        headers=csrf,
        json={"email": "hr@acme.test", "role": "viewer"},
    )
    client.post("/api/auth/login", json={"email": "hr@acme.test", "password": "password1"})
    csrf = csrf_headers(client)
    hr_thread = client.post("/api/chat/threads", headers=csrf, json={"space_id": hr["id"]}).json()
    blocked = client.post(
        f"/api/chat/threads/{hr_thread['id']}/messages",
        headers=csrf,
        json={"content": "try premium", "model_id": premium_id, "space_id": hr["id"]},
    )
    assert blocked.status_code == 403


def test_demo_pack_is_space_specific(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "data_dir", tmp_path)
    import app.db as dbmod

    dbmod._INIT = False
    dbmod._INIT_PATH = None
    copied = load_demo_docs("sp_hr_demo", pack="hr")
    assert "hr-pto-policy.md" in copied
    assert "hr-benefits.md" in copied
    assert "finance-expenses.md" not in copied
    eng = load_demo_docs("sp_eng_demo", pack="engineering")
    assert "eng-oncall.md" in eng
    assert "hr-pto-policy.md" not in eng

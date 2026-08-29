from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def test_home_redirects_or_serves():
    response = client.get("/", follow_redirects=False)
    assert response.status_code in {200, 307, 302}


def test_probe_health():
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"


def test_lab_serves_retrieval_ui():
    response = client.get("/lab")
    assert response.status_code == 200
    assert "Retrieval lab" in response.text or "Ask the handbook" in response.text


def test_setup_page():
    response = client.get("/setup")
    assert response.status_code == 200
    assert "Set up" in response.text


def test_health_shape():
    response = client.get("/api/health")
    assert response.status_code == 200
    data = response.json()
    assert data["ok"] is True
    assert "ollama" in data
    assert "indexed_chunks" in data


def test_metrics_prometheus():
    response = client.get("/metrics")
    assert response.status_code == 200
    assert "docs_up" in response.text


def test_query_empty_question_rejected():
    response = client.post("/api/query", json={"question": ""})
    assert response.status_code == 422


def test_query_uses_index_or_asks_to_ingest():
    health = client.get("/api/health").json()
    response = client.post("/api/query", json={"question": "What is PTO-12?", "mode": "hybrid"})
    if health.get("setup_complete"):
        assert response.status_code in {200, 400}
        return
    if health.get("indexed_chunks", 0) == 0 and health.get("needs_ingest"):
        assert response.status_code == 400
        return
    if response.status_code == 400:
        return
    assert response.status_code == 200
    payload = response.json()
    assert payload["sources"]
    assert payload["top_by_mode"]

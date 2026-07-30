"""API tests for the answer-strategy router on POST /api/cases."""
from __future__ import annotations

from fastapi.testclient import TestClient


def test_create_case_always_returns_routing(client: TestClient, admin_headers: dict):
    resp = client.post(
        "/api/cases",
        json={"prompt": "update the reorder point on SKU-EL-2210 from 150 to 200"},
        headers=admin_headers,
    )
    assert resp.status_code == 200, resp.text
    routing = resp.json()["routing"]
    assert routing is not None
    assert abs(routing["p_a"] + routing["p_b"] + routing["p_c"] - 1.0) < 1e-6
    assert 0.0 <= routing["confidence"] <= 1.0
    assert routing["strategy"] in ("deterministic", "pipeline", "rag")


def test_offcatalog_prompt_routes_rag_with_answer(client: TestClient, admin_headers: dict):
    # Pure gibberish matches no scenario keywords → both classifiers weak → C.
    resp = client.post(
        "/api/cases",
        json={"prompt": "zxqwv qppl flarp gibberish nonsense unrelated"},
        headers=admin_headers,
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["routing"]["strategy"] == "rag"
    assert body["rag"] is not None
    assert "answer" in body["rag"]


def test_hitl_prompt_does_not_route_rag(client: TestClient, admin_headers: dict):
    # A confident single non-deterministic scenario match must route to the
    # pipeline (B), never to RAG.
    resp = client.post(
        "/api/cases",
        json={"prompt": "Override the SC-TC-001 sanctions block"},
        headers=admin_headers,
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["routing"]["strategy"] != "rag"

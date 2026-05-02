"""Scenarios catalog + data sources happy paths."""
from __future__ import annotations

from fastapi.testclient import TestClient


def test_scenarios_lists_six_builtins(client: TestClient, admin_headers: dict) -> None:
    rows = client.get("/api/scenarios", headers=admin_headers).json()
    ids = {r["id"] for r in rows}
    for expected in ("SC-TC-007", "SC-TC-008", "SC-PP-007", "SC-LN-002",
                     "SC-LN-STATUS-009", "SC-PP-AUTO-014"):
        assert expected in ids, f"missing built-in scenario {expected}"


def test_data_sources_lists_defaults(client: TestClient, admin_headers: dict) -> None:
    rows = client.get("/api/data-sources", headers=admin_headers).json()
    ids = {r["id"] for r in rows}
    assert "products_csv" in ids
    assert "sanctions_csv" in ids
    assert "governance_sqlite" in ids


def test_test_endpoint_on_csv_source(client: TestClient, admin_headers: dict) -> None:
    resp = client.post("/api/data-sources/products_csv/test", headers=admin_headers)
    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is True
    assert len(body["sample_facts"]) >= 1
    assert any("P-EL-9001" in f["id"] for f in body["sample_facts"])


def test_save_custom_scenario(client: TestClient, admin_headers: dict) -> None:
    resp = client.post(
        "/api/scenarios",
        json={
            "title": "Outcome counts",
            "data_source": "governance_sqlite",
            "ontology_type": "OutcomeStat",
            "sql": "SELECT outcome AS id, outcome AS title, COUNT(*) AS summary FROM prior_cases GROUP BY outcome LIMIT :max_results",
            "match_keywords": ["outcome counts unique kw"],
        },
        headers=admin_headers,
    )
    assert resp.status_code == 200, resp.text
    sid = resp.json()["scenario_id"]
    assert sid.startswith("SC-CUSTOM-")

    # Now visible in the list
    rows = client.get("/api/scenarios", headers=admin_headers).json()
    assert any(r["id"] == sid for r in rows)


def test_keyword_conflict_returns_409(client: TestClient, admin_headers: dict) -> None:
    """Saving a scenario with overlapping keywords trips the conflict guard."""
    resp = client.post(
        "/api/scenarios",
        json={
            "title": "Trade override v2",
            "data_source": "governance_sqlite",
            "ontology_type": "PriorOverride",
            "sql": "SELECT 1 AS id, 'x' AS title, 'y' AS summary",
            "match_keywords": ["override", "sanction", "ofac"],
        },
        headers=admin_headers,
    )
    assert resp.status_code == 409
    assert resp.json()["detail"]["error"] == "keyword_conflict"


def test_run_query_smoke(client: TestClient, admin_headers: dict) -> None:
    resp = client.post(
        "/api/data-sources/governance_sqlite/run-query",
        json={
            "sql": "SELECT scenario_id, COUNT(*) AS n FROM prior_cases GROUP BY scenario_id LIMIT :max_results",
            "params": {},
            "limit": 5,
        },
        headers=admin_headers,
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is True
    assert body["columns"] == ["scenario_id", "n"]
    assert len(body["rows"]) >= 1


def test_run_query_refuses_multi_statement(client: TestClient, admin_headers: dict) -> None:
    resp = client.post(
        "/api/data-sources/governance_sqlite/run-query",
        json={"sql": "DROP TABLE prior_cases; SELECT 1"},
        headers=admin_headers,
    )
    body = resp.json()
    assert body["ok"] is False
    assert "multiple statements" in body["error"].lower()

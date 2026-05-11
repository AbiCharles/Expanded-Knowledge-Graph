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


def test_save_custom_scenario_returns_410(client: TestClient, admin_headers: dict) -> None:
    """Phase 3.C removed the legacy save-from-playground endpoint. The
    replacement is per-class chip generation via the ontology layer."""
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
    assert resp.status_code == 410, resp.text
    assert resp.json()["detail"]["error"] == "save_from_playground_removed"


def test_generate_lookup_chip_via_ontology(
    client: TestClient, admin_headers: dict
) -> None:
    """The replacement for save-from-playground: pick an ontology+class,
    click Generate lookup chip, get an SC-ONTO-* scenario."""
    # tcs_core is the seeded default ontology with a Product binding to products_csv.
    resp = client.post(
        "/api/ontologies/tcs_core/classes/Product/scenario",
        headers=admin_headers,
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["scenario_id"] == "SC-ONTO-tcs_core-Product"
    assert body["binding_count"] == 1

    # Now appears in the chip list
    rows = client.get("/api/scenarios", headers=admin_headers).json()
    assert any(r["id"] == "SC-ONTO-tcs_core-Product" for r in rows)

    # Removable
    resp = client.delete(
        "/api/ontologies/tcs_core/classes/Product/scenario",
        headers=admin_headers,
    )
    assert resp.status_code == 200, resp.text


def test_legacy_queries_block_in_scenario_yaml_raises() -> None:
    """Phase 3.C hard-removed `queries:` from the scenario schema. Loading
    a YAML that still uses it must raise a ScenarioSchemaError with the
    migration recipe in the message."""
    import pytest as _pt
    from backend.scenario_loader import ScenarioRegistry, ScenarioSchemaError

    legacy = {
        "id": "SC-LEGACY-FOO",
        "title": "Legacy Foo",
        "domain": "Test",
        "autonomous": True,
        "actor_id": "agent-test",
        "operator_role": {"label": "Operator", "name": "tester"},
        "action_type": "data_lookup",
        "action_payload": {},
        "match_keywords": ["legacy foo"],
        "interpreted_as": "test",
        "clarifying_question": "go?",
        "stages": {
            "agent_intake": {"binder": "x", "facts": []},
            "proposal": {
                "binder": "y",
                "queries": [
                    {"data_source": "products_csv", "ontology_type": "Product",
                     "filter": {}}
                ],
            },
        },
    }
    reg = ScenarioRegistry({}, directory=None)
    with _pt.raises(ScenarioSchemaError) as exc:
        reg.register(legacy, persist=False)
    assert "queries:" in str(exc.value)
    assert "ontology_queries:" in str(exc.value)


def test_generate_lookup_chip_rejects_unmapped_class(
    client: TestClient, admin_headers: dict
) -> None:
    """Generate-chip must refuse classes with no source bindings."""
    # Upload a fresh ontology with a class but no mapping.
    client.post(
        "/api/ontologies/raw",
        json={"document": {
            "id": "ephemeral_v1",
            "title": "Ephemeral",
            "classes": {"Foo": {"attributes": [{"name": "id", "identifier": True}]}},
        }},
        headers=admin_headers,
    )
    resp = client.post(
        "/api/ontologies/ephemeral_v1/classes/Foo/scenario",
        headers=admin_headers,
    )
    assert resp.status_code == 400
    assert "no source bindings" in resp.json()["detail"]


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

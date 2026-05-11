"""Phase 3.D: NL→ontology fallback in the main composer.

When the operator opts in via `try_ontology_fallback=true` AND the scenario
classifier finds no match, the cases endpoint should:

  1. Run `parse_nl_query` against every loaded ontology.
  2. Pick the first parsed class that has a non-empty mapping.
  3. Synthesize an `SC-ADHOC-<case-id>` autonomous scenario in-memory.
  4. Return it as the case's scenario_id so the orchestrator runs it
     through the existing OntologyResolver path.

These tests exercise that flow via the public REST API.
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient


def _post_case(
    client: TestClient,
    headers: dict,
    prompt: str,
    *,
    try_ontology_fallback: bool = False,
) -> dict:
    resp = client.post(
        "/api/cases",
        headers=headers,
        json={"prompt": prompt, "try_ontology_fallback": try_ontology_fallback},
    )
    assert resp.status_code == 200, resp.text
    return resp.json()


@pytest.fixture()
def widget_ontology(client: TestClient, admin_headers: dict) -> dict:
    """Upload a one-class ontology + mapping where the class name doesn't
    collide with any seeded scenario's keywords. This isolates the fallback
    tests from the rest of the demo catalog (which has chips for Product,
    Override, Sanction, Shipment, etc.). Returns ids."""
    # The Widget class maps to products_csv — products_csv is the seeded
    # CSV source used elsewhere in the test suite, so we know it returns
    # ≥3 rows on a no-filter query.
    onto_doc = {
        "id": "fallback_demo_v1",
        "title": "Fallback Demo",
        "classes": {
            "Widget": {
                "attributes": [
                    {"name": "widget_id", "identifier": True},
                    {"name": "name"},
                    {"name": "category"},
                ],
            },
        },
    }
    client.post(
        "/api/ontologies/raw",
        headers=admin_headers,
        json={"document": onto_doc},
    )
    mapping_doc = {
        "ontology_id": "fallback_demo_v1",
        "mappings": {
            "Widget": {
                "sources": [
                    {
                        "data_source": "products_csv",
                        "identifier_column": "product_id",
                        "attribute_map": {
                            "widget_id": "product_id",
                            "name": "name",
                            "category": "category",
                        },
                    }
                ]
            }
        },
    }
    client.put(
        "/api/ontologies/fallback_demo_v1/mappings",
        headers=admin_headers,
        json={"document": mapping_doc},
    )
    return {"ontology_id": "fallback_demo_v1", "class": "Widget"}


# =============================================================================
# Off by default — the existing dead-end path is preserved
# =============================================================================
def test_no_fallback_when_flag_off(
    client: TestClient, admin_headers: dict, widget_ontology: dict
) -> None:
    """Prompt that won't match any scenario AND no opt-in → no scenario_id.
    Same behaviour as before Phase 3.D."""
    body = _post_case(client, admin_headers, "show me widgets")
    # Without try_ontology_fallback=True, the fallback never runs.
    assert body["scenario_id"] is None or not body["scenario_id"].startswith("SC-ADHOC-")


# =============================================================================
# Existing scenario classification still wins
# =============================================================================
def test_classifier_wins_even_with_fallback_enabled(
    client: TestClient, admin_headers: dict
) -> None:
    """When the classifier finds a match, the fallback shouldn't fire even
    if the operator opted in. This relies on the keyword-fallback
    classifier (LLM_PROVIDER=fake in conftest) matching SC-LN-STATUS-009's
    keywords."""
    body = _post_case(
        client, admin_headers,
        "What's the current ETA on shipment S-700499?",
        try_ontology_fallback=True,
    )
    assert body["scenario_id"] == "SC-LN-STATUS-009"
    assert not body["scenario_id"].startswith("SC-ADHOC-")


# =============================================================================
# Fallback fires when classifier finds nothing AND mapping exists
# =============================================================================
def test_fallback_synthesizes_adhoc_scenario(
    client: TestClient, admin_headers: dict, widget_ontology: dict
) -> None:
    """The widget_ontology fixture uploads a Widget class with a mapping to
    products_csv. "Widget" doesn't match any seeded scenario's keywords,
    so classification finds nothing → fallback fires → SC-ADHOC synth."""
    body = _post_case(
        client, admin_headers,
        "show me widgets",
        try_ontology_fallback=True,
    )
    assert body["scenario_id"] is not None
    assert body["scenario_id"].startswith("SC-ADHOC-"), body
    assert "fallback_demo_v1.Widget" in body["clarifying_question"]


def test_fallback_runs_case_to_completion(
    client: TestClient, admin_headers: dict, widget_ontology: dict
) -> None:
    """End-to-end: synthesized SC-ADHOC scenario should auto-execute and
    bind facts via the ontology layer."""
    import time

    body = _post_case(
        client, admin_headers,
        "show me widgets",
        try_ontology_fallback=True,
    )
    assert body["scenario_id"].startswith("SC-ADHOC-")
    case_id = body["case_id"]

    # Confirm to kick the orchestrator off (autonomous → auto_execute)
    resp = client.post(
        f"/api/cases/{case_id}/confirm",
        headers=admin_headers,
        json={"scenario_id": body["scenario_id"]},
    )
    assert resp.status_code == 200, resp.text

    # Poll for completion
    deadline = time.time() + 5.0
    while time.time() < deadline:
        case = client.get(f"/api/cases/{case_id}", headers=admin_headers).json()
        if case.get("phase") == "complete":
            break
        time.sleep(0.1)
    assert case["phase"] == "complete", case
    assert case["decision_kind"] == "auto_execute"

    # Proposal stage should carry Widget-tagged facts coming from products_csv
    proposal_facts = next(
        s["facts"] for s in case["stages"] if s["stage"] == "proposal"
    )
    assert any(
        f.get("via_ontology") == "fallback_demo_v1.Widget" for f in proposal_facts
    ), proposal_facts
    assert any(
        f.get("via_source_binding") == "products_csv" for f in proposal_facts
    ), proposal_facts


# =============================================================================
# Ad-hoc scenarios are hidden from the chip catalog
# =============================================================================
def test_adhoc_scenarios_filtered_from_chip_list(
    client: TestClient, admin_headers: dict, widget_ontology: dict
) -> None:
    """SC-ADHOC-* lives in-memory but must not appear as a suggested chip
    on the operator console — they're per-case ephemerals."""
    body = _post_case(
        client, admin_headers,
        "show me widgets",
        try_ontology_fallback=True,
    )
    assert body["scenario_id"].startswith("SC-ADHOC-")

    rows = client.get("/api/scenarios", headers=admin_headers).json()
    assert all(
        not r["id"].startswith("SC-ADHOC-") for r in rows
    ), f"ad-hoc scenario leaked into chip list: {[r['id'] for r in rows]}"


# =============================================================================
# No mapping → no fallback (don't synthesize a useless scenario)
# =============================================================================
def test_fallback_skips_class_with_no_mapping(
    client: TestClient, admin_headers: dict
) -> None:
    """Upload an ontology with a class that has no source binding. Even
    if the NL parser matches the class, the fallback should skip it
    rather than create a scenario that would auto-execute and bind zero
    facts."""
    client.post(
        "/api/ontologies/raw",
        headers=admin_headers,
        json={"document": {
            "id": "lonely_v1",
            "title": "Lonely",
            "classes": {
                "Lonely": {"attributes": [{"name": "id", "identifier": True}]},
            },
        }},
    )
    # No PUT mapping for Lonely.

    body = _post_case(
        client, admin_headers,
        "show me lonelys",
        try_ontology_fallback=True,
    )
    # No scenario should fire — fallback skipped, classifier had nothing.
    assert body["scenario_id"] is None or not body["scenario_id"].startswith("SC-ADHOC-")

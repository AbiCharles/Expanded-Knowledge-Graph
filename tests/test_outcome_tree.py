"""API tests for POST /api/graph/outcome-tree."""
from __future__ import annotations

import math

from fastapi.testclient import TestClient

# Two real shipped scenarios: a HITL supply-assurance case and the
# autonomous PO-release case (with risk_bands).
HITL_ID = "SC-PP-AERONOVA-026"
AUTO_ID = "SC-PP-AUTO-PO-RELEASE-027"


def test_outcome_tree_requires_auth(client: TestClient):
    resp = client.post(
        "/api/graph/outcome-tree",
        json={"question": "q", "scenario_ids": [HITL_ID]},
    )
    assert resp.status_code == 401


def test_outcome_tree_single_scenario(client: TestClient, admin_headers: dict):
    resp = client.post(
        "/api/graph/outcome-tree",
        json={"question": "Assess the supply assurance case", "scenario_ids": [HITL_ID]},
        headers=admin_headers,
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["question"]
    assert body["scenario_ids"] == [HITL_ID]
    assert body["nodes"] and body["edges"] and body["outcomes"]
    # There is exactly one question root.
    assert sum(1 for n in body["nodes"] if n["kind"] == "question") == 1
    # Probabilities are conserved.
    assert math.isclose(body["stats"]["total_probability"], 1.0, abs_tol=1e-6)
    # Every outcome carries a probability in [0, 1].
    for o in body["outcomes"]:
        assert 0.0 <= o["probability"] <= 1.0
    # Outcomes are ranked most-probable first.
    probs = [o["probability"] for o in body["outcomes"]]
    assert probs == sorted(probs, reverse=True)


def test_outcome_tree_composes_two_scenarios(client: TestClient, admin_headers: dict):
    resp = client.post(
        "/api/graph/outcome-tree",
        json={
            "question": "If the supplier fails, what happens to the auto-release?",
            "scenario_ids": [HITL_ID, AUTO_ID],
            "context": {"reliability_score": 0.7},
        },
        headers=admin_headers,
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["scenario_ids"] == [HITL_ID, AUTO_ID]
    # Both scenarios contribute scenario_step nodes.
    step_scenarios = {n["scenario_id"] for n in body["nodes"] if n["kind"] == "scenario_step"}
    assert step_scenarios == {HITL_ID, AUTO_ID}
    # The autonomous scenario contributes an authority gate.
    assert any(n["label"] == "Authority gate" for n in body["nodes"])
    # Edges carry a probability + a basis explaining the weight.
    assert all("probability" in e and "basis" in e for e in body["edges"])
    assert math.isclose(body["stats"]["total_probability"], 1.0, abs_tol=1e-6)


def test_outcome_tree_unknown_scenario_404(client: TestClient, admin_headers: dict):
    resp = client.post(
        "/api/graph/outcome-tree",
        json={"question": "q", "scenario_ids": ["SC-NOPE-999"]},
        headers=admin_headers,
    )
    assert resp.status_code == 404


def test_outcome_tree_rejects_empty_scenarios(client: TestClient, admin_headers: dict):
    resp = client.post(
        "/api/graph/outcome-tree",
        json={"question": "q", "scenario_ids": []},
        headers=admin_headers,
    )
    assert resp.status_code == 422

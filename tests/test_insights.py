"""Phase 3a — pattern-mining endpoint tests.

Seed a small captured-highlights set, hit /insights/patterns, and
assert the aggregation logic computes the right counts + percentages.
"""
from __future__ import annotations

import json
from datetime import datetime

from fastapi.testclient import TestClient


def _seed_case(client: TestClient, conn, case_id: str, scenario_id: str,
               decision_kind: str) -> None:
    """Insert a minimal CaseRow directly via SQL — we don't need the
    orchestrator's lineage; just the pieces the aggregator joins on."""
    conn.execute(
        """
        INSERT INTO cases (case_id, scenario_id, scenario_version, phase,
                           decision_kind, prompt, created_at, updated_at, payload)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            case_id, scenario_id, 1, "complete", decision_kind, "p",
            datetime.utcnow(), datetime.utcnow(),
            json.dumps({"case_id": case_id, "scenario_id": scenario_id,
                        "decision_kind": decision_kind}),
        ),
    )


def _seed_highlight(conn, case_id: str, scenario_id: str,
                    decision_kind: str, ontology_type: str, fact_id: str,
                    position: int = 0) -> None:
    conn.execute(
        """
        INSERT INTO case_highlighted_facts
            (case_id, scenario_id, scenario_version, decision_kind,
             fact_source, fact_ontology_type, fact_id, fact_title,
             position, highlighted_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            case_id, scenario_id, 1, decision_kind,
            "graph:neo4j_default", ontology_type, fact_id,
            f"Title for {fact_id}", position, datetime.utcnow(),
        ),
    )


def _seed_full(client: TestClient) -> None:
    """Three rejects of SC-PP-008 — all driven by SanctionsProximity;
    two also flag CarrierExposure. One approve of SC-PP-008 — driven
    by Product. Result: SanctionsProximity has 100% share of the
    reject decisions; 75% of all decisions on SC-PP-008."""
    state = client.app.state.app_state
    db = state.database
    raw = db.engine.raw_connection()
    try:
        cur = raw.cursor()
        for case_id, decision, ots in (
            ("C-001", "reject",  [("SanctionsProximity", "SUP-001-PROX"),
                                   ("CarrierExposure", "SUP-001-CARRIER")]),
            ("C-002", "reject",  [("SanctionsProximity", "SUP-002-PROX")]),
            ("C-003", "reject",  [("SanctionsProximity", "SUP-003-PROX"),
                                   ("CarrierExposure", "SUP-003-CARRIER")]),
            ("C-004", "approve", [("Product", "P-EL-9001")]),
        ):
            _seed_case(client, cur, case_id, "SC-PP-008", decision)
            for pos, (ot, fid) in enumerate(ots):
                _seed_highlight(cur, case_id, "SC-PP-008", decision, ot, fid, pos)
        raw.commit()
    finally:
        raw.close()


# -----------------------------------------------------------------------------
# Tests
# -----------------------------------------------------------------------------
def test_patterns_aggregates_distinct_cases_per_driver(
    client: TestClient, admin_headers: dict
) -> None:
    _seed_full(client)
    resp = client.get("/api/insights/patterns", headers=admin_headers)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    scenarios = {s["scenario_id"]: s for s in body["scenarios"]}
    assert "SC-PP-008" in scenarios
    sc = scenarios["SC-PP-008"]
    assert sc["total_decided_cases"] == 4

    by_key = {(p["decision_kind"], p["fact_ontology_type"]): p
              for p in sc["patterns"]}

    # SanctionsProximity drove all 3 rejects.
    sp = by_key[("reject", "SanctionsProximity")]
    assert sp["case_count"] == 3
    assert sp["share_of_decision_kind"] == 100.0
    assert sp["share_of_decisions"] == 75.0

    # CarrierExposure drove 2 of 3 rejects.
    ce = by_key[("reject", "CarrierExposure")]
    assert ce["case_count"] == 2
    assert ce["share_of_decision_kind"] == round(100.0 * 2 / 3, 1)
    assert ce["share_of_decisions"] == 50.0


def test_patterns_includes_sample_fact_ids(
    client: TestClient, admin_headers: dict
) -> None:
    _seed_full(client)
    body = client.get("/api/insights/patterns", headers=admin_headers).json()
    sc = next(s for s in body["scenarios"] if s["scenario_id"] == "SC-PP-008")
    sp = next(p for p in sc["patterns"]
              if (p["decision_kind"], p["fact_ontology_type"])
              == ("reject", "SanctionsProximity"))
    assert sorted(sp["sample_fact_ids"]) == ["SUP-001-PROX", "SUP-002-PROX", "SUP-003-PROX"]


def test_patterns_sorted_by_case_count_desc(
    client: TestClient, admin_headers: dict
) -> None:
    _seed_full(client)
    body = client.get("/api/insights/patterns", headers=admin_headers).json()
    sc = next(s for s in body["scenarios"] if s["scenario_id"] == "SC-PP-008")
    counts = [p["case_count"] for p in sc["patterns"]]
    assert counts == sorted(counts, reverse=True)


def test_patterns_admin_only(client: TestClient, admin_headers: dict) -> None:
    # Admin creates a non-admin user; the user logs in; expect 403.
    resp = client.post(
        "/api/auth/register",
        json={"username": "op1", "password": "pw1234"},
        headers=admin_headers,
    )
    assert resp.status_code == 200, resp.text
    resp = client.post(
        "/api/auth/login",
        data={"username": "op1", "password": "pw1234"},
        headers={"content-type": "application/x-www-form-urlencoded"},
    )
    tok = resp.json()["access_token"]
    resp = client.get(
        "/api/insights/patterns",
        headers={"Authorization": f"Bearer {tok}"},
    )
    assert resp.status_code == 403


def test_patterns_empty_when_no_highlights(
    client: TestClient, admin_headers: dict
) -> None:
    body = client.get("/api/insights/patterns", headers=admin_headers).json()
    assert body["scenarios"] == []


# =============================================================================
# Phase 3b — promote / demote
# =============================================================================
def _scenario_state(client: TestClient, scenario_id: str) -> dict:
    state = client.app.state.app_state
    return state.scenarios.get(scenario_id) or {}


def test_promote_writes_pattern_and_bumps_version(
    client: TestClient, admin_headers: dict
) -> None:
    _seed_full(client)
    sc_before = _scenario_state(client, "SC-PP-008")
    version_before = sc_before.get("version", 1)

    resp = client.post(
        "/api/insights/patterns/promote",
        json={
            "scenario_id": "SC-PP-008",
            "decision_kind": "reject",
            "fact_ontology_type": "SanctionsProximity",
        },
        headers=admin_headers,
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["scenario_id"] == "SC-PP-008"
    assert body["version"] == version_before + 1
    assert body["pattern_id"].startswith("auto-")
    assert body["replaced"] is False

    sc_after = _scenario_state(client, "SC-PP-008")
    promoted = sc_after.get("auto_promoted_patterns") or []
    assert len(promoted) == 1
    entry = promoted[0]
    assert entry["decision_kind"] == "reject"
    assert entry["trigger"]["ontology_type"] == "SanctionsProximity"
    assert entry["metadata"]["source_case_count"] == 3
    assert entry["metadata"]["promoted_by"] == "admin"


def test_promote_idempotent_replaces_existing_pattern(
    client: TestClient, admin_headers: dict
) -> None:
    _seed_full(client)
    first = client.post(
        "/api/insights/patterns/promote",
        json={"scenario_id": "SC-PP-008", "decision_kind": "reject",
              "fact_ontology_type": "SanctionsProximity"},
        headers=admin_headers,
    ).json()
    second = client.post(
        "/api/insights/patterns/promote",
        json={"scenario_id": "SC-PP-008", "decision_kind": "reject",
              "fact_ontology_type": "SanctionsProximity",
              "suggested_rationale": "Override the rationale this time."},
        headers=admin_headers,
    ).json()
    # Same pattern id, second bump replaces the entry rather than appending.
    assert first["pattern_id"] == second["pattern_id"]
    assert second["replaced"] is True
    promoted = _scenario_state(client, "SC-PP-008").get("auto_promoted_patterns") or []
    assert len(promoted) == 1
    assert promoted[0]["suggested_rationale"] == "Override the rationale this time."


def test_promote_blocked_by_case_count_guardrail(
    client: TestClient, admin_headers: dict
) -> None:
    _seed_full(client)
    resp = client.post(
        "/api/insights/patterns/promote",
        json={"scenario_id": "SC-PP-008", "decision_kind": "approve",
              "fact_ontology_type": "Product",
              "min_case_count": 5},  # we only have 1 such case
        headers=admin_headers,
    )
    assert resp.status_code == 409, resp.text
    assert "case_count" in resp.text


def test_promote_blocked_by_share_guardrail(
    client: TestClient, admin_headers: dict
) -> None:
    _seed_full(client)
    resp = client.post(
        "/api/insights/patterns/promote",
        json={"scenario_id": "SC-PP-008", "decision_kind": "reject",
              "fact_ontology_type": "CarrierExposure",
              # CarrierExposure shows on 2/3 rejects = 66.7% — below 90%
              "min_share_of_kind_pct": 90.0},
        headers=admin_headers,
    )
    assert resp.status_code == 409
    assert "share_of_decision_kind" in resp.text


def test_promote_404_on_unknown_scenario(
    client: TestClient, admin_headers: dict
) -> None:
    resp = client.post(
        "/api/insights/patterns/promote",
        json={"scenario_id": "SC-NOPE", "decision_kind": "reject",
              "fact_ontology_type": "X"},
        headers=admin_headers,
    )
    assert resp.status_code == 404


def test_demote_removes_pattern_and_bumps_version(
    client: TestClient, admin_headers: dict
) -> None:
    _seed_full(client)
    promoted = client.post(
        "/api/insights/patterns/promote",
        json={"scenario_id": "SC-PP-008", "decision_kind": "reject",
              "fact_ontology_type": "SanctionsProximity"},
        headers=admin_headers,
    ).json()
    pid = promoted["pattern_id"]
    pre_v = _scenario_state(client, "SC-PP-008")["version"]

    resp = client.post(
        "/api/insights/patterns/demote",
        json={"scenario_id": "SC-PP-008", "pattern_id": pid},
        headers=admin_headers,
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["remaining_patterns"] == 0
    assert body["version"] == pre_v + 1
    assert (_scenario_state(client, "SC-PP-008").get("auto_promoted_patterns") or []) == []


def test_demote_404_on_unknown_pattern_id(
    client: TestClient, admin_headers: dict
) -> None:
    resp = client.post(
        "/api/insights/patterns/demote",
        json={"scenario_id": "SC-PP-008", "pattern_id": "auto-doesnotexist"},
        headers=admin_headers,
    )
    assert resp.status_code == 404


def test_promote_and_demote_are_admin_only(
    client: TestClient, admin_headers: dict
) -> None:
    # Create a non-admin user via the admin
    resp = client.post(
        "/api/auth/register",
        json={"username": "op2", "password": "pw1234"},
        headers=admin_headers,
    )
    assert resp.status_code == 200, resp.text
    resp = client.post(
        "/api/auth/login",
        data={"username": "op2", "password": "pw1234"},
        headers={"content-type": "application/x-www-form-urlencoded"},
    )
    tok = resp.json()["access_token"]

    promote_resp = client.post(
        "/api/insights/patterns/promote",
        json={"scenario_id": "SC-PP-008", "decision_kind": "reject",
              "fact_ontology_type": "SanctionsProximity"},
        headers={"Authorization": f"Bearer {tok}"},
    )
    assert promote_resp.status_code == 403
    demote_resp = client.post(
        "/api/insights/patterns/demote",
        json={"scenario_id": "SC-PP-008", "pattern_id": "x"},
        headers={"Authorization": f"Bearer {tok}"},
    )
    assert demote_resp.status_code == 403

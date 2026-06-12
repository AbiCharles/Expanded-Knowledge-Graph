"""Phase 2 — structured override capture.

Unit-level tests for the persistence layer + a smoke pass through the
decision endpoint's validation. Full orchestrator integration is
covered by the in-process happy-path test in test_cases.py (which
already exercises the decision path end-to-end).
"""
from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from backend.case_record import CaseRecord
from backend.persistence.case_store import PersistentCaseStore
from backend.persistence.db import Database


# -----------------------------------------------------------------------------
# Persistence — write/read round-trip
# -----------------------------------------------------------------------------
def _build_store(tmp_path: Path) -> PersistentCaseStore:
    db = Database(tmp_path / "phase2.sqlite")
    return PersistentCaseStore(db)


def test_write_highlights_round_trips(tmp_path: Path) -> None:
    store = _build_store(tmp_path)
    rec = CaseRecord(
        case_id="C-001",
        prompt="onboard hemlock",
        scenario_id="SC-PP-008",
        scenario_version=2,
        decision_kind="reject",
        highlighted_fact_refs=[
            {"source": "sqlite:governance_sqlite", "ontology_type": "PriorOverride",
             "id": "C-PP-007-001", "title": "Prior reject"},
            {"source": "graph:neo4j_default", "ontology_type": "SanctionsProximity",
             "id": "SDN-12345", "title": "3-hop ownership"},
        ],
    )
    store.save(rec)
    store.write_highlighted_facts(rec)

    rows = store.read_highlighted_facts("C-001")
    assert [r["id"] for r in rows] == ["C-PP-007-001", "SDN-12345"]
    assert [r["position"] for r in rows] == [0, 1]
    assert rows[0]["ontology_type"] == "PriorOverride"
    assert rows[1]["source"] == "graph:neo4j_default"


def test_rewriting_highlights_replaces_prior_rows(tmp_path: Path) -> None:
    """Replays / admin edits must not pile up duplicate rows."""
    store = _build_store(tmp_path)
    rec = CaseRecord(
        case_id="C-RE",
        prompt="p",
        scenario_id="SC-PP-008",
        scenario_version=1,
        decision_kind="approve",
        highlighted_fact_refs=[
            {"source": "csv:products_csv", "ontology_type": "Product", "id": "P-1", "title": "P1"},
        ],
    )
    store.save(rec)
    store.write_highlighted_facts(rec)

    rec.highlighted_fact_refs = [
        {"source": "csv:products_csv", "ontology_type": "Product", "id": "P-2", "title": "P2"},
        {"source": "csv:products_csv", "ontology_type": "Product", "id": "P-3", "title": "P3"},
    ]
    store.write_highlighted_facts(rec)

    rows = store.read_highlighted_facts("C-RE")
    assert [r["id"] for r in rows] == ["P-2", "P-3"]
    assert all(r["position"] in (0, 1) for r in rows)


def test_undecided_case_does_not_write_rows(tmp_path: Path) -> None:
    """Decided cases only — until decision_kind is set, the denorm table
    stays empty. Otherwise an interim save mid-orchestration would emit
    pre-decision rows."""
    store = _build_store(tmp_path)
    rec = CaseRecord(
        case_id="C-UND",
        prompt="p",
        scenario_id="SC-PP-008",
        scenario_version=1,
        decision_kind=None,
        highlighted_fact_refs=[
            {"source": "csv:products_csv", "ontology_type": "Product", "id": "P-1"},
        ],
    )
    store.save(rec)
    store.write_highlighted_facts(rec)
    assert store.read_highlighted_facts("C-UND") == []


def test_highlighted_fact_refs_survive_case_payload_roundtrip(tmp_path: Path) -> None:
    """The optional list lives on CaseRecord.payload; rehydration after a
    process restart must preserve it."""
    db = Database(tmp_path / "phase2-rt.sqlite")
    store = PersistentCaseStore(db)
    rec = CaseRecord(
        case_id="C-RT",
        prompt="p",
        scenario_id="SC-PP-008",
        scenario_version=2,
        decision_kind="reject",
        highlighted_fact_refs=[
            {"source": "csv:products_csv", "ontology_type": "Product", "id": "P-7"},
        ],
    )
    store.save(rec)

    # New store on the same DB → rehydrates from sqlite.
    store2 = PersistentCaseStore(db)
    rehydrated = store2.get("C-RT")
    assert rehydrated is not None
    assert rehydrated.highlighted_fact_refs == [
        {"source": "csv:products_csv", "ontology_type": "Product", "id": "P-7"},
    ]


# -----------------------------------------------------------------------------
# Decision API — validation
# -----------------------------------------------------------------------------
def test_decision_endpoint_rejects_more_than_three_highlights(
    client: TestClient, admin_headers: dict
) -> None:
    """The MAX cap is enforced at the API boundary, not just in the UI."""
    # We don't have an open ticket here; the cap check fires before the
    # ticket-existence check, so any plausible request body proves the
    # validator runs.
    refs = [
        {"source": f"s{i}", "ontology_type": "X", "id": f"id-{i}"}
        for i in range(4)
    ]
    resp = client.post(
        "/api/decisions/nonexistent-ticket",
        json={
            "decision": "reject",
            "rationale": "r",
            "highlighted_fact_refs": refs,
        },
        headers=admin_headers,
    )
    # 400 for the cap; 404 only if we accidentally passed cap-check.
    assert resp.status_code == 400, resp.text
    assert "highlighted_fact_refs" in resp.text or "at most" in resp.text


def test_decision_endpoint_rejects_malformed_highlight_ref(
    client: TestClient, admin_headers: dict
) -> None:
    """Pydantic shape: source/ontology_type/id are required non-empty strings."""
    resp = client.post(
        "/api/decisions/nonexistent-ticket",
        json={
            "decision": "reject",
            "rationale": "r",
            "highlighted_fact_refs": [{"source": "", "ontology_type": "X", "id": "y"}],
        },
        headers=admin_headers,
    )
    assert resp.status_code == 422, resp.text


def test_highlights_endpoint_returns_empty_for_pre_phase2_case(
    client: TestClient, admin_headers: dict
) -> None:
    """A case that never had highlights stamped should return [] cleanly."""
    # Create a case so we have a known case_id to query.
    resp = client.post(
        "/api/cases",
        json={"prompt": "list products"},
        headers=admin_headers,
    )
    assert resp.status_code in (200, 201), resp.text
    case_id = resp.json()["case_id"]

    resp = client.get(f"/api/cases/{case_id}/highlights", headers=admin_headers)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["case_id"] == case_id
    assert body["highlighted_fact_refs"] == []

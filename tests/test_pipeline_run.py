"""Chained execution tests for run_pipeline (Phase 2).

`run_case` is stubbed so the tests drive the pipeline's branching logic
deterministically without the full binding / HITL machinery (that path is
covered by test_cases.py).
"""
from __future__ import annotations

import time

from fastapi.testclient import TestClient

# Keyword-matches the supply-assurance scenario AND the autonomous PO-release
# scenario, so the keyword-chain planner returns a 2+ step pipeline.
MULTI_PROMPT = "Run supply assurance for Northwind Forge, then auto-release the bulk PO to SUP-021"


def _stub_run_case(monkeypatch, script: dict[int, str]):
    """Replace orchestrator.run_case with one that files a scripted decision."""
    import backend.pipeline_orchestrator as po

    async def fake_run_case(state, case):
        case.decision_kind = script.get(case.pipeline_step, "approve")
        case.phase = "complete"
        state.cases.save(case)

    monkeypatch.setattr(po.orchestrator, "run_case", fake_run_case)


def _make_pipeline(client: TestClient, headers: dict) -> dict:
    create = client.post("/api/cases", json={"prompt": MULTI_PROMPT}, headers=headers).json()
    assert create["pipeline"] is not None, "expected a multi-scenario pipeline"
    assert len(create["pipeline"]["steps"]) >= 2
    return create["pipeline"]


def _run_to_completion(client: TestClient, headers: dict, pid: str) -> dict:
    r = client.post(f"/api/pipelines/{pid}/confirm", headers=headers)
    assert r.status_code == 200, r.text
    for _ in range(60):
        p = client.get(f"/api/pipelines/{pid}", headers=headers).json()
        if p["status"] in ("complete", "error"):
            return p
        time.sleep(0.05)
    raise AssertionError("pipeline did not finish")


def test_pipeline_stops_on_reject(client: TestClient, admin_headers: dict, monkeypatch):
    _stub_run_case(monkeypatch, {0: "approve", 1: "reject"})
    pipe = _make_pipeline(client, admin_headers)
    p = _run_to_completion(client, admin_headers, pipe["pipeline_id"])

    assert p["status"] == "complete", p
    assert p["steps"][0]["decision"] == "approve"
    assert p["steps"][1]["decision"] == "reject"
    assert p["terminal_decision"] == "reject"
    # Nothing past the reject ran.
    for s in p["steps"][2:]:
        assert s["decision"] is None
    assert [a["decision"] for a in p["actual_path"]] == ["approve", "reject"]


def test_pipeline_runs_all_steps_when_all_continue(client: TestClient, admin_headers: dict, monkeypatch):
    _stub_run_case(monkeypatch, {})  # default "approve" for every step
    pipe = _make_pipeline(client, admin_headers)
    n = len(pipe["steps"])
    p = _run_to_completion(client, admin_headers, pipe["pipeline_id"])

    assert p["status"] == "complete"
    assert all(s["decision"] == "approve" for s in p["steps"])
    assert p["terminal_decision"] == "approve"
    assert len(p["actual_path"]) == n
    # Each step got its own case.
    case_ids = [s["case_id"] for s in p["steps"]]
    assert all(case_ids) and len(set(case_ids)) == n


def test_pipeline_get_requires_auth(client: TestClient):
    assert client.get("/api/pipelines/whatever").status_code == 401


def test_pipeline_unknown_404(client: TestClient, admin_headers: dict):
    assert client.get("/api/pipelines/pipe-nope", headers=admin_headers).status_code == 404


def test_pipeline_exposes_viable_paths_with_recommended(client: TestClient, admin_headers: dict):
    pipe = _make_pipeline(client, admin_headers)
    p = client.get(f"/api/pipelines/{pipe['pipeline_id']}", headers=admin_headers).json()
    assert p["viable_paths"], "expected actionable viable paths"
    assert sum(1 for vp in p["viable_paths"] if vp["recommended"]) == 1
    # Ranked most-probable first, and the recommended one leads.
    probs = [vp["probability"] for vp in p["viable_paths"]]
    assert probs == sorted(probs, reverse=True)
    assert p["viable_paths"][0]["recommended"]


def test_approve_path_starts_execution(client: TestClient, admin_headers: dict, monkeypatch):
    # Stub run_case so the approve-path run completes deterministically.
    _stub_run_case(monkeypatch, {})  # every step -> approve
    pipe = _make_pipeline(client, admin_headers)
    pid = pipe["pipeline_id"]
    p = client.get(f"/api/pipelines/{pid}", headers=admin_headers).json()
    rec = next(vp for vp in p["viable_paths"] if vp["recommended"])

    # Unknown path -> 404.
    assert client.post(f"/api/pipelines/{pid}/approve-path", json={"path_id": "nope"}, headers=admin_headers).status_code == 404

    r = client.post(f"/api/pipelines/{pid}/approve-path", json={"path_id": rec["path_id"]}, headers=admin_headers)
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "running"

    # Poll directly (approve-path already started the run; don't re-confirm).
    final = None
    for _ in range(60):
        final = client.get(f"/api/pipelines/{pid}", headers=admin_headers).json()
        if final["status"] in ("complete", "error"):
            break
        time.sleep(0.05)
    assert final and final["status"] == "complete", final
    assert final["chosen_path_id"] == rec["path_id"]
    assert final["steps"][0]["decision"] == "approve"


def test_first_step_case_is_linked_to_pipeline(client: TestClient, admin_headers: dict):
    create = client.post("/api/cases", json={"prompt": MULTI_PROMPT}, headers=admin_headers).json()
    pid = create["pipeline"]["pipeline_id"]
    # The pipeline-state endpoint carries the per-step case_id.
    p = client.get(f"/api/pipelines/{pid}", headers=admin_headers).json()
    first = p["steps"][0]
    assert first["case_id"] == create["case_id"]  # entry-point case runs step 0
    case = client.get(f"/api/cases/{first['case_id']}", headers=admin_headers).json()
    assert case["scenario_id"] == first["scenario_id"]

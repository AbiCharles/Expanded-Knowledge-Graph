"""API tests for the multi-scenario auto-detect on POST /api/cases."""
from __future__ import annotations

import math

from fastapi.testclient import TestClient


def test_multi_scenario_prompt_returns_pipeline(client: TestClient, admin_headers: dict):
    # This prompt's words hit the keywords of the supply-assurance scenario
    # (SC-PP-AERONOVA-026: "supply assurance", "northwind forge") AND the
    # autonomous PO-release scenario (SC-PP-AUTO-PO-RELEASE-027: "auto-release",
    # "bulk po", "sup-021") — so the keyword-chain planner returns 2+ steps.
    resp = client.post(
        "/api/cases",
        json={"prompt": "Run supply assurance for Northwind Forge, then auto-release the bulk PO to SUP-021"},
        headers=admin_headers,
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["pipeline"] is not None, "expected a multi-scenario pipeline"
    pipe = body["pipeline"]
    assert len(pipe["steps"]) >= 2
    assert all(s["scenario_id"] and s["title"] for s in pipe["steps"])
    # The forecast is a valid probability-weighted Outcome DAG.
    fc = pipe["forecast"]
    assert fc["nodes"] and fc["edges"] and fc["outcomes"]
    assert math.isclose(fc["stats"]["total_probability"], 1.0, abs_tol=1e-6)


def test_unrelated_prompt_has_no_pipeline(client: TestClient, admin_headers: dict):
    resp = client.post(
        "/api/cases",
        json={"prompt": "zxqw unrelated gibberish nothing matches here"},
        headers=admin_headers,
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["pipeline"] is None


def test_pipeline_does_not_break_single_case_flow(client: TestClient, admin_headers: dict):
    # Ordinary create-case response fields are still present regardless.
    resp = client.post(
        "/api/cases",
        json={"prompt": "auto-release the bulk PO to SUP-021"},
        headers=admin_headers,
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert "case_id" in body and "candidates" in body

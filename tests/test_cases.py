"""Cases: create, confirm, decide, replay, delete, isolation."""
from __future__ import annotations

import time

from fastapi.testclient import TestClient


def _confirm_and_wait(client: TestClient, headers: dict, case_id: str) -> None:
    """Confirm a case and wait for the orchestrator to bind stages."""
    client.post(f"/api/cases/{case_id}/confirm", headers=headers)
    # Orchestrator runs as a background task; give it a moment.
    for _ in range(20):
        case = client.get(f"/api/cases/{case_id}", headers=headers).json()
        if case.get("phase") in ("review_ready", "complete", "cancelled"):
            return
        time.sleep(0.1)


def test_unauthed_create_case_401(client: TestClient) -> None:
    resp = client.post("/api/cases", json={"prompt": "hello"})
    assert resp.status_code == 401


def test_create_case_classifies_known_prompt(client: TestClient, admin_headers: dict) -> None:
    resp = client.post(
        "/api/cases",
        json={"prompt": "Override the SC-TC-001 sanctions block"},
        headers=admin_headers,
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["scenario_id"] == "SC-TC-007"
    assert body["case_id"]
    assert body["candidates"]


def test_full_hitl_flow_reject(client: TestClient, admin_headers: dict) -> None:
    create = client.post(
        "/api/cases",
        json={"prompt": "Override the SC-TC-001 sanctions block"},
        headers=admin_headers,
    ).json()
    cid = create["case_id"]
    _confirm_and_wait(client, admin_headers, cid)

    case = client.get(f"/api/cases/{cid}", headers=admin_headers).json()
    assert case["phase"] == "review_ready"

    # Find the open ticket
    queue = client.get("/api/decisions/queue", headers=admin_headers).json()
    ticket = next(t["ticket_id"] for t in queue if t["case_id"] == cid)

    client.post(
        f"/api/decisions/{ticket}",
        json={"decision": "reject", "reviewer_id": "test", "rationale": "smoke"},
        headers=admin_headers,
    )
    # Wait for orchestrator to apply
    for _ in range(20):
        case = client.get(f"/api/cases/{cid}", headers=admin_headers).json()
        if case["phase"] == "complete":
            break
        time.sleep(0.1)
    assert case["phase"] == "complete"
    assert case["decision_kind"] == "reject"


def test_autonomous_flow_auto_executes(client: TestClient, admin_headers: dict) -> None:
    create = client.post(
        "/api/cases",
        json={"prompt": "What is the current ETA on shipment S-700499?"},
        headers=admin_headers,
    ).json()
    cid = create["case_id"]
    assert create["scenario_id"] == "SC-LN-STATUS-009"
    _confirm_and_wait(client, admin_headers, cid)
    case = client.get(f"/api/cases/{cid}", headers=admin_headers).json()
    assert case["phase"] == "complete"
    assert case["decision_kind"] == "auto_execute"


def test_user_cannot_see_anothers_cases(client: TestClient) -> None:
    # Register two users
    a = client.post("/api/auth/register", json={"username": "alice2", "password": "alice123"}).json()
    b = client.post("/api/auth/register", json={"username": "bob2", "password": "bob1234"}).json()
    a_h = {"Authorization": f"Bearer {a['access_token']}"}
    b_h = {"Authorization": f"Bearer {b['access_token']}"}

    cid = client.post(
        "/api/cases",
        json={"prompt": "Override the SC-TC-001 sanctions block"},
        headers=a_h,
    ).json()["case_id"]

    # Alice sees her own
    assert any(c["case_id"] == cid for c in client.get("/api/cases", headers=a_h).json())
    # Bob does not see Alice's
    assert not any(c["case_id"] == cid for c in client.get("/api/cases", headers=b_h).json())
    # Direct access → 403
    assert client.get(f"/api/cases/{cid}", headers=b_h).status_code == 403


def test_delete_case(client: TestClient, admin_headers: dict) -> None:
    cid = client.post(
        "/api/cases",
        json={"prompt": "ETA on S-700499?"},
        headers=admin_headers,
    ).json()["case_id"]

    assert client.delete(f"/api/cases/{cid}", headers=admin_headers).status_code == 200
    assert client.get(f"/api/cases/{cid}", headers=admin_headers).status_code == 404

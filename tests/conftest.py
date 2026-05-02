"""Shared pytest fixtures.

Each test gets a fresh app + isolated SQLite + isolated scenario directory
so they can run in any order without interference.
"""
from __future__ import annotations

import os
import shutil
from pathlib import Path
from typing import Iterator

import pytest

# Set required env vars BEFORE importing anything that reads config.
os.environ["JWT_SECRET"] = "test-secret-not-for-production"
os.environ["LLM_PROVIDER"] = "fake"
os.environ["HITL_ALLOW_DEFAULT_SECRET"] = "0"  # we set a real one above
# Tests run all auth assertions against the same TestClient (single fake IP),
# so the production 10/min limit on /login + /register would trip after a
# handful of tests. Disable for the suite.
os.environ["HITL_DISABLE_RATE_LIMIT"] = "1"

from fastapi.testclient import TestClient


REPO_ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture()
def tmp_app_data(tmp_path: Path) -> Iterator[Path]:
    """Mirror the repo's `backend/data/` and `backend/scenarios/` into a tmp
    dir so tests don't trample the dev environment. We replicate the layout
    exactly so the relative paths in sources.yaml resolve as-is."""
    # `sources.yaml` declares paths like "backend/data/products.csv" — mirror
    # that under tmp_path so the registry's `_resolve_path` finds them.
    data_dir = tmp_path / "backend" / "data"
    data_dir.mkdir(parents=True)
    seed = REPO_ROOT / "backend" / "data"
    for f in ("sources.yaml", "products.csv", "sanctions_sdn_sample.csv", "governance.sqlite"):
        if (seed / f).exists():
            shutil.copy(seed / f, data_dir / f)
    if (seed / "policy_corpus").exists():
        shutil.copytree(seed / "policy_corpus", data_dir / "policy_corpus")

    scenarios = tmp_path / "backend" / "scenarios"
    shutil.copytree(REPO_ROOT / "backend" / "scenarios", scenarios)
    yield data_dir


@pytest.fixture()
def client(tmp_app_data: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[TestClient]:
    """Fresh TestClient with isolated data dir."""
    # Patch project_root + db path to use tmp dir
    import backend.main as main_module
    from backend.persistence import db as db_module

    db_module._singleton = None  # reset the lazy singleton

    real_lifespan = main_module.lifespan

    # The lifespan reads `Path(__file__).resolve().parent.parent` for the
    # project root. Easiest approach: monkeypatch the function locally.
    @main_module.asynccontextmanager
    async def test_lifespan(app):
        from backend.agent_runtime import AgentRuntime
        from backend.auth import ensure_default_admin
        from backend.config import get_settings
        from backend.datasources import DataSourceRegistry
        from backend.persistence import get_database
        from backend.scenario_loader import ScenarioRegistry
        from backend.state import AppState
        from tcs_hitl_context import build_llm_client_from_env

        settings = get_settings()
        # tmp_app_data points at <tmp>/backend/data; project_root is one up.
        project_root = tmp_app_data.parent.parent
        scenarios = ScenarioRegistry.from_directory(project_root / "backend" / "scenarios")
        sources_yaml = tmp_app_data / "sources.yaml"
        data_sources = DataSourceRegistry.from_yaml(
            storage_path=sources_yaml,
            project_root=project_root,
            openai_api_key=settings.OPENAI_API_KEY or None,
        )
        database = get_database(tmp_app_data / "app.sqlite")
        ensure_default_admin(database)
        llm = build_llm_client_from_env(settings.model_dump())
        agent_runtime = AgentRuntime(llm=llm, scenarios=scenarios)
        app.state.app_state = AppState(
            scenarios=scenarios, llm=llm, agent_runtime=agent_runtime,
            data_sources=data_sources, database=database,
        )
        yield

    monkeypatch.setattr(main_module, "lifespan", test_lifespan)
    app = main_module.create_app()
    app.router.lifespan_context = test_lifespan

    with TestClient(app) as c:
        yield c


@pytest.fixture()
def admin_token(client: TestClient) -> str:
    """Log in as the seeded admin user, return the bearer token."""
    resp = client.post(
        "/api/auth/login",
        data={"username": "admin", "password": "admin"},
        headers={"content-type": "application/x-www-form-urlencoded"},
    )
    assert resp.status_code == 200, resp.text
    return resp.json()["access_token"]


@pytest.fixture()
def admin_headers(admin_token: str) -> dict:
    return {"Authorization": f"Bearer {admin_token}"}

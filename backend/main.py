"""FastAPI application entry point."""
from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from tcs_hitl_context import FakeLLMClient, build_llm_client_from_env

from .agent_runtime import AgentRuntime
from .api.auth import router as auth_router
from .api.cases import router as cases_router
from .api.datasources import router as datasources_router
from .api.decisions import router as decisions_router
from .api.exports import router as exports_router
from .api.scenarios import router as scenarios_router
from .auth import ensure_default_admin
from .config import get_settings
from .datasources import DataSourceRegistry
from .persistence import get_database
from .scenario_loader import ScenarioRegistry
from .state import AppState


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    logging.basicConfig(level=settings.LOG_LEVEL)

    scenario_dir = Path(__file__).resolve().parent / "scenarios"
    scenarios = ScenarioRegistry.from_directory(scenario_dir)

    project_root = Path(__file__).resolve().parent.parent
    sources_yaml = project_root / "backend" / "data" / "sources.yaml"
    data_sources = DataSourceRegistry.from_yaml(
        storage_path=sources_yaml,
        project_root=project_root,
        openai_api_key=settings.OPENAI_API_KEY or None,
    )

    db_path = project_root / "backend" / "data" / "app.sqlite"
    database = get_database(db_path)
    ensure_default_admin(database)

    # Build the LLM client from env. If keys are missing for the requested
    # provider, fall back to FakeLLMClient so the UI still runs (with keyword
    # classification only). Loud warning so the operator notices.
    try:
        llm = build_llm_client_from_env(settings.model_dump())
    except RuntimeError as exc:
        logging.getLogger(__name__).warning(
            "LLM credentials missing (%s). Falling back to FakeLLMClient — "
            "classification will use keyword matching, not the LLM. "
            "Set OPENAI_API_KEY (or Azure equivalents) in .env to enable.",
            exc,
        )
        llm = FakeLLMClient()
    agent_runtime = AgentRuntime(llm=llm, scenarios=scenarios)

    app.state.app_state = AppState(
        scenarios=scenarios,
        llm=llm,
        agent_runtime=agent_runtime,
        data_sources=data_sources,
        database=database,
    )
    logging.getLogger(__name__).info(
        "HITL backend ready · LLM=%s · scenarios=%d · data_sources=%d · db=%s",
        llm.name, len(scenarios.all()), len(data_sources.specs()), db_path,
    )
    yield


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(title="HITL Context Framework", version="0.1.0", lifespan=lifespan)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins_list,
        allow_credentials=False,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.include_router(auth_router, prefix="/api")
    app.include_router(cases_router, prefix="/api")
    app.include_router(decisions_router, prefix="/api")
    app.include_router(scenarios_router, prefix="/api")
    app.include_router(datasources_router, prefix="/api")
    app.include_router(exports_router, prefix="/api")

    @app.get("/api/health")
    def health():
        return {"status": "ok"}

    return app


app = create_app()

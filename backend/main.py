"""FastAPI application entry point."""
from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from pathlib import Path

# Load .env into os.environ BEFORE any backend imports. backend.auth captures
# JWT_SECRET at module-import time via os.environ.get(); without this dance
# .env values are only seen later (when pydantic-settings reads them in
# get_settings()), which is too late for the import-time constant.
from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parent.parent / ".env")

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from tcs_hitl_context import FakeLLMClient, build_llm_client_from_env

from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.util import get_remote_address

from .actions import ActionRegistry
from .agent_runtime import AgentRuntime
from .api.auth import limiter as auth_limiter, router as auth_router
from .api.cases import router as cases_router
from .api.datasources import router as datasources_router
from .api.decisions import router as decisions_router
from .api.graph import router as graph_router
from .api.exports import router as exports_router
from .api.insights import router as insights_router
from .api.metrics import router as metrics_router
from .api.actions import router as actions_router
from .api.ontologies import router as ontologies_router
from .api.scenarios import router as scenarios_router
from .auth import assert_jwt_secret_set, ensure_default_admin
from .config import get_settings
from .datasources import DataSourceRegistry
from .ontology import OntologyRegistry
from .persistence import get_database
from .scenario_loader import ScenarioRegistry
from .state import AppState


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    logging.basicConfig(level=settings.LOG_LEVEL)
    # Refuse to start without a real JWT_SECRET. HITL_ALLOW_DEFAULT_SECRET=1
    # bypasses for transient local runs.
    assert_jwt_secret_set()

    scenario_dir = Path(__file__).resolve().parent / "scenarios"
    scenarios = ScenarioRegistry.from_directory(scenario_dir)

    project_root = Path(__file__).resolve().parent.parent
    sources_yaml = project_root / "backend" / "data" / "sources.yaml"
    # Wire Azure embeddings only when LLM_PROVIDER=azure AND a separate
    # embedding deployment is configured. Without it, vector sources fall back
    # to OPENAI_API_KEY (if set) or skip embedding entirely.
    azure_embedding_config = None
    if (
        settings.LLM_PROVIDER == "azure"
        and settings.AZURE_OPENAI_EMBEDDING_DEPLOYMENT
        and settings.AZURE_OPENAI_API_KEY
        and settings.AZURE_OPENAI_ENDPOINT
    ):
        azure_embedding_config = {
            "api_key": settings.AZURE_OPENAI_API_KEY,
            "endpoint": settings.AZURE_OPENAI_ENDPOINT,
            "api_version": settings.AZURE_OPENAI_API_VERSION,
            "deployment": settings.AZURE_OPENAI_EMBEDDING_DEPLOYMENT,
        }
    data_sources = DataSourceRegistry.from_yaml(
        storage_path=sources_yaml,
        project_root=project_root,
        openai_api_key=settings.OPENAI_API_KEY or None,
        azure_embedding_config=azure_embedding_config,
    )

    # Optional: auto-register a default Neo4j source when NEO4J_PASSWORD
    # is set in the env. The operator can still add more Neo4j sources
    # via the UI form. We use a stable id (`neo4j_default`) so re-running
    # at boot updates the spec rather than creating duplicates.
    if settings.NEO4J_PASSWORD and settings.NEO4J_URI:
        from .datasources import DataSourceSpec, ResolverError

        cfg: dict = {"uri": settings.NEO4J_URI, "password": settings.NEO4J_PASSWORD}
        if settings.NEO4J_USER:
            cfg["user"] = settings.NEO4J_USER
        if settings.NEO4J_DATABASE:
            cfg["database"] = settings.NEO4J_DATABASE
        try:
            data_sources.register(
                DataSourceSpec(
                    id="neo4j_default",
                    kind="neo4j",
                    config=cfg,
                    description=(
                        f"Auto-registered from NEO4J_* env vars "
                        f"({settings.NEO4J_URI})"
                    ),
                )
            )
            logging.getLogger(__name__).info(
                "Neo4j source `neo4j_default` auto-registered from NEO4J_* env vars"
            )
        except ResolverError as exc:
            logging.getLogger(__name__).warning(
                "Neo4j auto-registration failed: %s", exc
            )

    ontology_dir = project_root / "backend" / "ontologies"
    ontologies = OntologyRegistry.from_directory(ontology_dir)

    actions_dir = project_root / "backend" / "data" / "actions"
    actions = ActionRegistry.from_directory(actions_dir)

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
        ontologies=ontologies,
        actions=actions,
        database=database,
    )
    mapping_count = sum(
        1 for o in ontologies.all() if ontologies.get_mapping(o.id) is not None
    )
    logging.getLogger(__name__).info(
        "HITL backend ready · LLM=%s · scenarios=%d · data_sources=%d · "
        "ontologies=%d · mappings=%d · actions=%d · db=%s",
        llm.name, len(scenarios.all()), len(data_sources.specs()),
        len(ontologies.all()), mapping_count, len(actions.all()), db_path,
    )
    yield


def create_app() -> FastAPI:
    app = FastAPI(title="HITL Context Framework", version="0.1.0", lifespan=lifespan)
    # CORS — open to all origins since the Fly API is hit from external
    # clients (Azure deployment, local dev, demo audience browsers).
    # allow_credentials stays False so the "*" wildcard is browser-spec
    # compliant (credentials + wildcard origins is rejected client-side).
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=False,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # Rate limiting: app-wide default keeps any one IP from hammering the
    # LLM-backed endpoints. The auth router has a tighter per-route limit
    # for /login + /register applied via the @limiter.limit decorator.
    limiter = Limiter(key_func=get_remote_address, default_limits=["120/minute"])
    app.state.limiter = limiter
    auth_limiter._key_func = get_remote_address  # share the IP-extraction strategy
    app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)
    app.include_router(auth_router, prefix="/api")
    app.include_router(cases_router, prefix="/api")
    app.include_router(decisions_router, prefix="/api")
    app.include_router(scenarios_router, prefix="/api")
    app.include_router(datasources_router, prefix="/api")
    app.include_router(exports_router, prefix="/api")
    app.include_router(insights_router, prefix="/api")
    app.include_router(metrics_router, prefix="/api")
    app.include_router(ontologies_router, prefix="/api")
    app.include_router(actions_router, prefix="/api")
    app.include_router(graph_router, prefix="/api")

    @app.get("/api/health")
    def health():
        return {"status": "ok"}

    # Serve the built frontend at / when present (Docker / Fly). Skipped in
    # local dev where the Vite dev server runs on its own port.
    dist_dir = Path(__file__).resolve().parent.parent / "frontend" / "dist"
    if dist_dir.is_dir():
        index_file = dist_dir / "index.html"
        assets_dir = dist_dir / "assets"

        # Cache strategy for an SPA whose JS bundle name is hash-tagged
        # by Vite (e.g. index-CgXcNLoD.js):
        #   - /assets/* (the hashed bundles + css):  cache forever +
        #     `immutable` so a browser doesn't even revalidate. Safe
        #     because the filename changes on every rebuild.
        #   - index.html:  never cache. It's what tells the browser which
        #     hashed bundle to load; if it's stale the user keeps loading
        #     yesterday's JS forever even after a deploy.
        # Without these headers anuj-style "I'm still on the old UI"
        # bugs are guaranteed after every release.
        IMMUTABLE = "public, max-age=31536000, immutable"
        NO_CACHE = "no-cache, no-store, must-revalidate"

        class _ImmutableStatic(StaticFiles):
            async def get_response(self, path, scope):
                resp = await super().get_response(path, scope)
                resp.headers["Cache-Control"] = IMMUTABLE
                return resp

        if assets_dir.is_dir():
            app.mount("/assets", _ImmutableStatic(directory=assets_dir), name="assets")

        # SPA fallback so React Router routes survive a hard refresh. Skips
        # /api/* so unmatched API paths still 404 instead of silently
        # returning the HTML shell.
        @app.get("/{full_path:path}")
        def _spa_fallback(full_path: str):
            if full_path.startswith("api/"):
                from fastapi import HTTPException
                raise HTTPException(status_code=404, detail="Not Found")
            asset = dist_dir / full_path
            if full_path and asset.is_file():
                # Hashed bundle that escaped /assets — still immutable.
                return FileResponse(
                    asset, headers={"Cache-Control": IMMUTABLE}
                )
            return FileResponse(
                index_file, headers={"Cache-Control": NO_CACHE}
            )

    return app


app = create_app()

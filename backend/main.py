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
from fastapi.responses import FileResponse, HTMLResponse
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
from .api.rca import router as rca_router
from .api.aeronova import router as aeronova_router
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
    #
    # If a `neo4j_default` already exists in the persisted sources.yaml
    # (e.g. shipped from a local dev machine that auto-registered
    # bolt://localhost:7687), env-var values win. Without this, a stale
    # localhost entry on the Fly volume would shadow the production URI
    # forever and the supplier graph would silently return empty.
    if settings.NEO4J_PASSWORD and settings.NEO4J_URI:
        from .datasources import DataSourceSpec, ResolverError

        cfg: dict = {"uri": settings.NEO4J_URI, "password": settings.NEO4J_PASSWORD}
        if settings.NEO4J_USER:
            cfg["user"] = settings.NEO4J_USER
        if settings.NEO4J_DATABASE:
            cfg["database"] = settings.NEO4J_DATABASE
        log = logging.getLogger(__name__)
        existing = next(
            (s for s in data_sources.specs() if s.id == "neo4j_default"),
            None,
        )
        if existing is not None:
            try:
                data_sources.remove("neo4j_default")
                log.info(
                    "Removed stale neo4j_default spec (uri=%s) so env-var "
                    "values can take precedence",
                    existing.config.get("uri"),
                )
            except ResolverError as exc:
                log.warning("Could not remove stale neo4j_default: %s", exc)
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
            log.info(
                "Neo4j source `neo4j_default` registered with uri=%s",
                settings.NEO4J_URI,
            )
        except ResolverError as exc:
            log.warning("Neo4j auto-registration failed: %s", exc)

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


# Tiny (~2 KB) shell served at GET /launcher. Renders a centered spinner
# on the FIRST paint, then fetch()es /launcher/frame (the 165 KB wireframe
# body) and swaps its <body> markup + <script> execution into the page.
# Split out so the user sees feedback in <100 ms even during a cold-start
# request that takes several seconds to hand back the full wireframe.
_LAUNCHER_SHELL_HTML = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>Loading launcher · TCS Knowledge Fabric</title>
<meta name="viewport" content="width=device-width, initial-scale=1">
<style>
  html, body { margin: 0; padding: 0; height: 100%;
               font-family: Calibri, "Helvetica Neue", Arial, sans-serif;
               background: #f3f4f6; color: #1E2761; }
  #shell { position: fixed; inset: 0; display: flex; flex-direction: column;
           align-items: center; justify-content: center;
           transition: opacity 220ms ease; }
  #shell.hide { opacity: 0; pointer-events: none; }
  .spinner { width: 42px; height: 42px; border-radius: 50%;
             border: 4px solid #d1d5db; border-top-color: #4f46e5;
             animation: spin 900ms linear infinite; }
  @keyframes spin { to { transform: rotate(360deg); } }
  .title  { margin-top: 18px; font-size: 15px; font-weight: 600; }
  .sub    { margin-top: 4px;  font-size: 12px; color: #6b7280; max-width: 360px;
            text-align: center; padding: 0 24px; line-height: 1.5; }
  #err    { max-width: 420px; padding: 14px 18px; background: #fef2f2;
            border: 1.5px solid #dc2626; border-radius: 6px;
            font-size: 12px; color: #7f1d1d; line-height: 1.5; }
</style>
</head>
<body>
<div id="shell">
  <div class="spinner"></div>
  <div class="title">Loading launcher…</div>
  <div class="sub">Fetching the 6-step config wizard · usually 1–2 seconds after the machine wakes</div>
</div>
<div id="stage"></div>
<script>
(async function boot() {
  // Fetch the wireframe body. On a cold Fly start this can take up to
  // ~15 s while the machine boots; the spinner keeps the user informed
  // during that wait. Once the response lands we extract the <body>
  // markup and execute any inline <script> tags manually (setting
  // innerHTML does NOT run scripts).
  try {
    const res = await fetch('/launcher/frame', { cache: 'no-store' });
    if (!res.ok) throw new Error('HTTP ' + res.status);
    const html = await res.text();
    const doc  = new DOMParser().parseFromString(html, 'text/html');

    // Hoist <style> + <link> from the fetched <head> so the wireframe
    // renders with its own CSS instead of inheriting the shell's.
    doc.head.querySelectorAll('style, link[rel="stylesheet"]').forEach(function (n) {
      document.head.appendChild(n);
    });

    // Swap in the wireframe's <body> children.
    const stage = document.getElementById('stage');
    while (doc.body.firstChild) stage.appendChild(doc.body.firstChild);

    // Execute inline scripts. innerHTML-inserted scripts don't run;
    // we clone each into a fresh <script> so the browser picks them up.
    stage.querySelectorAll('script').forEach(function (old) {
      const s = document.createElement('script');
      if (old.src) s.src = old.src;
      else s.textContent = old.textContent;
      old.replaceWith(s);
    });

    // Fade the shell spinner out; wireframe takes over.
    const shell = document.getElementById('shell');
    shell.classList.add('hide');
    setTimeout(function () { shell.remove(); }, 260);
  } catch (err) {
    document.getElementById('shell').innerHTML =
      '<div id="err"><b>Couldn\\u2019t load the launcher.</b><br>' + err.message +
      '<br><br>The fabric machine may be cold-starting. Please refresh in a few seconds.</div>';
  }
})();
</script>
</body>
</html>
"""


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
    app.include_router(rca_router, prefix="/api")
    app.include_router(aeronova_router, prefix="/api")

    @app.get("/api/health")
    def health():
        return {"status": "ok"}

    # Launcher wireframe at /launcher (no auth). The wireframe itself
    # is 165 KB of self-contained HTML; instead of shipping that in one
    # blob (during which the browser tab shows a blank page), we serve
    # a ~2 KB shell here that paints a loading spinner in the first
    # frame, then fetches the body from /launcher/frame and swaps it
    # into the DOM. Cold-start latency now shows as an animated spinner
    # instead of a white void.
    #
    # File lives at repo_root/docs/launcher-wireframe.html and is
    # copied into the image by the Dockerfile.
    launcher_path = (
        Path(__file__).resolve().parent.parent / "docs" / "launcher-wireframe.html"
    )
    if launcher_path.is_file():
        @app.get("/launcher", response_class=HTMLResponse)
        def _launcher_shell() -> str:
            return _LAUNCHER_SHELL_HTML

        @app.get("/launcher/frame")
        def _launcher_frame() -> FileResponse:
            return FileResponse(
                launcher_path,
                media_type="text/html",
                headers={"Cache-Control": "no-cache, no-store, must-revalidate"},
            )

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

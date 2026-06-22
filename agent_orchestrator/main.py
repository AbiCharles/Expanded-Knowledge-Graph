"""FastAPI surface for the agent-orchestrator companion service.

Two endpoints:

  POST /api/agent-run/start         — kick off a new run, return run_id
  GET  /api/agent-run/{id}/events   — SSE stream of AgentEvent objects

The service is intentionally simple: no auth (the fabric is the
sensitive layer; this service just orchestrates calls against it),
in-memory run state (no persistence; restart wipes prior runs), one
worker (cheap; can horizontally scale once we add Redis later).
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
from contextlib import asynccontextmanager
from typing import AsyncIterator

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse

from .events import AgentEvent, StartRunRequest, StartRunResponse
from .fabric_client import FabricClient
from .narrator import Narrator
from .orchestrator import AgentRun

log = logging.getLogger(__name__)

# Active runs by id. AgentRun objects are small and there's no
# persistence target for a demo service.
RUNS: dict[str, AgentRun] = {}

# Shared infrastructure — one fabric client + one narrator per
# process. Both are cheap to instantiate; sharing keeps the
# admin-JWT cache hot across runs.
_fabric: FabricClient | None = None
_narrator: Narrator | None = None


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    global _fabric, _narrator
    _fabric = FabricClient()
    _narrator = Narrator()
    log.info(
        "Agent orchestrator ready · fabric=%s · narrator=%s",
        _fabric.base_url,
        "llm" if _narrator._client else "fake",
    )
    try:
        yield
    finally:
        if _fabric is not None:
            await _fabric.aclose()


app = FastAPI(title="Agent Orchestrator", version="0.1.0", lifespan=lifespan)


# CORS — allow the fabric's frontend host + localhost dev.
_cors_origins_env = os.environ.get(
    "AGENT_CORS_ORIGINS",
    "https://tcs-knowledge-fabric.fly.dev,http://localhost:5173",
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=[o.strip() for o in _cors_origins_env.split(",") if o.strip()],
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["*"],
    allow_credentials=False,
)


@app.get("/api/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/api/agent-run/start", response_model=StartRunResponse)
async def start_run(_payload: StartRunRequest | None = None) -> StartRunResponse:
    if _fabric is None or _narrator is None:
        raise HTTPException(503, "service not initialized")
    run = AgentRun(fabric=_fabric, narrator=_narrator)
    RUNS[run.run_id] = run
    # Kick off the run in the background; the SSE endpoint pulls
    # events off the queue as they come in.
    asyncio.create_task(run.run())
    return StartRunResponse(run_id=run.run_id)


@app.get("/api/agent-run/{run_id}/events")
async def stream_events(run_id: str) -> StreamingResponse:
    run = RUNS.get(run_id)
    if run is None:
        raise HTTPException(404, f"unknown run_id {run_id!r}")

    async def _stream() -> AsyncIterator[bytes]:
        # SSE protocol — each event is a "data: <json>\n\n" packet.
        while True:
            evt: AgentEvent | None = await run.events.get()
            if evt is None:
                # Sentinel — orchestrator finished. Emit a final
                # "done" so the client can close its EventSource.
                yield b"event: done\ndata: {}\n\n"
                return
            payload = evt.model_dump(mode="json")
            yield (
                f"event: {evt.type}\ndata: {json.dumps(payload)}\n\n"
            ).encode("utf-8")

    return StreamingResponse(
        _stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache, no-transform",
            "X-Accel-Buffering": "no",
            "Connection": "keep-alive",
        },
    )


@app.get("/api/agent-run/{run_id}/status")
async def run_status(run_id: str) -> dict:
    run = RUNS.get(run_id)
    if run is None:
        raise HTTPException(404, f"unknown run_id {run_id!r}")
    return {"run_id": run_id, "done": run.done}

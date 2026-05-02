# HITL Context Framework — Full-Stack App

A real implementation of the HITL Context Framework demo, with:

- **Backend** (`backend/`) — FastAPI exposing the framework over REST + Server-Sent Events.
- **Framework** (`hitl-context/`) — the typed envelope, stage binders, transports, lineage recorder.
- **Frontend** (`frontend/`) — Vite + React + TypeScript. Lifts the design from the static demo.
- **LLM adapter** — OpenAI, Azure OpenAI, or a fake client. Configurable via `.env`.

## Quick start

```bash
# 1. Python env (one-time)
python3.11 -m venv .venv
source .venv/bin/activate
pip install -e .[dev]

# 2. Configure credentials
cp .env.example .env
$EDITOR .env       # set LLM_PROVIDER + the matching keys

# 3. Frontend deps (one-time)
cd frontend && npm install && cd ..

# 4. Run (two terminals)
uvicorn backend.main:app --reload --port 8000
cd frontend && npm run dev   # http://localhost:5173
```

If you don't have credentials handy, set `LLM_PROVIDER=fake` in `.env` — the UI will run end-to-end against canned LLM responses.

## Layout

```
HITL/
├── backend/              FastAPI app
│   ├── api/              REST routes
│   ├── scenarios/        YAML scenario fixtures (data, not code)
│   ├── agent_runtime.py  LLM-driven prompt classification + action drafting
│   ├── binders.py        Fixture-driven implementations of the framework's binder protocols
│   ├── policy.py         Deciding autonomous vs HITL
│   ├── state.py          In-memory case + ticket store
│   └── main.py           App entry point
├── hitl-context/         The framework package (Pydantic envelope, transports, surface)
├── frontend/             React UI
└── pyproject.toml        Top-level project (declares backend + framework as installable)
```

## Switching LLM providers

Edit `.env`:

```
LLM_PROVIDER=openai      # or `azure` or `fake`
```

For Azure, fill in the four `AZURE_OPENAI_*` variables (deployment name + endpoint + api-version + key). For OpenAI, fill in `OPENAI_API_KEY` and `OPENAI_MODEL`. The model identifier is a free-form string — set it to whatever your deployment exposes.

## Type-generation (frontend ↔ backend)

The frontend keeps a hand-maintained `src/types.ts` for the most-used shapes.
For full coverage that won't drift, run:

```bash
# (with uvicorn running on :8001)
cd frontend && npm run gen-types
```

This regenerates `src/api-types.ts` from FastAPI's `/openapi.json`. Re-run
whenever you add/change a backend endpoint and want the frontend's typings
to follow.

## Smoke tests

```bash
# Framework regression — should report 90/90.
python hitl-context/tests/verify_package.py

# Original SC-TC-007 example, end-to-end:
python hitl-context/examples/sc_guardrails_integration.py

# Backend health (with uvicorn running):
curl http://localhost:8000/api/health
```

## What's wired

- **5 scenarios** (3 HITL, 2 autonomous) live as YAML in [backend/scenarios/](backend/scenarios/). Drop new ones in to extend.
- **Stage 1 / Stage 2 / Stage 3** binders ([backend/binders.py](backend/binders.py)) pull facts from those YAMLs and return the framework's `StageContext`.
- **Policy** ([backend/policy.py](backend/policy.py)) reads each scenario's `autonomous` flag to decide HITL vs auto-execute.
- **LLM adapter** ([hitl-context/src/tcs_hitl_context/llm.py](hitl-context/src/tcs_hitl_context/llm.py)) wraps OpenAI / Azure / Fake under one `LLMClient` Protocol.
- **Live updates** stream over SSE at `GET /api/cases/{case_id}/events` — `stage_bound`, `review_ready`, `decided`, `auto_approved`, `done`.
- **Replay & compare**: `POST /api/cases/{case_id}/replay` clones a case with a forced reviewer decision; both cases get linked as siblings for side-by-side comparison.

## What's not wired (and why)

- **No real KF / ERP / IAM connectors** — the binders read fixture YAML. Swap in real `KnowledgeResolver` implementations to upgrade.
- **In-memory only** — `dict[str, CaseRecord]` and `InMemoryLineageRecorder`. Restart wipes state. The framework's `LineageRecorder` Protocol is the upgrade seam to a real audit store.
- **No auth** — single-operator demo. Operator/reviewer is a UI toggle.
- **Teams card is rendered locally** — uses `TeamsAdaptiveCardSurface.render()` JSON but doesn't actually post to MS Teams.

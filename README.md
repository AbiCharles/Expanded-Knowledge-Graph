# HITL Context Framework

A working full-stack implementation of a Human-In-The-Loop agent runtime
for enterprise supply-chain workflows. The agent reads a natural-language
prompt, classifies it to a scenario, binds knowledge from registered data
sources at each stage, and either auto-executes (low-risk) or routes to a
human reviewer (anything that needs judgement). Every step is recorded in
an append-only lineage log.

```
┌─────────────────┐  prompt   ┌────────────────┐  binds at each stage
│ Operator (you)  ├──────────▶│  Agent runtime ├──┐
└─────────────────┘           └────────────────┘  │   ┌─────────────┐
                                                  ├──▶│   Envelope  │
   ┌────────────────────────┐  KnowledgeResolver  │   │  (typed)    │
   │ Data sources (CSV,     ├─────────────────────┘   └──────┬──────┘
   │ SQLite, Postgres,      │                                │
   │ HTTP, vector store)    │                          autonomous?
   └────────────────────────┘                                │
                                          ┌─────────────────┴─┐
                                          │                   │
                                  yes — auto-execute   no — HITL review
                                                              │
                                                       ┌──────┴──────┐
                                                       │ Reviewer    │
                                                       │ (Teams card)│
                                                       └─────────────┘
```

---

## Quick start (five minutes)

```bash
# 1. Python env (one-time)
python3.11 -m venv .venv
source .venv/bin/activate
pip install -e .[dev]

# 2. Optional: configure LLM credentials. Without this the app uses a
#    deterministic keyword classifier that runs the demo end-to-end.
cp .env.example .env
$EDITOR .env       # set LLM_PROVIDER + matching keys

# 3. Frontend deps (one-time)
cd frontend && npm install && cd ..

# 4. Run two processes
uvicorn backend.main:app --reload --port 8001     # terminal 1
cd frontend && npm run dev                        # terminal 2 — http://localhost:5173
```

Sign in at <http://localhost:5173> with the seeded `admin / admin` account.
Click any of the suggested prompt chips to run a case end to end. See
[docs/production.md](docs/production.md) before deploying to anything that
isn't your own laptop.

---

## What's in the box

### Core flow
- **6 hand-authored scenarios** (Trade Compliance, Procurement, Logistics)
  covering both HITL and autonomous shapes
- **6 connector types** for data sources: CSV upload, SQLite, Postgres, HTTP
  REST, vector store (OpenAI embeddings), and **Neo4j** (Cypher with a
  read-only safety guard; bind ontology classes via `query_template`
  templates in the mapping doc)
- **Ontology layer** — upload a YAML/JSON ontology, the LLM proposes
  column-to-attribute mappings against your registered sources, and
  scenarios bind data via ontology classes instead of hard-coding
  source ids. Includes an NL→ontology query playground for ad-hoc
  questions and an opt-in NL→ontology fallback in the operator
  console. See [docs/ontology.md](docs/ontology.md).
- **Action registry (NL→write)** — register structured write actions
  (SQL UPDATE, HTTP POST/PUT/PATCH/DELETE) with typed argument schemas
  and an executor; the LLM picks an action from a natural-language
  prompt, the case goes through HITL review by default, and the
  executor runs only on reviewer approval. Opt in per-prompt via the
  composer's "Try write action" toggle.
- **LLM adapter** with three drop-in clients: `OpenAIClient`,
  `AzureOpenAIClient`, `FakeLLMClient`
- **Top-K classifier suggestions** when prompt confidence is low
- **Replay & compare**: clone a completed case with a forced reviewer
  decision; view both side by side

### Operator features
- **Query playground** — run ad-hoc SQL against any SQLite/Postgres source
  with named parameters
- **Save as scenario** — turn an iterated query into a runnable agent
  scenario, with optional LLM-suggested keywords / clarifier / prompt
- **Edit existing scenarios** in-app (titles, keywords, clarifier text);
  Remove for auto- and custom-scenarios
- **One-click lookup chip per ontology class** — register a source, map
  it to ontology classes via the Knowledge tile, click "Generate lookup
  chip" per class to surface an autonomous `SC-ONTO-…` chip on the
  operator console
- **Live metrics dashboard** — totals, cases-by-status, decisions-by-
  scenario stack, cases-per-day sparkline, top rejection reasons
- **CSV export** of cases + full lineage (with date-range filters)
- **History panel** — past conversations, search, delete, bulk-clear
  completed

### Architecture
- **Persistent storage** in SQLite — cases, lineage events, users. Survives
  restart. Designed to swap for Postgres without code changes (the
  framework's `LineageRecorder` Protocol is the seam).
- **Authentication** via JWT + bcrypt. Per-user case isolation; admin role
  bypasses scoping. Token revocation on logout.
- **Rate limiting** — 10/min on login + register, 120/min global.
- **SSE live updates** — stage-bound, review-ready, decided, auto-approved
  events streamed to the UI; auto-reconnects with exponential backoff.

### Operations
- **Multi-stage Dockerfile** + `docker-compose.yaml` with Caddy auto-TLS
- **GitHub Actions CI** — framework tests, pytest suite, frontend build,
  ruff lint
- **21 backend tests** + 90 framework tests, all green

---

## Architecture at a glance

```
HITL/
├── hitl-context/                 The framework package (separate from the app)
│   ├── src/tcs_hitl_context/
│   │   ├── models.py             KnowledgeContext, KnowledgeFact, AgentAction…
│   │   ├── protocols.py          KnowledgeResolver, StageBinder, HITLTransport,
│   │   │                         ReviewerSurface, LineageRecorder
│   │   ├── service.py            HITLContextService orchestrator
│   │   ├── transport.py          Sync + async transports
│   │   ├── lineage.py            InMemoryLineageRecorder
│   │   ├── llm.py                OpenAI / Azure / Fake adapter
│   │   └── surface_teams.py      Teams Adaptive Card v1.5 surface
│   └── docs/                     Framework reference docs
│
├── backend/                      FastAPI app on top of the framework
│   ├── api/                      REST routers (auth, cases, decisions,
│   │                             scenarios, datasources, ontologies,
│   │                             ontology_query, actions, exports, metrics)
│   ├── scenarios/                Built-in YAML scenarios + saved customs
│   ├── ontologies/               Uploaded ontology + mapping YAMLs
│   ├── data/                     Default data sources (CSV, SQLite, vector)
│   │   └── actions/              Registered write actions (one YAML per action)
│   ├── datasources/              Connector implementations
│   │                             (csv, sqlite, postgres, http, vector, neo4j)
│   ├── ontology/                 OntologyRegistry, mapper, OntologyResolver,
│   │                             NL→ontology query parser, cypher safety
│   ├── actions/                  ActionRegistry, NL action picker, executors
│   │                             (sql_update, http_request)
│   ├── persistence/              SQLite-backed CaseStore + LineageRecorder
│   ├── agent_runtime.py          LLM-driven classification + action drafting
│   ├── binders.py                Fixture- and source-driven stage binders
│   │                             (also dispatches `ontology_queries:` blocks)
│   ├── auth.py                   Hash, JWT, FastAPI dependencies
│   ├── auto_scenario.py          Generate a chip per ontology class +
│   │                             synthesize SC-ADHOC / SC-NLWRITE scenarios
│   ├── orchestrator.py           Drives a case through all 4 nodes;
│   │                             invokes action executors on approve
│   └── main.py                   App entry point
│
├── frontend/                     Vite + React + TypeScript
│   └── src/
│       ├── components/           StatusBar, Console, FlowStage, Envelope,
│       │                         LineagePanel, modals (Teams card,
│       │                         rationale, scenarios help, metrics, …)
│       ├── api.ts                Typed REST client
│       ├── auth.ts               Token storage + authedFetch wrapper
│       └── App.tsx               Layout + state
│
├── tests/                        pytest suite (auth, cases, scenarios, sources)
├── docs/                         Architecture + authoring guides
├── Dockerfile                    Multi-stage build
├── docker-compose.yaml           Backend + Caddy with auto-TLS
└── pyproject.toml                Top-level Python project
```

The framework package (`hitl-context/`) is reusable on its own — the
backend depends on it the same way any external project would. This gives
you a clean swap path: replace the FastAPI app with whatever wrapper you
need, keep the framework's typed envelope + binder Protocols.

---

## Documentation

| Path | Topic | Audience |
|---|---|---|
| [docs/overview.md](docs/overview.md) | What the system is, who uses it, the mental model, an end-to-end walkthrough, what's been built, what's next. | Non-technical / managers / new joiners |
| [docs/architecture.md](docs/architecture.md) | Big-picture diagram, layer-by-layer breakdown with file paths, the three core flows (case lifecycle, fallback chain, ontology resolution), extension seams. | Engineers |
| [docs/scenarios.md](docs/scenarios.md) | Scenario authoring: anatomy, HITL vs autonomous, stage knowledge, full examples, lifecycle (built-in / auto / custom). | Scenario authors |
| [docs/ontology.md](docs/ontology.md) | Ontology layer: document format, source mappings, `ontology_queries:` block, NL playground, Neo4j connector, authoring tutorial. | Engineers + ontology authors |
| [docs/scaling.md](docs/scaling.md) | When to add scenarios vs. when to manage growth. Top-K UX, auto-generation patterns, ontology as a scaling lever, the staged roadmap. | Architects |
| [docs/production.md](docs/production.md) | Deployment guide: required config, security checklist, what's still deferred, smoke-test checklist. | Ops / deployers |
| [hitl-context/docs/framework.md](hitl-context/docs/framework.md) | Framework reference: protocols, transports, knowledge envelope. | Engineers extending the framework |
| [hitl-context/docs/context_flow.mermaid](hitl-context/docs/context_flow.mermaid) | Visual diagram of the four-stage flow. | Anyone |
| In-app **Scenarios guide** (status bar pill) | Same content as scenarios.md, navigable in the running app. | Operators |

---

## Switching LLM providers

Edit `.env`:

```bash
LLM_PROVIDER=openai      # or "azure" or "fake"
OPENAI_API_KEY=sk-...
OPENAI_MODEL=gpt-4o-mini

# Azure (when LLM_PROVIDER=azure)
AZURE_OPENAI_API_KEY=
AZURE_OPENAI_ENDPOINT=
AZURE_OPENAI_API_VERSION=2024-10-21
AZURE_OPENAI_DEPLOYMENT=
```

The model name is free-form — set it to whatever your account / deployment
exposes (e.g. `gpt-4o`, `gpt-4o-mini`, your Azure deployment name).

`LLM_PROVIDER=fake` runs the entire UI without any credentials, using a
deterministic keyword classifier. Great for development and demos.

---

## Type-generation (frontend ↔ backend)

The frontend keeps a hand-maintained `src/types.ts` for the most-used
shapes. For full coverage that won't drift:

```bash
# (with uvicorn running on :8001)
cd frontend && npm run gen-types
```

This regenerates `src/api-types.ts` from FastAPI's `/openapi.json`. Re-run
whenever you add or change a backend endpoint.

---

## Testing

```bash
# Framework regression — 90/90 expected
python hitl-context/tests/verify_package.py

# Backend pytest — 21/21 expected
pytest tests/

# Frontend type-check + bundle
cd frontend && npx tsc --noEmit && npm run build

# Original SC-TC-007 framework example end-to-end
python hitl-context/examples/sc_guardrails_integration.py
```

CI runs all four on every push (`.github/workflows/ci.yaml`).

---

## Production deployment

The bundled `Dockerfile` builds the frontend in a node stage and copies
the static assets into a Python runtime image. `docker-compose.yaml`
brings it up alongside Caddy with auto-TLS:

```bash
echo "JWT_SECRET=$(openssl rand -hex 32)" > .env.docker
echo "DOMAIN=hitl.your-domain.com" >> .env.docker
echo "OPENAI_API_KEY=sk-..." >> .env.docker
docker compose --env-file .env.docker up -d
```

Read [docs/production.md](docs/production.md) before going live. It covers
the security checklist (real `JWT_SECRET`, rotate the seeded admin
password, HTTPS, rate limiting, read-only DB user for the playground,
backups, LLM cost cap) and the items still deferred (single-worker
limitation, no password reset, no audit-log retention policy).

---

## What's *not* yet wired (and why)

These are deliberate trade-offs documented in
[docs/production.md](docs/production.md) — call them out so you can pick
which to address first.

- **Single-process state** — case-store, decision events, and the SSE bus
  live in memory. Horizontal scale needs Redis-backed state and the
  framework's `AsyncQueueTransport` against Kafka/SQS.
- **No password reset / email verification** — auth is demo-grade. Wire
  SMTP if you need it.
- **No structured metrics emission** — the dashboard reads from SQLite;
  there's no Prometheus instrumentation yet.
- **Teams card is rendered locally** — wire-compatible JSON, but the UI
  shows the card itself; nothing actually posts to MS Teams. Swap in
  a webhook to make this a real surface.
- **Real KF / ERP / IAM connectors** are not provided — built-in scenarios
  use fixture data. Drop in real `KnowledgeResolver` implementations to
  upgrade. The recommended path for cross-source knowledge is the planned
  ontology layer ([docs/ontology.md](docs/ontology.md)) — one ontology +
  N source mappings replaces N scenario rewrites.

The architecture is built around clean swap points: every piece above is
a Protocol the framework already declares, so each upgrade is one new
class, not a refactor.

---

## License

Private / not yet licensed. Add a `LICENSE` file before any public release.

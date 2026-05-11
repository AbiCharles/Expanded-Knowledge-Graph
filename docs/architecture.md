# System architecture

A reference for engineers working in this codebase. Pairs with
[overview.md](overview.md) (the non-technical version), [ontology.md](ontology.md)
(the schema-layer design), and [scenarios.md](scenarios.md) (scenario
authoring). Skim this first if you're new to the repo.

## Big picture

```
┌────────────────────────────────────────────────────────────────────────────┐
│                            FRONTEND (React + Vite)                         │
│  ┌──────────────┐  ┌─────────────┐  ┌──────────────┐  ┌──────────────┐    │
│  │   Console    │  │ FlowStage   │  │  Lineage     │  │  Knowledge   │    │
│  │  composer +  │  │ 4-stage     │  │  panel       │  │  modal       │    │
│  │  chip list   │  │ envelope    │  │              │  │  ┌──┬──┬──┐  │    │
│  │              │  │             │  │              │  │  │DS│ON│AC│  │    │
│  └──────────────┘  └─────────────┘  └──────────────┘  └──┴──┴──┴──┘  │    │
└──────────────┬─────────────────────────────────────────────────────────────┘
               │  REST + SSE (token-auth via JWT)
┌──────────────▼─────────────────────────────────────────────────────────────┐
│                         BACKEND (FastAPI app)                              │
│                                                                            │
│  ┌──────────────────────────────────────────────────────────────────────┐  │
│  │                    Operator-facing flow (orchestrator)               │  │
│  │   prompt → AgentRuntime.interpret_prompt → scenario picked           │  │
│  │      → 4-stage case (intake → proposal → review → execute)           │  │
│  │      → SSE events stream phase + facts to the UI                     │  │
│  └────────────────────┬─────────────────────────────────────────────────┘  │
│                       │                                                    │
│         ┌─────────────┼─────────────┬──────────────────────┐               │
│         ▼             ▼             ▼                      ▼               │
│  ┌────────────┐ ┌──────────┐ ┌─────────────┐ ┌─────────────────┐          │
│  │ Scenarios  │ │ Ontology │ │   Actions   │ │  Data sources   │          │
│  │ Registry   │ │ Registry │ │  Registry   │ │  Registry       │          │
│  │ (YAML)     │ │ + Mapping│ │  (YAML)     │ │  (YAML)         │          │
│  └────────────┘ └────┬─────┘ └──────┬──────┘ └────────┬────────┘          │
│                      │              │                 │                    │
│                      ▼              ▼                 │                    │
│              ┌────────────────┐  ┌──────────────┐     │                    │
│              │OntologyResolver│  │ Executors    │     │                    │
│              │ (fans out →)   │  │ sql_update,  │     │                    │
│              │                │  │ http_request │     │                    │
│              └────────┬───────┘  └──────┬───────┘     │                    │
│                       │                 │             │                    │
│                       └────────┬────────┴─────────────┤                    │
│                                ▼                      ▼                    │
│                        ┌───────────────────────────────────┐               │
│                        │   KnowledgeResolver Protocol      │               │
│                        │  csv | sqlite | postgres | http   │               │
│                        │  vector | neo4j                   │               │
│                        └───────────────────────────────────┘               │
└────────────────────────────────────────────────────────────────────────────┘
                                    │
        ┌───────────────────────────┼─────────────────────────┐
        ▼                           ▼                         ▼
   App SQLite               External sources              Neo4j (Bolt)
   • cases                  • CSV files                   • read via
   • lineage                • SQLite governance.sqlite      assert_read_only
   • users                  • Postgres governance            guard
                            • vector embeddings (.npz)
                            • HTTP REST APIs
```

---

## Layers

### Framework layer ([hitl-context/](../hitl-context/))

The reusable HITL Context Framework — a separate package the app
depends on. **Doesn't know about your domain, your scenarios, or your
data.** Defines:

- **Models** ([models.py](../hitl-context/src/tcs_hitl_context/models.py)) — `KnowledgeContext`, `KnowledgeFact`, `KnowledgeRef`, `KnowledgeQuery`, `AgentAction`, `StageContext`, `LineageEvent`, `ReviewTicket`, `ReviewDecision`. Pydantic; `payload` and `extra="allow"` give you escape hatches.
- **Protocols** ([protocols.py](../hitl-context/src/tcs_hitl_context/protocols.py)) — `KnowledgeResolver`, `KnowledgeResolverRegistry`, `AgentIntakeBinder`, `ProposalBinder`, `ReviewBinder`, `HITLTransport`, `ReviewerSurface`, `LineageRecorder`.
- **HITLContextService** — orchestrator: `open_case` → `attach_proposal` → `submit_for_review` → `collect_decision`.
- **Transports** — `SyncInProcessTransport` (tests), `AsyncQueueTransport` (production).
- **TeamsAdaptiveCardSurface** — reference reviewer surface.
- **LLM adapter** — `OpenAIClient`, `AzureOpenAIClient`, `FakeLLMClient` behind a single `complete(system, user, response_format)` async method.

**The app extends, never modifies.** Every new capability (the
OntologyResolver, the action executors, the Cypher guard) is a Protocol
implementation.

### Backend layer ([backend/](../backend/))

#### Knowledge plane

Three sibling registries that together describe what data the agent can
see and act on:

- **DataSourceRegistry** ([backend/datasources/registry.py](../backend/datasources/registry.py)) — connection-only. Each spec is `{id, kind, config}`; loaded from [backend/data/sources.yaml](../backend/data/sources.yaml). Connector implementations: [csv_source.py](../backend/datasources/csv_source.py), [sqlite_source.py](../backend/datasources/sqlite_source.py), [postgres_source.py](../backend/datasources/postgres_source.py), [http_source.py](../backend/datasources/http_source.py), [vector_source.py](../backend/datasources/vector_source.py), [neo4j_source.py](../backend/datasources/neo4j_source.py). Each implements `KnowledgeResolver.resolve(query)` and reads kind-specific binding hints (`table` / `query_template` / `http_path_template`) from `query.filters["__binding__"]`.

- **OntologyRegistry** ([backend/ontology/loader.py](../backend/ontology/loader.py)) — the schema layer. Two YAML files per ontology (`<id>.yaml` for classes, `<id>.mappings.yaml` for source bindings) under [backend/ontologies/](../backend/ontologies/). Default-flagged ontologies refuse delete. Composes with:
  - **OntologyResolver** ([backend/ontology/resolver.py](../backend/ontology/resolver.py)) — itself a `KnowledgeResolver` Protocol impl. Translates an `OntologyQuery {ontology, class, where}` → fans out to every source the mapping covers → tags returned facts with `payload.via_ontology` and `payload.via_source_binding`.
  - **NL parser** ([backend/ontology/nl_query.py](../backend/ontology/nl_query.py)) — `parse_nl_query(prompt, ontology, llm, attribute_samples)`. Schema-aware: uses sample values from `inspect_source` to normalize "Dutch" → `"NL"`.
  - **Mapper** ([backend/ontology/mapper.py](../backend/ontology/mapper.py)) — LLM-driven `suggest_mappings(ontology, schemas)` → draft `Mapping` for operator review.
  - **Schema introspection** ([backend/ontology/schema_introspect.py](../backend/ontology/schema_introspect.py)) — uniform per-source tables/columns/sample_values across all six connector kinds.
  - **Cypher safety** ([backend/ontology/cypher_safety.py](../backend/ontology/cypher_safety.py)) — `assert_read_only` rejects writes; used by every Cypher path.

- **ActionRegistry** ([backend/actions/loader.py](../backend/actions/loader.py)) — write actions. Each YAML file under [backend/data/actions/](../backend/data/actions/) declares an `Action` with typed `ActionArgument`s and an `Executor` (`sql_update` against SQLite/Postgres or `http_request` against an HTTP source). Default-flagged actions refuse delete. Composes with:
  - **NL picker** ([backend/actions/nl_picker.py](../backend/actions/nl_picker.py)) — `parse_nl_action(prompt, registry, llm)` → returns action_id + extracted arguments.
  - **Executors** ([backend/actions/executors.py](../backend/actions/executors.py)) — `execute_action(action, args, sources)` dispatches on `executor.kind`; returns an `ActionExecutionResult` (never raises).

#### Scenario plane

- **ScenarioRegistry** ([backend/scenario_loader.py](../backend/scenario_loader.py)) — loads `*.yaml` from [backend/scenarios/](../backend/scenarios/). Tracks per-scenario file mtime so the chip list sorts newest-first. Validates that no scenario uses the removed `queries:` block (raises `ScenarioSchemaError`).
- **Built-in scenarios** — 6 hand-authored YAMLs (SC-TC-007/008, SC-PP-007/AUTO-014, SC-LN-002/STATUS-009).
- **Generated scenarios** — three families, each in-memory or persisted with a marker that hides them from the chip list when ephemeral:
  - `SC-ONTO-<ontology>-<class>` — opt-in via Mappings tab "Generate lookup chip" button. Persisted. Has `_filter_from_prompt: true` so the orchestrator merges prompt-extracted filters into its empty `where: {}`.
  - `SC-ADHOC-<case_id>` — synthesized in-memory when the operator's NL→ontology fallback fires (`try_ontology_fallback=true` + no scenario match).
  - `SC-NLWRITE-<case_id>` — synthesized in-memory when the NL→action fallback fires (`try_action_fallback=true` + no scenario match + no ontology match).
- **Auto-scenario builder** ([backend/auto_scenario.py](../backend/auto_scenario.py)) — `make_ontology_scenario`, `make_adhoc_ontology_scenario`, `make_nlwrite_action_scenario`.

#### Orchestrator + binders

- **AgentRuntime** ([backend/agent_runtime.py](../backend/agent_runtime.py)) — `interpret_prompt(text)` → LLM picks scenario from catalog (or keyword fallback under `LLM_PROVIDER=fake`); `draft_action(scenario)` → instantiates the framework's `AgentAction` from the scenario's `action_payload`.
- **Binders** ([backend/binders.py](../backend/binders.py)) — three thin wrappers around `_facts_from_stage()` which reads each stage's `facts:` (inline) and `ontology_queries:` (live). Honours `:param` substitution from `action.payload` and merges `__prompt_filters__` for `_filter_from_prompt: true` chips.
- **Orchestrator** ([backend/orchestrator.py](../backend/orchestrator.py)) — `run_case(state, case)` is the coroutine spawned on confirm. Stages: agent intake → proposal (with optional prompt-filter pre-extraction) → policy decision (auto-approve vs HITL) → review (await reviewer) → optional executor invocation (for SC-NLWRITE-*) → emit "decided" SSE event → close stream.

#### State + persistence + auth

- **AppState** ([backend/state.py](../backend/state.py)) — singleton holding all registries, the LLM client, the in-memory transport (queue + decision store), the SSE bus, and the SQLite-backed `PersistentCaseStore` + `SqliteLineageRecorder`.
- **Persistence** ([backend/persistence/](../backend/persistence/)) — SQLite (`backend/data/app.sqlite`) for cases, lineage events, users. `Database` is a thin SQLAlchemy session factory.
- **Auth** ([backend/auth.py](../backend/auth.py)) — JWT (HS256) + bcrypt + token blocklist on logout.
- **Transport** — `InMemoryQueue` + `InMemoryDecisionStore` are concrete implementations of the framework's Protocol. Production swaps for Kafka/SQS + Redis.

#### API surface

[backend/api/](../backend/api/) — FastAPI routers:

| Router | Purpose |
|---|---|
| auth | login, register, logout, change-password, /me |
| cases | create (with two opt-in fallback flags), confirm, cancel, replay, relink, delete, get, events (SSE) |
| decisions | queue, post-decision (the reviewer-side action) |
| scenarios | list (mtime-sorted, `_adhoc`/`_nlwrite` filtered), autofill |
| datasources | list, add, upload-csv, test, schema, run-query, run-cypher, test-postgres, test-neo4j |
| ontologies | upload, list, get, delete, classes, mappings (get/put), suggest-mappings, generate-chip per class, structured query, NL query |
| actions | list, get, upload, delete, preview-nl |
| metrics | summary (totals, decisions-by-scenario, top rejection reasons) |
| exports | CSV download of cases + lineage |

### Frontend layer ([frontend/](../frontend/))

React + Vite + TypeScript. Single-page; everything mounts under `App.tsx`.

- **StatusBar** — top bar with one **Knowledge** button (collapses Data sources + Ontologies + Actions into one modal with three tabs), Metrics button, Scenarios guide, role pill, logout.
- **Console** — left pane: chat composer with two opt-in fallback toggles (ontology + write-action), suggested-prompt chips sorted newest-first, history view.
- **FlowStage** — middle pane: live four-stage envelope renderer (intake → proposal → review → execute), updated via SSE.
- **LineagePanel** — right pane: append-only event log per case.
- **KnowledgeModal** + **ActionsPanel** + **OntologyModal** + **DataSourcesModal** — three-tab knowledge management.
- **Modals**: TeamsCard (review surface), Approve/Rationale, Replay/Compare, ScenarioEdit, Metrics dashboard.

---

## Three core flows

### A. Case lifecycle (the spine)

```
Operator types prompt
      │
      ▼
POST /api/cases ── AgentRuntime.interpret_prompt ──┐
      │                                            ▼
      │                                   1. Scenario classifier (LLM)
      │                                   2. NL→ontology fallback (opt-in)
      │                                   3. NL→action fallback (opt-in)
      │
      ▼
CaseRecord {phase: "awaiting_clarification"}
      │  (UI shows clarifier + Did-You-Mean candidates)
      ▼
POST /api/cases/{id}/confirm ── orchestrator.run_case ──┐
                                                        ▼
                            STAGE 1: agent intake binder → SSE "stage_bound"
                                                        ▼
                            STAGE 2: draft_action → optional prompt-filter
                                     extraction → proposal binder → SSE
                                                        ▼
                                          policy.evaluate(scenario)
                                       ┌──────────────┴──────────────┐
                                  autonomous                     HITL
                                       │                            │
                                       ▼                            ▼
                            _finalise_autonomous          submit_for_review
                            (run executor if               (writes ticket to
                             SC-NLWRITE && hitl=false,     queue, awaits
                             emit auto_approved)            decision_event)
                                                                   │
                                                                   ▼
                                                       POST /api/decisions/{ticket}
                                                                   │
                                                                   ▼
                                                       collect_decision +
                                                       _maybe_run_executor
                                                       (SC-NLWRITE on approve)
                                                                   │
                                                                   ▼
                                                       SSE "decided" + close
```

### B. The fallback chain (in `create_case`)

```
prompt
  │
  ▼
1. classifier ── matched? ──yes──▶ return scenario (chip wins)
  │ no
  ▼
2. try_ontology_fallback ON?
  │ yes ── parse_nl_query against each ontology ──┐
  │                                                ▼
  │                                        class has mapping?
  │                                                │ yes
  │                                                ▼
  │                              synthesize SC-ADHOC-<case_id>
  │                              (autonomous, in-memory)
  │ no  / failed
  ▼
3. try_action_fallback ON?
  │ yes ── parse_nl_action against action registry ──┐
  │                                                   ▼
  │                                          action found + args extracted?
  │                                                   │ yes
  │                                                   ▼
  │                                  synthesize SC-NLWRITE-<case_id>
  │                                  (HITL by default, in-memory)
  │ no
  ▼
return scenario_id=None (UI shows "I'm not sure I can act on that")
```

### C. Ontology resolution (per query)

```
Binder sees ontology_queries: entry
  │
  ▼
substitute_payload_refs(where, action.payload)
   merge __prompt_filters__ (for _filter_from_prompt: true chips)
  │
  ▼
OntologyResolver.resolve_query(OntologyQuery)
  │
  ▼
look up class in ontology + its mapping
  │
  ▼
for each SourceBinding:
   translate where keys via attribute_map (e.g. supplier_id→vendor_id)
   attach __binding__ {data_source, identifier_column, table,
                       query_template, http_path_template} to filters
   call DataSourceRegistry.require(binding.data_source).resolve(query)
        │
        ▼
   underlying connector reads __binding__ (preferring query_template
   when present; auto-derives a SELECT *  / MATCH otherwise);
   strips framework-private filter keys; runs against the source
        │
        ▼
   facts come back; OntologyResolver tags each:
     payload.via_ontology       = "<onto>.<class>"
     payload.via_source_binding = "<source_id>"
        │
        ▼
   concatenate (no cross-source dedupe in v1) → return list[KnowledgeFact]
```

---

## Extension seams

| Want to add… | What you implement |
|---|---|
| A new data source kind | Subclass of `KnowledgeResolver` Protocol + branch in `DataSourceRegistry._build()` + frontend Add-form |
| A new write-action kind | New `Executor` variant + branch in `execute_action()` |
| A different reviewer surface (Slack, JIRA, ServiceNow, …) | Implement `ReviewerSurface` Protocol; swap into `AppState.surface` |
| A different transport (Kafka, SQS, Redis) | Implement `OutboundQueue` + `DecisionStore`; swap into `AppState.transport` |
| A different lineage sink (audit DB, Splunk) | Implement `LineageRecorder` Protocol; swap into `AppState.lineage` |
| RDF/Turtle ontology import | Add a parse path to `OntologyRegistry.from_directory` (rdflib already converts) |
| SHACL validation on uploaded ontologies | Add `pyshacl` import to the upload endpoint |
| Cross-source entity resolution | Extend `OntologyResolver.resolve_query` with a dedupe/merge step keyed by class identifier across bindings |

---

## Test gates

- **Backend:** 124 pytest cases across 8 files (auth, cases, scenarios+sources, neo4j, nl-writes, ontology loader/mapper/nl_query/resolver, ontology fallback). FakeLLM + mocked Neo4j driver — no live infra needed.
- **Framework:** 90 framework tests in [hitl-context/tests/verify_package.py](../hitl-context/tests/verify_package.py).
- **Frontend:** `npx tsc --noEmit` plus `npm run build` for bundle check.

---

## Deliberate cuts (what's NOT in here)

- Single-process state (no Redis-backed case store yet)
- Single-worker uvicorn (no horizontal scale)
- No password reset / email verification
- No multi-reviewer / quorum
- Cypher writes intentionally blocked at the resolver layer (use the action registry for graph mutations instead)
- No cross-source entity resolution (each source returns its own facts; reviewer sees both)
- No RDF/Turtle import (YAML/JSON only)

The architecture intentionally puts every one of these behind a single
Protocol/seam so each is a future PR, not a refactor.

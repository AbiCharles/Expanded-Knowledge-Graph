# Authoring Scenarios

A scenario is the blueprint for one type of action the agent can take. It tells
the framework: how to recognise an operator's intent, what knowledge to bind at
each stage, whether to require human review, and what to say back.

This document covers both ways to add scenarios:

- **Save-from-playground** — for read-only data lookups, in-app via the Query
  playground. Zero YAML, autonomous by default.
- **Hand-authored YAML** — for HITL flows or anything more structured. Drop a
  file in [backend/scenarios/](../backend/scenarios/) and restart uvicorn.

> See [docs/scaling.md](scaling.md) for guidance on when to add scenarios vs.
> when to manage scenario sprawl with templates / hierarchy / vector retrieval.

---

## Anatomy of a scenario

A scenario answers eight questions:

```
┌──────────────────────────────────────────────────────────────────────┐
│ Identity                                                             │
│   id, title, domain, actor_id, operator_role, reviewer_role          │
│                                                                      │
│ Intent                                                               │
│   match_keywords          → how prompts route here                   │
│   interpreted_as          → paraphrase shown to operator             │
│   clarifying_question     → "Did you mean X?" before binding         │
│                                                                      │
│ Action                                                               │
│   action_type             → categorical label                        │
│   action_payload          → typed envelope the framework executes    │
│                                                                      │
│ Mode                                                                 │
│   autonomous: true|false  → governs whether HITL review is required  │
│   auto_approval_*         → autonomous only                          │
│                                                                      │
│ Knowledge bound at each stage                                        │
│   stages.agent_intake     → policies, scopes (always)                │
│   stages.proposal         → master data refs (always)                │
│   stages.review           → reviewer evidence package (HITL only)    │
│                                                                      │
│ What the reviewer sees                                               │
│   teams_channel, teams_headline, rationale_reasons,                  │
│   execute_message                                                    │
│                                                                      │
│ Outcomes                                                             │
│   outcomes.approve / reject / request_more_info / auto_execute       │
│                                                                      │
│ Closing message                                                      │
│   closing_messages.{...}  for HITL                                   │
│   closing_message         for autonomous                             │
└──────────────────────────────────────────────────────────────────────┘
```

---

## Two flow shapes

### HITL — `autonomous: false`

Three binder stages (intake, proposal, review). The case enters
`review_ready`, a Teams card is rendered, the reviewer decides. Required
fields specific to HITL:

```yaml
autonomous: false
reviewer_role: { label: Reviewer, name: <name> }
teams_channel: "#channel-name"
teams_headline: "Card title shown to reviewer"
execute_message: "Confirmation text for approve modal"

stages:
  agent_intake: { binder, facts? , queries? }
  proposal:     { binder, facts? , queries? }
  review:       { binder, facts? , queries? }   # required for HITL

rationale_reasons:
  reject:             ["reason 1", "reason 2", ...]
  request_more_info:  ["question 1", "question 2", ...]

outcomes:
  approve:           { headline, detail }
  reject:            { headline, detail }
  request_more_info: { headline, detail }

closing_messages:
  approve:           "Final agent message after approve. {rationale} interpolated."
  reject:            "...after reject..."
  request_more_info: "...after more info..."
```

### Autonomous — `autonomous: true`

Two binder stages. The framework auto-approves and executes without human
review. Required fields specific to autonomous:

```yaml
autonomous: true
auto_approval_guardrail: "GR-..."
auto_approval_reason: "Why this action is safe to auto-execute."

stages:
  agent_intake: { binder, facts? , queries? }
  proposal:     { binder, facts? , queries? }
  # no review stage

outcomes:
  auto_execute: { headline, detail }

closing_message: "Single closing message. No decision branching."
```

---

## Stage knowledge: `facts:` vs `queries:`

Each binder stage can hold either or both:

### `facts:` — inline literal facts

Use for static, demo-stable data. Good for policies, actor scopes, and
anything that doesn't change between runs.

```yaml
stages:
  agent_intake:
    binder: PolicyAndScopeAgentBinder/1.0
    facts:
      - source: "kf:graph"
        ontology_type: "Policy"
        id: "POL-TC-OVERRIDE-2026-Q2"
        uri: "kf.tcs/policy/POL-TC-OVERRIDE-2026-Q2"
        title: "TC override policy"
        payload: "Critical TC overrides require named compliance officer."
```

### `queries:` — live data via registered sources

Use when the fact comes from a real source that may change over time. The
binder resolves these at bind time against the `DataSourceRegistry`.

```yaml
stages:
  proposal:
    binder: TradeOverrideProposalBinder/2.0-live
    queries:
      - data_source: products_csv      # source id from sources.yaml
        ontology_type: Product
        filter: { product_id: P-EL-9001 }
        purpose: "Bind product master record"
```

`filter:` is passed to the resolver as `KnowledgeQuery.filters`. Its
interpretation depends on the connector kind (column match for CSV, named SQL
params for SQLite/Postgres, path template substitution for HTTP, query
string for vector store).

You can mix both blocks in the same stage. The combined facts go into the
`StageContext`.

---

## Field reference

| Field | Required? | Notes |
|---|---|---|
| `id` | yes | Unique, `^[A-Za-z0-9][A-Za-z0-9_\-]+$`. Convention: `SC-<DOMAIN>-<NN>`, `SC-AUTO-<source>` for auto-generated, `SC-CUSTOM-<slug>` for save-from-playground. |
| `title` | yes | Human label shown in the chat header and case list. |
| `domain` | yes | Broad category (Trade Compliance, Procurement, Logistics, Custom data sources). |
| `actor_id` | yes | Agent identity recorded on every lineage event. |
| `operator_role` | yes | `{ label, name }` — pill in the status bar. |
| `reviewer_role` | HITL | `{ label, name }` — pill when in reviewer mode. |
| `autonomous` | yes | `true` skips review; `false` requires it. |
| `match_keywords` | yes | Lowercase tokens. The classifier matches on hits. |
| `interpreted_as` | yes | Paraphrase the agent reads back to the operator. |
| `clarifying_question` | yes | HTML allowed. Confirms before binding. |
| `action_type` | yes | Categorical (e.g. `trade_override`, `data_lookup`). |
| `action_payload` | yes | Dict. Becomes `AgentAction.payload` at bind time. |
| `auto_approval_guardrail` | autonomous | Guardrail id shown on the auto-approve badge. |
| `auto_approval_reason` | autonomous | Plain text shown on the badge. |
| `teams_headline` | HITL | Card title. |
| `teams_channel` | HITL | `#channel-name`. |
| `execute_message` | HITL | Approve confirmation text. HTML allowed. |
| `rationale_reasons` | HITL | `{ reject: [...], request_more_info: [...] }` quick-pick chips. |
| `stages` | yes | See above. |
| `outcomes` | yes | Per-decision `{ headline, detail }`. |
| `closing_messages` | HITL | Per-decision; `{rationale}` interpolated. |
| `closing_message` | autonomous | Single final agent message. |

---

## Quality guidelines

### Match keywords

- **3–7 specific terms** per scenario. More = more false matches.
- Avoid generic words like `data`, `lookup`, `query`, `report`. They hijack other scenarios.
- Include the canonical id of the entity the action touches (e.g. `S-700412`, `SC-TC-001`).
- Lowercase everything; the classifier lowercases the prompt first.

### Inline facts vs live queries

- **Inline `facts:`** for facts that should be reproducible across runs (policy text, actor scope, the agent's own self-description).
- **Live `queries:`** for facts that come from a source of truth (master data, prior cases, sanctions list, vector store).
- Mixing both in one stage is normal. The agent intake stage almost always has inline facts; the proposal/review stages often mix.

### One scenario per discrete intent

Don't bundle "lookup X and onboard X" into one scenario. Two scenarios that
chain via the agent runtime is cleaner than one super-scenario with branching
logic.

### Autonomous vs HITL

- **Autonomous** for read-only data lookups, parameter changes within an
  approved envelope, and any action where the guardrail engine can establish
  safety deterministically.
- **HITL** for any irreversible commitment, policy override, or action where
  judgement matters more than process.

### Anti-patterns to avoid

| Anti-pattern | Why it bites |
|---|---|
| Vague keywords | Every prompt routes here, classifier accuracy collapses |
| Empty `facts:` AND `queries:` on a stage | Stage binds nothing, envelope is empty |
| `clarifying_question` repeats the prompt | Operator can't tell if the agent understood |
| HITL scenario with `closing_messages` only for `approve` | Reject + more-info paths render blank |
| `match_keywords` overlap with another scenario's | Top-K shows both with similar confidence — confusing |
| Inline facts that should be live | Stale data goes through review |

---

## Worked examples (already in the repo)

| File | Domain | Mode | Notable |
|---|---|---|---|
| [SC-TC-007.yaml](../backend/scenarios/SC-TC-007.yaml) | Trade Compliance | HITL | Sanctions override, all inline facts |
| [SC-TC-008.yaml](../backend/scenarios/SC-TC-008.yaml) | Trade Compliance | HITL | Live-data twin — pulls from CSV + SQLite + vector store |
| [SC-PP-007.yaml](../backend/scenarios/SC-PP-007.yaml) | Procurement | HITL | Vendor onboarding |
| [SC-LN-002.yaml](../backend/scenarios/SC-LN-002.yaml) | Logistics | HITL | Mode switch (ocean → air) |
| [SC-LN-STATUS-009.yaml](../backend/scenarios/SC-LN-STATUS-009.yaml) | Logistics | Autonomous | Read-only ETA lookup |
| [SC-PP-AUTO-014.yaml](../backend/scenarios/SC-PP-AUTO-014.yaml) | Procurement | Autonomous | Reorder-point parameter change |

Open any of them — they're the same shape, just different domain content.

---

## Save-from-playground (the easy path)

The Query playground's "Save as scenario" form covers most of the boilerplate:

| Form field | Maps to |
|---|---|
| **Title** | `title` |
| **Suggested prompt** | the chip text in the operator console |
| **Match keywords** (comma-separated) | `match_keywords` |
| **Clarifying question** | `clarifying_question` |
| **Ontology type** | `action_payload.ontology_type` and the `queries:` block |

Hidden defaults (set automatically):

- `autonomous: true`, `action_type: data_lookup`, `actor_id: agent-data-lookup`
- `agent_intake` stage with policy + scope inline facts
- `proposal` stage with one `queries:` entry whose `sql_override` is your saved SQL
- `auto_approval_guardrail: GR-AUTO-LOOKUP`
- `outcomes.auto_execute` derived from your title

If the form's defaults don't fit (you need HITL, or richer structure), hand-author a YAML and drop it into `backend/scenarios/`.

---

## Lifecycle

- **Built-in scenarios** (`SC-TC-*`, `SC-PP-*`, `SC-LN-*`) — committed to the
  repo. Cannot be deleted via the API.
- **Auto-scenarios** (`SC-AUTO-<source_id>`) — created automatically when an
  operator-registered data source is added. Removed when the source is removed.
- **Custom scenarios** (`SC-CUSTOM-<slug>`) — created via "Save as scenario".
  Persist in `backend/scenarios/` until explicitly deleted via the API.

All three types appear in the operator console's chip list and can be invoked
the same way.

# Authoring Scenarios

## What is a scenario?

A **scenario** is the framework's blueprint for *one type of action the agent
can take*. Think of it as a recipe: the operator says something in plain
language, the framework matches the request to a recipe, follows it
step-by-step (binding the right knowledge at each stage), runs the action —
and either executes autonomously or routes through a human reviewer first.

> **Example.** An operator types "Override the SC-TC-001 block on order
> ORD-44216." The framework matches that to the `SC-TC-007` scenario. It binds
> the active trade-compliance policy, the agent's IAM scope, the product
> master record, the contract, prior similar overrides, and an applicable
> SOP — then renders all of that as evidence for a compliance officer to
> review.

What scenarios *do*:

1. **Route prompts.** The classifier scans every scenario's `match_keywords`
   and `interpreted_as` phrasing and picks the best match.
2. **Tell the agent what to read.** Each scenario specifies which knowledge
   gets bound at each stage (intake, proposal, review).
3. **Decide whether a human needs to look.** Autonomous scenarios skip review
   and execute directly. HITL scenarios stop at the review stage.
4. **Render the right surfaces.** Teams card title, rationale-reason chips,
   outcome banner, closing message.

What scenarios are **not**:

- Not the binders themselves. Binders are Python in `backend/binders.py`.
- Not the agent's reasoning. The LLM only consults scenarios for
  classification.
- Not persistent state. Each case run reads the YAML fresh; the data envelope
  is the case's state, not the YAML.

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

## HITL vs autonomous

Every scenario picks one of two flow shapes. The choice governs whether a
human gets to inspect and approve the action before it happens.

### HITL (Human In The Loop) — `autonomous: false`

The agent does the reasoning and proposes an action, **but stops before
executing**. The framework binds an evidence package (everything from the
proposal stage plus a review-only stage with prior cases / SOPs / sanctions
checks), renders it as a Teams Adaptive Card, and waits for a named reviewer
to decide.

The reviewer sees three buttons:

- **Approve** → outcome banner, agent executes
- **Reject** → outcome banner, action aborted, rationale captured
- **Need more info** → case loops back to review with the reviewer's questions appended

The case spends measurable time in `review_ready` (seconds to hours,
depending on the reviewer). The framework's async transport keeps the case
envelope persisted while waiting.

**Required HITL-only fields:**

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

The agent reasons, the framework verifies the action against a named
guardrail, and **executes immediately without human review**. The reviewer
sees an "auto-approved by guardrail" badge in the case history afterward —
but isn't a gate in the flow.

The case never enters `review_ready`. From the operator's perspective the
agent appears to "just do it" — the envelope still binds and lineage still
records every step, but execution doesn't pause.

**Required autonomous-only fields:**

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

### How to choose

**Choose autonomous when…**

- The action is **read-only** (data lookups, status checks, dashboards).
- The action is a **parameter change within a pre-approved envelope** (e.g. reorder-point adjustments within ±50%, mode switches under 25% cost uplift).
- A guardrail engine can establish safety **deterministically** — clear yes/no rules, not judgement calls.
- **Reversibility is high**: if it's wrong, you can undo it cheaply.

**Choose HITL when…**

- The action is **irreversible or expensive to undo** — sanctions overrides, vendor onboarding commitments, payments above a threshold.
- The action requires **judgement** the agent can't capture in code — interpreting a customer's claimed license, weighing a strategic supplier relationship, deciding when a precedent has stretched too far.
- It involves **regulatory or audit obligations** — sanctions screening, AML, export controls, fiduciary decisions.
- Stakes are high enough that a "two-person rule" or named-officer signoff is required by policy.

> **Rule of thumb.** Autonomous = "the framework knows enough to be safe alone."
> HITL = "we want a human's name on this decision in the audit log."
> When in doubt, ship HITL first; you can promote a scenario to autonomous later by adding a guardrail and flipping the flag, but you can't easily un-execute an autonomous mistake.

---

## Stage knowledge: `facts:` vs `ontology_queries:`

> **Phase 3.C:** the legacy `queries:` block (which named a data source
> id directly) has been hard-removed. Loading a YAML that still uses it
> raises `ScenarioSchemaError` at startup with the migration recipe in
> the message. New scenarios bind live data via `ontology_queries:` —
> the OntologyResolver dispatches to whichever sources the mapping
> covers.

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

### `ontology_queries:` — live data via the ontology layer

Use when the fact comes from a real source that may change over time.
The binder hands the request to the OntologyResolver, which uses the
mapping doc to fan out to whichever data source(s) back this class.

```yaml
stages:
  proposal:
    binder: TradeOverrideProposalBinder/2.0-live
    ontology_queries:
      - ontology: tcs_core
        class: Product
        where: { product_id: P-EL-9001 }
        purpose: "Bind product master record"
```

`where:` keys are ontology attribute names; the resolver translates
them to source-native columns via the binding's `attribute_map`. Per-
fact provenance (`payload.via_ontology`, `payload.via_source_binding`)
is added so the reviewer card can show *what* was asked AND *where* the
answer came from.

You can mix both blocks in the same stage. The combined facts go into the
`StageContext`.

---

## Three coexistence patterns

| Pattern | What it looks like | Use when |
|---|---|---|
| **A — facts-only** | Only `facts:` blocks | Pure mock/demo flows where no live data is needed |
| **B — hybrid** | `facts:` + `ontology_queries:` together | Stable seeded data + live ontology-driven fetch on the same stage |
| **C — ontology-first** | Only `ontology_queries:` | The scenario is portable across source layouts (CSV in dev, Postgres + Neo4j in prod) |

Field-by-field on the `ontology_queries:` entry:

| Field | Required? | Notes |
|---|---|---|
| `ontology` | yes | The `id` of an uploaded ontology. |
| `class` | yes | Class name from that ontology. |
| `where` | optional | `{attribute: value}` map. Values starting with `:` reference `action.payload` keys, exactly like `queries.filter` already does. |
| `include_relations` | optional | List of relation names from the class definition. Each related class is bound via its own mapping, with `payload.related_via` set on those facts. |
| `purpose` | optional | Free-text rationale; recorded in lineage. |
| `max_results` | optional | Default 50. |

What the reviewer sees doesn't change — the Teams card and review panel
still render `StageContext.facts`. Two new things appear on each
ontology-bound fact's `payload`:

- `via_ontology: "supply_chain_v1.Supplier"` — what was asked.
- `related_via: "Supplier.places"` — present only on facts pulled in via `include_relations`.

The full design (mapping doc shape, NL query playground, auto-scenarios
per class, Neo4j connector, error semantics) lives in
[docs/ontology.md](ontology.md).

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

| Anti-pattern | The issue |
|---|---|
| Vague keywords | Every prompt routes here, classifier accuracy collapses |
| Empty `facts:` AND `ontology_queries:` on a stage | Stage binds nothing, envelope is empty |
| `clarifying_question` repeats the prompt | Operator can't tell if the agent understood |
| HITL scenario with `closing_messages` only for `approve` | Reject + more-info paths render blank |
| `match_keywords` overlap with another scenario's | Top-K shows both with similar confidence — confusing |
| Inline facts that should be live | Stale data goes through review |

---

## Full examples

Two complete YAMLs you can use as templates. Drop a copy into
`backend/scenarios/`, edit the domain content, and restart uvicorn.

### HITL example — sanctions override

Trade-compliance scenario. The agent proposes overriding a sanctions block;
a compliance officer reviews the evidence (policy, master data, prior cases,
SOP excerpts) and decides approve / reject / need more info.

```yaml
id: SC-TC-007
title: "Trade override — sanctioned counterparty"
domain: "Trade Compliance"
teams_channel: "#trade-compliance"
actor_id: "agent-trade-01"
operator_role: { label: "Operator", name: "trade.analyst.dlin" }
reviewer_role: { label: "Reviewer", name: "compliance.officer.kchen" }
autonomous: false

action_type: "trade_override"
action_payload:
  originating_guardrail_id: "SC-TC-001"
  product_id: "P-EL-9001"
  counterparty_name: "Sanctioned Pharma Holdings"
  destination_country: "IR"
  contract_id: "K-2026-0182"

teams_headline: "Trade override — SC-TC-001 sanctions block"
execute_message: >-
  The agent will execute the override. The order to <strong>Sanctioned Pharma
  Holdings</strong> will proceed and the SC-TC-001 block will be cleared on this case only.

match_keywords: ["override", "sanction", "ofac", "block", "eccn", "ord-44216"]
interpreted_as: "override the SC-TC-001 sanctions block on order ORD-44216"
clarifying_question: >-
  Just to confirm — override the SC-TC-001 sanctions block on counterparty
  <strong>Sanctioned Pharma Holdings</strong> for product <code>P-EL-9001</code>?
  This is a critical override that requires named compliance officer approval.

closing_messages:
  approve: >-
    <strong>Compliance officer approved.</strong> Override granted; proceeding to execute.
  reject: >-
    <strong>Compliance officer rejected the override.</strong> Reason: <em>"{rationale}"</em>
  request_more_info: >-
    <strong>Compliance officer needs more information.</strong> Specifically: <em>"{rationale}"</em>

rationale_reasons:
  reject:
    - "OFAC license could not be verified — counterparty remains on SDN list."
    - "Customer documentation insufficient to clear sanctions match."
    - "Override pattern is unusual — escalating to legal."
  request_more_info:
    - "Need a copy of the OFAC license and its expiration date."
    - "Need end-user verification and intended-use documentation."
    - "Need customer compliance attestation signed by their export officer."

stages:
  agent_intake:
    binder: "PolicyAndScopeAgentBinder/1.0"
    facts:
      - source: "kf:graph"
        ontology_type: "Policy"
        id: "POL-TC-OVERRIDE-2026-Q2"
        uri: "kf.tcs/policy/POL-TC-OVERRIDE-2026-Q2"
        title: "TC override policy"
        payload: "Critical TC overrides require named compliance officer."
      - source: "iam:scopes"
        ontology_type: "ActorScope"
        id: "agent-trade-01"
        uri: "iam.tcs/actors/agent-trade-01"
        title: "Actor scope"
        payload: "Scopes: sc.read, sc.propose, sc.execute_after_review"

  proposal:
    binder: "TradeOverrideProposalBinder/1.0"
    facts:
      - source: "erp:material_master"
        ontology_type: "Product"
        id: "P-EL-9001"
        uri: "erp.tcs/products/P-EL-9001"
        title: "Encryption module"
        payload: "ECCN 5A002 · HTS 8517.62.00 · controlled"
    queries:
      - data_source: sanctions_csv
        ontology_type: SanctionedEntity
        filter: { name: "Sanctioned Pharma Holdings" }
        purpose: "Confirm OFAC SDN match"

  review:
    binder: "TradeOverrideReviewBinder/1.0"
    queries:
      - data_source: governance_sqlite
        ontology_type: PriorOverride
        filter: { scenario_id: SC-TC-007, max_results: 3 }
        purpose: "Surface prior similar overrides"
      - data_source: policy_corpus
        ontology_type: PolicyExcerpt
        filter: { query: "OFAC override license verification", top_k: 3 }
        purpose: "Retrieve relevant SOP excerpts"

outcomes:
  approve:
    headline: "Approved with conditions"
    detail: "Override granted pending verified license."
  reject:
    headline: "Rejected — sanctions hit confirmed"
    detail: "Override denied per SOP-TC-OVERRIDE-001."
  request_more_info:
    headline: "More information requested"
    detail: "Reviewer requested OFAC license documentation before deciding."
```

### Autonomous example — read-only data lookup

Logistics scenario. The agent fetches a shipment's live status. No human
review; auto-cleared by a read-only guardrail.

```yaml
id: SC-LN-STATUS-009
title: "Shipment status lookup"
domain: "Logistics & Network"
autonomous: true
actor_id: "agent-logistics-31"
operator_role: { label: "Operator", name: "planner.lvenkat" }

action_type: "shipment_status_lookup"
action_payload:
  shipment_id: "S-700499"
  query_type: "live_status"
  scope: "logistics.read"

match_keywords: ["eta", "status", "where is", "track", "shipment status", "s-700499"]
interpreted_as: "look up the current status and ETA on shipment S-700499"
clarifying_question: >-
  Just to confirm — pull the current status and ETA on shipment <code>S-700499</code>.
  Read-only query within my <code>logistics.read</code> scope; per policy
  <code>GR-LN-AUTO-001</code>, no human review is required. Proceed?

auto_approval_guardrail: "GR-LN-AUTO-001"
auto_approval_reason: "Read-only logistics query within agent scope. Policy GR-LN-AUTO-001 permits autonomous status checks."

closing_message: >-
  Done — the status query was auto-approved by <code>GR-LN-AUTO-001</code>.
  <strong>Shipment S-700499</strong>: ETA now <strong>Apr 30</strong>. No action required.

stages:
  agent_intake:
    binder: "PolicyAndScopeAgentBinder/1.0"
    facts:
      - source: "kf:graph"
        ontology_type: "Policy"
        id: "POL-LN-READONLY-2026"
        uri: "kf.tcs/policy/POL-LN-READONLY-2026"
        title: "Read-only logistics policy"
        payload: "Read-only queries are autonomous within logistics.read scope."
      - source: "iam:scopes"
        ontology_type: "ActorScope"
        id: "agent-logistics-31"
        uri: "iam.tcs/actors/agent-logistics-31"
        title: "Actor scope"
        payload: "Scopes: logistics.read · this query: logistics.read only"

  proposal:
    binder: "ShipmentLookupProposalBinder/1.0"
    facts:
      - source: "tms:shipments"
        ontology_type: "Shipment"
        id: "S-700499"
        uri: "tms.tcs/shipments/S-700499"
        title: "Shipment record"
        payload: "Origin Singapore · Dest Rotterdam · 8 pallets · ocean booking"
      - source: "tms:tracking"
        ontology_type: "LiveTrack"
        id: "TRK-S-700499"
        uri: "tms.tcs/tracking/TRK-S-700499"
        title: "Live tracking"
        payload: "Vessel MV NORDIC CRYSTAL · 12 nm off Rotterdam · ETA Apr 30 04:00 UTC"

outcomes:
  auto_execute:
    headline: "Auto-executed — status retrieved"
    detail: "ETA confirmed as Apr 30. Vessel 12 nm off Rotterdam. No action required."
```

Both shapes share `id`, `title`, `domain`, `actor_id`, `operator_role`,
`match_keywords`, `interpreted_as`, `clarifying_question`, `action_type`,
`action_payload`, and `stages.{agent_intake, proposal}`. The differences are
entirely in the review-related fields.

## Other scenarios already in the repo

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

Three kinds of scenarios coexist in the chip list. They differ in how they
get there, who can edit them, and how they're removed.

### Built-in scenarios — `SC-TC-*`, `SC-PP-*`, `SC-LN-*`

Hand-authored YAMLs committed to the repo at
[`backend/scenarios/`](../backend/scenarios/). Loaded once at uvicorn
startup. **Read-mostly:** the in-app pencil lets you edit titles, keywords,
and clarifiers, and changes persist to disk; the structural fields
(`stages`, `action_type`, `autonomous`) stay locked because changing them
mid-flight risks breaking running cases.

The chip's edit modal does **not** offer a Remove button for built-ins — to
delete one, remove its YAML file and restart uvicorn. This is intentional:
built-ins represent the canonical, version-controlled scenario catalogue.

### Auto-scenarios — `SC-AUTO-<source_id>`

Created automatically by [`backend/auto_scenario.py`](../backend/auto_scenario.py)
when an operator-registered data source is added. They're autonomous (no
human review), use the framework's `data.read` scope, and bind facts from
their source via the `queries:` block. The chip text and match_keywords are
derived from the source id.

**Two ways to remove an auto-scenario:**

1. **Delete the source.** When you remove a source from the Data sources
   modal, its `SC-AUTO-<id>` scenario is removed at the same time
   (`_on_source_remove` hook in
   [`backend/datasources/registry.py`](../backend/datasources/registry.py)).
   This is the usual path: keep source and chip in lockstep.

2. **Delete just the chip via the edit modal.** Click the pencil on the
   chip → **Remove this scenario** at the bottom of the modal. The source
   stays registered (still queryable via the playground), but the chip
   disappears from the operator console. Use this when you want the source
   for ad-hoc queries but don't want operators to invoke it through the
   agent runtime.

### Custom scenarios — `SC-CUSTOM-<slug>`

Created via the **Save as scenario** form in the Query playground (or the
`POST /api/scenarios` endpoint directly). They're autonomous, run a saved
SQL query against a registered source, and persist in `backend/scenarios/`
as YAML.

**Removed via the edit modal**: pencil → **Remove this scenario**. Or via
the API: `DELETE /api/scenarios/SC-CUSTOM-<slug>`. The YAML file is
deleted; the operator-console chip disappears.

### Quick reference

| Action | Built-in | Auto | Custom |
|---|---|---|---|
| Edit title / keywords / clarifier in UI | ✅ | ✅ | ✅ |
| Edit structural fields in UI | ❌ (edit YAML) | ❌ | ❌ |
| Remove via Edit modal | ❌ | ✅ | ✅ |
| Remove via API DELETE | ❌ (`400`) | ✅ | ✅ |
| Removed automatically with its source | n/a | ✅ | ❌ |

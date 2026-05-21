# TCS Knowledge Fabric — system overview

A short, non-technical walkthrough of what the system is, who uses it,
and how a request flows from "operator types something" to "action
executed and audited." Pairs with [architecture.md](architecture.md)
(the engineering view) and the in-app **Scenarios guide** for the
authoring patterns.

---

## What this is, in one paragraph

A **Human-in-the-Loop (HITL) agent runtime** for enterprise workflows.
Operators ask the agent to do work in plain English. The agent
classifies the request, gathers the right data from connected systems,
and either executes autonomously (read-only lookups, parameter changes
within a pre-approved envelope) or pauses for a named human reviewer
(anything irreversible — sanctions overrides, vendor onboarding,
regulatory actions). Every step is recorded in an append-only audit
trail.

## Why it exists

Off-the-shelf agent platforms have one of two failure modes:

1. **Too autonomous** — they execute, but you can't see what knowledge
   informed each decision, and you can't insert a human approval
   step where you need one.
2. **Too rigid** — they stop at "auto-suggest the next form to fill in"
   and don't actually take action.

This system aims for the middle: the agent does real work, with
real provenance, and with HITL review wired into the spine of every
risky action.

## Three audiences and what each gets

| Audience | What they touch | What they get |
|---|---|---|
| **Operator** | Chat composer + a row of suggested-prompt chips | A natural-language way to kick off pre-approved workflows + ad-hoc data queries against any registered source. No SQL or ontology authoring required. |
| **Reviewer** | A Teams Adaptive Card (or in-app card) per pending decision | Approve / Reject / Need more info, with the full context (active policy, actor scope, master data, prior similar cases, SOPs) bound into the card automatically. |
| **Engineer / scenario author** | YAML files + a Knowledge admin tile | Add a new connected system and the agent can use it across every existing scenario without rewriting any of them. Author one ontology, get many scenarios for free. |

---

## The mental model

Three nouns + three verbs.

### Nouns (what the system knows about)

1. **Data sources** — connections to things that hold data. CSVs, SQLite, Postgres, HTTP APIs, vector stores, Neo4j graphs.
2. **Ontology** — a business-language description of the entities the operator cares about (Supplier, Product, PurchaseOrder, etc.) and how each entity maps to columns in the data sources. Authored once; reused everywhere. Includes which columns hold which attributes.
3. **Scenarios** — recipes the agent follows. Each one is a pattern: *"the operator typed something like X → here's what the agent should fetch, what it should propose, who reviews it, and what happens on approve."*

### Verbs (what happens to a request)

1. **Classify** — the agent's LLM picks the scenario that best matches the operator's prompt.
2. **Bind** — the framework gathers the knowledge each stage of the scenario needs (the active policy, the actor's scope, the master-data record, prior decisions, etc.) into a typed envelope. Every fact carries provenance.
3. **Decide** — either auto-execute (low-risk, deterministic) or pause for a named human reviewer.

That's it. Everything else is implementation.

---

## A walk-through: one operator request

> *"Override the SC-TC-001 sanctions block on order ORD-44216 — customer says they have an OFAC license."*

**Step 1 — Operator types it.** The chat composer sends the prompt to
the backend.

**Step 2 — The agent classifies.** The LLM looks at the catalog of
scenarios, picks `SC-TC-007 Trade override — sanctioned counterparty`,
and rephrases it as *"override the SC-TC-001 sanctions block on order
ORD-44216."* The operator sees the rephrasing as a clarifier and
clicks Confirm.

**Step 3 — The framework binds knowledge.** Two stages run in sequence:
- *Agent intake* — pulls the active TC-override policy from the policy
  graph, plus the agent's IAM scopes (so the audit trail shows what
  the agent was actually permitted to do).
- *Proposal* — pulls the product master record (encryption module
  P-EL-9001, ECCN 5A002), the OFAC sanctions hit on the counterparty
  (Sanctioned Pharma Holdings), and the contract value.

**Step 4 — Policy decides.** Sanctions overrides require named
compliance officer approval, so the case enters the **review** stage
and a Teams Adaptive Card is rendered with all the bound facts plus:
the prior similar overrides this scenario has seen, three relevant SOP
excerpts retrieved by semantic search, and the reviewer's three
buttons (Approve / Reject / Need more info).

**Step 5 — Reviewer decides.** The named compliance officer reads the
card. If they approve, the agent proceeds with the override and the
case completes. If they reject or ask for more info, the case captures
the rationale.

**Step 6 — Audit trail.** Every fact bound, every query issued, every
decision: appended to an immutable log keyed by case id. Replayable
later for compliance review.

The whole loop happens in ~10 seconds for autonomous cases, or pauses
indefinitely at the review step for HITL cases. The reviewer's
decision arrives through a webhook (or the in-app surface today) and
the orchestrator picks the case back up where it left off.

---

## What's been built (functionality)

### Operator-facing

- **Suggested-prompt chips** sorted newest-first so freshly added recipes surface to the top.
- **Deterministic classification** — the LLM only picks from the closed set of authored scenarios (built-in + persisted `SC-ONTO-*` lookup chips). If nothing matches, the case is refused with a clear message rather than guessed at.
- **Live envelope view** — the operator can watch each stage's bound facts populate as the agent works.
- **History panel** — past conversations, search, replay with a forced reviewer decision (so authors can compare "what would have happened if approved instead of rejected").

### Knowledge admin (the "Knowledge" tile)

- **Data sources tab** — register a CSV, SQLite, Postgres, HTTP API, vector store, or Neo4j graph. Test the connection. Run ad-hoc SQL or Cypher in a playground.
- **Ontologies tab** — upload a YAML/JSON ontology defining business entities. Click "Suggest mappings" to have the LLM propose how each business attribute maps to columns in registered sources, then review and confirm. Per-class "Generate lookup chip" button creates an autonomous chip on the operator console.
- **Actions tab** — view registered write actions, preview what the LLM would extract from a natural-language prompt, remove non-default ones.

### Audit + observability

- **Append-only lineage** per case: every fact fetched, every query issued, every decision. Survives restart.
- **Per-fact provenance** in the reviewer card: each fact shows both *what was asked* (the ontology class) and *which source answered* (the physical data source).
- **Live metrics dashboard** — totals, decisions-by-scenario, top rejection reasons, cases-per-day sparkline.
- **CSV export** of cases + lineage with date-range filters.

### Safety

- **HITL by default for write actions.** The natural-language write path always sends the proposed action to a human reviewer; the executor only runs after approve.
- **Read-only Cypher guard** on every Neo4j query path. Writes via Cypher are rejected at the application layer; the action registry is the only path for graph mutations.
- **Default-flagged knowledge artefacts** (built-in ontologies, seeded actions) refuse delete via the API.
- **JWT auth + bcrypt passwords + token blocklist on logout.** Per-user case isolation; admin role bypasses scoping.
- **Rate limiting** on login + register (10/min/IP) + app-wide 120/min default.

---

## Why it's different from a generic agent platform

| Generic agent platform | This system |
|---|---|
| LLM picks a function, calls it, returns. | LLM picks a scenario; the *framework* binds the right knowledge at each stage and routes through HITL when policy says to. |
| Audit trail is a chat transcript. | Audit trail is a typed envelope: every fact has provenance, every decision has rationale, every step is replayable. |
| Adding a new data source means re-prompting the LLM with new tool definitions. | Adding a new data source means registering a connection and clicking "Suggest mappings." Existing scenarios pick it up via the ontology layer without changes. |
| Human review is a chat message you can ignore. | Human review is a structured Teams Adaptive Card with three buttons; the case literally pauses until a named reviewer decides. |
| Write actions go through the LLM. | Write actions are operator-authored YAML with typed argument schemas and named executors. The LLM only fills the arguments; the executor is hand-written. |

---

## Quality gates today

- **214 automated tests passing** (124 backend + 90 framework).
- **Frontend type-check clean** + **production bundle builds**.
- **Live demo verified** through every chip + the Neo4j graph + the ontology Query playground.

---

## What's recommended next

### Implementable in 2 weeks (pilot prep + obvious feature gaps)

1. **Pick one real customer data source** (e.g. their Postgres governance store) and run the full flow: register → AI-map → review with a domain expert → confirm → click "Generate lookup chip" → demo. Proves the value prop on real data.
2. **Tighten the production deployment** per [docs/production.md](production.md) — generate JWT secret, rotate the seeded admin password, set up HTTPS, configure backups.
3. **Decide the mapping governance model** — who can confirm a mapping? Mappings are effectively access-control documents; treat the confirm step like an ACL change.
4. **RDF/Turtle ontology import** (~2 days). For teams that already maintain ontologies in industry-standard formats. The mapping/resolver layer needs no changes; just an importer.
5. **Bulk "generate all chips"** in the Mappings tab — today operators click per class. Quality-of-life improvement.
6. **Cypher action executor** (~2 days). The action registry has SQL + HTTP today. Adding a Cypher write executor lets operators kick off graph mutations through the same HITL path.

### Production readiness (one quarter)

7. **Move from in-memory to durable transport.** Single worker with in-memory queues today; production scale needs Redis (case store) and Kafka/SQS (review-decision queue). The framework was designed for this swap; ~2 weeks.
8. **Observability** — structured JSON logging, Prometheus metrics, audit-log retention policy. ~1 week.
9. **Cross-source entity resolution.** Currently if Supplier S-001 lives in two sources, both records show up separately. Adding ER rules would dedupe with confidence scores. Defer until a customer asks; ~2 weeks of real engineering work.

The architecture is intentionally built so each of these is additive,
not a rewrite — the resolver layer, the binder protocols, and the
mapping/ontology contracts are all "swap-points" the framework was
designed around.

---

## Pointers for going deeper

| If you want to… | Read |
|---|---|
| Walk through how a request flows through the code | [architecture.md](architecture.md) (the engineering view) |
| Understand how the schema/mapping layer works | [ontology.md](ontology.md) |
| Learn the scenario YAML format and the three coexistence patterns | [scenarios.md](scenarios.md) |
| Decide which scaling step to ship next | [scaling.md](scaling.md) |
| Deploy this somewhere | [production.md](production.md) |

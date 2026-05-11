# Ontology-driven knowledge layer

> **Status:** design — not yet implemented. This doc is the contract that the
> implementation will be built against. YAML/JSON examples below are
> normative; if implementation drifts from them, update this doc *and* the
> Pydantic models in [backend/ontology/models.py](../backend/ontology/models.py)
> in the same change.

## Why this exists

The HITL framework's `KnowledgeFact` carries `ref.ontology_type` and
every scenario stage now binds data via an `ontology_queries:` block,
but until 3.C there was no central document that said *"a Supplier has
these attributes, lives in these sources, relates to PurchaseOrder via
X."* Source specs and scenarios each carried their own snippets of
class metadata, leading to duplicate vocabularies.

After 3.C the ontology is the **authoritative schema layer**. Data
sources are connections without schema metadata; the mapping doc is the
only place that says "source X backs class Y"; scenarios reference
ontology classes, not source ids.

The consequences:

- **Scenario authors hand-write `data_source` + `filter` for every query.**
  When the underlying source layout changes, every scenario that touches it
  needs an edit.
- **Agents can't reason across sources.** A scenario that wants
  "Supplier from CSV in dev, from Postgres in prod" is two scenarios.
- **No NL→data path.** Operators can ask the agent ("override SC-TC-001"),
  but they cannot ask the *data* ("show me suppliers in NL with low
  reliability") without writing SQL.

The ontology layer fixes all three by introducing a single authoritative
schema document plus a separate mapping document that translates ontology
classes into source-specific queries. Scenarios stay the spine — agents
still pick a scenario, the orchestrator still drives four stages, the
reviewer still sees a Teams card. What changes is that scenarios can now
say *"give me a Supplier by id"* without naming the source, and an
operator can pose ad-hoc questions to the ontology directly.

## Phasing

The ontology layer ships in five small, separately-reviewable phases. Each
is a single PR; no phase blocks on a later one beyond the seams listed.

| Phase | What lands | Dev surface | Out of scope until later |
|---|---|---|---|
| **1 — Backend MVP** | `Ontology` Pydantic models, `OntologyRegistry` (load/save), `OntologyResolver`, `ontology_queries:` block in `_facts_from_stage()`, REST: upload (YAML+JSON) / list / get / delete / get-classes / get-mappings / put-mappings (hand-edited body), tests. | curl + a hand-authored mapping YAML drop-in is enough to drive a real case end-to-end. | UI, LLM mapping suggestions, NL playground, Neo4j, auto-scenarios. |
| **2 — Mapping UX** | LLM-driven `suggest_mappings()`, frontend Ontologies tab, mapping confirm panel, schema-introspection helpers on existing resolvers. | Operator can upload an ontology, click "Suggest mappings," edit, confirm — entirely in the UI. | NL playground, Neo4j, auto-scenarios. |
| **3 — NL playground** | NL→`OntologyQuery` parser, `POST /api/ontology-query`, frontend ontology playground tab beside the SQL one. | Ad-hoc "show me suppliers in NL with reliability < 0.5" works. | Neo4j, auto-scenarios. |
| **4 — Neo4j connector** | `Neo4jResolver` (registered as a `kind: neo4j` data source, not bound to the ontology layer specifically), `assert_read_only` Cypher guard, Cypher playground, optional `docker-compose` block. | Graph queries usable both as a regular data source and as a target for ontology mappings. | Auto-scenarios. |
| **5 — Auto-scenarios per class (optional)** | "Generate lookup scenarios" button in the mappings panel — operator opts in per class. | One chip per chosen class. | n/a |

The seams between phases are stable: Phase 2's mapper writes the same
file shape Phase 1's API already accepts; Phase 3's NL parser produces
the same `OntologyQuery` shape Phase 1's resolver consumes; Phase 4's
`Neo4jResolver` plugs into the existing `DataSourceRegistry` like any
other connector.

Phase 1 is the smallest unit that delivers value end-to-end and is the
*only* phase that needs to land for the ontology layer to be considered
"shipped" — every later phase adds ergonomics, not capability.

## Architecture

```
                     ┌──────────────────────┐
   NL query ─────────▶  Ontology NL parser   │ (LLM)
                     └──────────┬───────────┘
                                │ OntologyQuery {class, filter, relations}
                                ▼
   Scenario ontology_queries ──▶┌──────────────────────┐
                                │  OntologyResolver    │
                                └──┬───────────────────┘
                                   │  uses Mapping doc
                                   │  to dispatch
                ┌─────────┬────────┼────────┬─────────────┐
                ▼         ▼        ▼        ▼             ▼
            CsvResolver  Sqlite  Postgres  Vector  Neo4jResolver
                                   │
                                   ▼
                           list[KnowledgeFact]
```

The `OntologyResolver` is itself a `KnowledgeResolver` — same Protocol the
framework already declares, same one CSV / SQLite / Postgres / HTTP /
vector / Neo4j all implement. Scenarios route to it through the existing
`DataSourceRegistry` under the reserved id `__ontology__`.

## Two documents per ontology

The ontology and its source mappings are kept in **separate files** so
that mapping suggestions can be regenerated as data sources come and go
without touching the ontology itself.

### Ontology document

Lives at `backend/ontologies/<id>.yaml`. Authored by hand or generated by
upstream tooling. Defines classes, attributes, and relations.

```yaml
id: supply_chain_v1
title: Supply Chain Ontology
namespace: sc
classes:
  Supplier:
    description: Vendor or producer of goods
    attributes:
      - { name: supplier_id, type: string, identifier: true }
      - { name: name, type: string, required: true }
      - { name: country, type: string }
      - { name: reliability_score, type: decimal }
    relations:
      - { name: places, target: PurchaseOrder, cardinality: "0..*", inverse: placed_with }
  PurchaseOrder:
    description: A confirmed order placed with a supplier
    attributes:
      - { name: po_id, type: string, identifier: true }
      - { name: supplier_id, type: string, required: true }
      - { name: total_value, type: decimal }
      - { name: placed_on, type: date }
    relations:
      - { name: contains, target: Product, cardinality: "1..*" }
  Product: { ... }
  Shipment: { ... }
```

#### Upload formats

Both `.yaml`/`.yml` *and* `.json` are accepted on upload. The endpoint
sniffs the content type and the leading character (`{` → JSON, otherwise
YAML); both are parsed into the same `Ontology` Pydantic model and
written to disk in YAML so the file remains hand-editable.
`GET /api/ontologies/{id}?format=json` returns the same shape as JSON for
tooling that prefers it.

#### Field reference

| Field | Required? | Notes |
|---|---|---|
| `id` | yes | Slug; used in URLs and on disk. |
| `title` | yes | Human label. |
| `namespace` | optional | Short prefix used to build `KnowledgeRef.uri` values for facts (`sc:Supplier:S-001` → `kf://sc/Supplier/S-001`). |
| `classes` | yes | Map keyed by class name. |
| `classes.<C>.description` | optional | One-line description, used as LLM context. |
| `classes.<C>.attributes` | yes | List of `{name, type, identifier?, required?, description?}`. Exactly one attribute per class should have `identifier: true`. |
| `classes.<C>.relations` | optional | List of `{name, target, cardinality, inverse?}`. `target` is another class id in the same ontology. |

`type` is one of `string`, `integer`, `decimal`, `boolean`, `date`,
`datetime`. Unknown types are stored as opaque strings.

### Mapping document

Lives at `backend/ontologies/<id>.mappings.yaml`. Authored by the LLM
mapper, edited by an operator, persisted by the API. Tells
`OntologyResolver` *where* each class lives and *how* attributes line up
with columns.

```yaml
ontology_id: supply_chain_v1
mappings:
  Supplier:
    sources:
      - data_source: suppliers_csv      # references DataSourceRegistry by id
        identifier_column: supplier_id
        attribute_map:
          supplier_id: supplier_id
          name: name
          country: country_iso
          reliability_score: reliability   # column name differs from attribute
        confidence: 0.95
        suggested_by: llm
        confirmed_by: admin
        confirmed_at: 2026-05-09T14:22:00Z
      - data_source: governance_postgres
        identifier_column: vendor_id
        attribute_map:
          supplier_id: vendor_id
          name: legal_name
          country: country_code
          reliability_score: trust_score
        confidence: 0.78
        suggested_by: llm
    relations:
      places:
        target: PurchaseOrder
        join:
          via_source: orders_postgres
          local_attribute: supplier_id
          remote_attribute: supplier_id
```

Multiple sources per class are allowed — master data in CSV, transactional
in Postgres, graph in Neo4j. The resolver fans out, calls each underlying
resolver, and merges results into a single `list[KnowledgeFact]` with
per-fact `KnowledgeRef.source` so the reviewer (or the playground UI)
can see which source answered which row.

## How scenarios use the ontology

> **Phase 3.C update.** The legacy `queries:` block has been
> hard-removed from the scenario schema; loading a YAML that still uses
> it raises `ScenarioSchemaError` at startup. Migrate via the recipe in
> the error message, or follow the example below. Two stage-knowledge
> blocks remain:

| Block | Binds | When you'd use it |
|---|---|---|
| `facts:` | inline literal `KnowledgeFact` rows | Mock/fixture data, demo seeds, deterministic always-true facts (policies, actor scope) |
| `ontology_queries:` | live data via an ontology class + attribute filter, dispatched through the mapping doc | Anything that fetches from a registered data source |

### Pattern A — facts-only (no live data)

The classic shape — a scenario whose stages bind only inline facts. Use
this for fully-mocked demos or scenarios where every stage's evidence is
a stable, seeded value:

```yaml
stages:
  agent_intake:
    binder: PolicyAndScopeAgentBinder/1.0
    facts:
      - source: "kf:graph"
        ontology_type: Policy
        id: POL-TC-OVERRIDE-2026-Q2
        title: "TC override policy"
        payload: "Critical TC overrides require named compliance officer."
```

### Pattern B — hybrid (facts + ontology queries)

A scenario keeps its inline `facts:` for stable seeded data and adds an
`ontology_queries:` entry to fan out across whichever sources the
mapping says hold `Supplier`:

```yaml
stages:
  proposal:
    binder: TradeOverrideProposalBinder/1.0
    facts:
      - source: "contract_mgmt"
        ontology_type: Contract
        id: K-2026-0182
        title: "Customer contract"
        payload: "DDP terms · $480k value · effective Q2 2026"
    ontology_queries:
      - ontology: supply_chain_v1
        class: Supplier
        where: { supplier_id: ":supplier_id" }
        include_relations: [places]
```

Both blocks return `KnowledgeFact[]`; the binder concatenates them into
one `StageContext.facts` list with one `KnowledgeQuery` recorded per
`ontology_queries:` entry — lineage shows the *intent* (ontology class)
plus the *underlying* source(s) hit (via per-fact `via_source_binding`).

### Pattern C — ontology-first (portable scenarios)

A scenario authored against the ontology never names a data source by
id. The same scenario works against CSV in dev, Postgres in stage,
Neo4j in prod, as long as the mapping doc covers the classes used.
This is what makes the ontology useful for *agents* — they can reason
in terms of "Supplier", "Product", "Shipment" without binding their
logic to physical schemas:

```yaml
stages:
  agent_intake:
    binder: OntologyAgentBinder/1.0
    ontology_queries:
      - ontology: supply_chain_v1
        class: Supplier
        where: { supplier_id: ":supplier_id" }
  proposal:
    binder: OntologyProposalBinder/1.0
    ontology_queries:
      - ontology: supply_chain_v1
        class: Supplier
        where: { supplier_id: ":supplier_id" }
        include_relations: [places]
      - ontology: supply_chain_v1
        class: Product
        where: { product_id: ":product_id" }
```

### Parameter binding

`where: { supplier_id: ":supplier_id" }` — the leading colon means
"pull this from `action.payload`," exactly the convention `queries.filter`
already uses today. No new templating language, no parser changes for
authors.

### Auto-scenarios per ontology class *(opt-in, Phase 5)*

Today, registering a data source generates one autonomous lookup chip
per source via [backend/auto_scenario.py](../backend/auto_scenario.py).
The ontology layer can mirror this — but on demand, not automatically.

Mapping confirmation does **not** generate scenarios. Generating one
chip per class (`SC-ONTO-supply_chain_v1-Supplier`,
`SC-ONTO-supply_chain_v1-PurchaseOrder`, …) for every uploaded
ontology would swamp the operator console — exactly the
scenario-explosion problem [docs/scaling.md](scaling.md) warns against.

Instead the mappings panel exposes a per-class **"Generate lookup
scenario"** button. The operator picks the classes worth surfacing as
autonomous lookup chips (typically the entry-point entities, not
every transitive relation). The generated scenarios are regular
`SC-ONTO-…` YAMLs in `backend/scenarios/`, removable through the
existing edit-modal "Remove this scenario" path. Removing the ontology
or the underlying mapping does *not* delete generated scenarios — the
operator decides their lifetime, mirroring how custom playground
scenarios behave today.

### Reviewer evidence stays the same shape

The Teams card and the in-app review panel render `StageContext.facts`.
Whether a fact came from `facts:`, `queries:`, or `ontology_queries:`
is invisible to the reviewer except via the per-fact `KnowledgeRef.source`
("csv:suppliers_csv", "neo4j:graph", etc.) — and a new optional
`payload.via_ontology` field of the form `"supply_chain_v1.Supplier"` so
the reviewer can see *both* what was asked (the ontology class) and
where the answer came from (the physical source).

## OntologyResolver semantics

```python
class OntologyResolver(KnowledgeResolver):
    name = "ontology"

    def __init__(self, ontologies: OntologyRegistry, sources: DataSourceRegistry):
        self._ontologies = ontologies
        self._sources = sources

    def resolve(self, query: KnowledgeQuery) -> list[KnowledgeFact]:
        # query.ontology_type is treated as an ontology class name.
        # 1. Look up the class in the loaded ontology.
        # 2. Read its ClassMapping from the mapping doc.
        # 3. For each source binding in the mapping:
        #    a. Translate ontology filter → source-native filter via attribute_map.
        #    b. Call the underlying resolver via DataSourceRegistry.
        #    c. Tag returned facts with payload.via_ontology = "<id>.<class>".
        # 4. Concatenate facts from all bindings (no cross-source dedupe — see below).
        # 5. Return.
```

`OntologyResolver` is constructed once in
[backend/state.py](../backend/state.py) and **passed directly to the
binders** as a constructor argument — it is *not* registered in
`DataSourceRegistry` under a magic id. `_facts_from_stage()` calls it
explicitly when a stage has an `ontology_queries:` block.

**Failure modes** — explicit, not silent:

- No mapping for the class → `OntologyResolveError("class X has no mapping")`.
- Mapping references an unregistered source → log a warning, skip that
  binding, continue with the rest. Empty results are returned only if
  *every* binding fails.
- Filter references an attribute that no source maps → log a warning,
  drop the filter for that source, continue.

**Relations** — `include_relations: [places]` follows the relation
defined in the ontology, looks up the target class's mapping, and binds
related facts. Related facts get their own `KnowledgeRef` with the same
`payload.via_ontology` pattern (`supply_chain_v1.PurchaseOrder`) and a
`payload.related_via = "Supplier.places"` annotation so the reviewer can
see how they got pulled in.

### Entity resolution across sources

When `Supplier` is mapped to two sources (CSV master + Postgres
governance), both sources will return facts for the same logical
entity. **The MVP does not attempt cross-source deduplication.** Every
source binding produces its own facts; all are concatenated into the
returned list with `KnowledgeRef.source` distinguishing them. The
reviewer (and the playground UI) sees one row per source, e.g.:

```
Supplier S-001  via supply_chain_v1.Supplier  source: csv:suppliers_csv
Supplier S-001  via supply_chain_v1.Supplier  source: postgres:governance_postgres
```

This is honest — same entity, two snapshots, possibly different values
— and avoids guessing at identity matching with no domain rules. Two
later evolutions are possible without breaking the mapping schema:

- **Primary source per class.** Add an optional `primary: true` flag on
  one source binding; the resolver could prefer that source's snapshot
  and link the others via foreign id. ~30 lines.
- **Per-class ER rules.** Add an `entity_resolution:` block to the
  mapping with confidence-scored match rules (mirrors the external
  KG repo's `manifest.yaml` ER section). Real engineering work — defer
  until a customer asks.

For Phase 1, the docs and the UI will say "rows from each source are
shown separately" so the behaviour isn't surprising.

## NL query playground

Operators get a new playground tab beside the existing SQL playground:

- **Input:** `"show me suppliers in NL with reliability < 0.5"` plus a
  picker for which ontology to query against.
- **What happens:**
  1. `parse_nl_query(prompt, ontology)` — LLM call, returns structured
     `OntologyQuery(class="Supplier", filter={country: "NL", reliability_score: {"<": 0.5}})`.
  2. `OntologyResolver.resolve(query)` — same path scenarios use.
  3. Frontend renders a results table grouped by source with the same
     "test" UX the existing data-source playground already has.

The structured form is also exposed for power users who don't want NL:
`POST /api/ontology-query/structured {ontology_id, class, filter, include_relations}`.

## Neo4j as a real datasource kind *(shipped)*

Stood up alongside SQLite / Postgres via the `kind: neo4j` branch in
[backend/datasources/registry.py](../backend/datasources/registry.py).
Source spec carries only the connection details (`uri`, `user`,
`password`, optional `database`); the Cypher template lives in the
mapping doc's `SourceBinding.query_template`. Without a template, the
resolver auto-derives `MATCH (n:<Label>) WHERE n.<id> = $id RETURN n`
from the binding's `identifier_column` and the requested ontology class.

**Read-only by default.** Every Cypher path — the resolver, the Cypher
playground, any LLM-generated query — goes through `assert_read_only`
in [backend/ontology/cypher_safety.py](../backend/ontology/cypher_safety.py).
Write clauses (`CREATE`/`MERGE`/`DELETE`/`SET`/`REMOVE`/`DROP`/`FOREACH`/
`LOAD CSV`) and dangerous procedure namespaces (`apoc.create.*`,
`apoc.refactor.*`, `apoc.periodic.*`, `n10s.rdf.import.*`,
`gds.graph.project`, `db.create*`) are rejected before reaching the
driver.

**Local Neo4j for demos.** [docker-compose.yaml](../docker-compose.yaml)
ships a commented `neo4j` service block with the APOC + n10s plugins
preloaded. Uncomment and bring it up with
`docker compose --profile graph up -d` (set `NEO4J_PASSWORD` in your
`.env.docker` first). The `Cypher` button on a registered Neo4j source
in the **Knowledge → Data sources** tab opens the same playground UI as
the SQL playground.
A spec looks like:

```yaml
- id: graph_local
  kind: neo4j
  uri: bolt://localhost:7687
  user: neo4j
  password: <env-or-secret>
  database: supply_chain    # optional; uses default DB if omitted
  queries:
    Supplier: |
      MATCH (s:Supplier {supplier_id: $supplier_id})
      RETURN s.supplier_id AS id, s.name AS title,
             s.country AS country, s.reliability_score AS reliability_score
      LIMIT $max_results
```

The `Neo4jResolver` implements the same `KnowledgeResolver` Protocol
everything else does. A new `POST /api/data-sources/{id}/run-cypher`
endpoint backs a Cypher playground tab. **All Cypher paths go through
`assert_read_only`** lifted from
[the external KnowledgeGraph repo's `pipeline/cypher_safety.py`](https://github.com/AbiCharles/KnowledgeGraph)
— write operations (`CREATE`, `DELETE`, `SET`, `MERGE`, `REMOVE`,
`DROP`, `CALL apoc.*write*`, …) are rejected before they hit the driver.

## What's reused, what's lifted, what's left

### Reused as-is from the framework

- **`KnowledgeResolver` Protocol** — `OntologyResolver` implements it; nothing in [hitl-context/](../hitl-context/) changes.
- **`KnowledgeFact` / `KnowledgeRef` / `KnowledgeQuery`** — `payload` is `dict[str, Any]`, room for ontology-shaped attribute bundles. `ref.ontology_type` is already the routing key. No model changes needed.
- **`_facts_from_stage()`** in [backend/binders.py](../backend/binders.py) — single helper feeds all three binders. One block to extend, not three.
- **`make_auto_scenario()`** in [backend/auto_scenario.py](../backend/auto_scenario.py) — same lifecycle-hook pattern, inverted: ontology class → autonomous scenario chip per class.
- **`LLMClient`** in [hitl-context/src/tcs_hitl_context/llm.py](../hitl-context/src/tcs_hitl_context/llm.py) — already wired in [backend/state.py](../backend/state.py). Mapper and NL parser take the same handle.

### Lifted from the external KnowledgeGraph repo

- `pipeline/cypher_safety.py` → [backend/ontology/cypher_safety.py](../backend/ontology/cypher_safety.py) verbatim — the read-only Cypher guard.
- The retry decorator + connection wrapper pattern from `db.py` → adapted into [backend/datasources/neo4j_source.py](../backend/datasources/neo4j_source.py).
- The "bundle = manifest + ontology + data" structure → inspires the split between `<id>.yaml` (ontology) and `<id>.mappings.yaml` (mappings); not lifted as code.

### Out of scope for this iteration

| Cut | Reason | Re-add when |
|---|---|---|
| RDF/Turtle import | YAML/JSON cover authoring needs today | An external team ships an `.owl` and asks us to consume it directly |
| SHACL validation | `pyshacl` is one import away if we ever import RDF | RDF import lands |
| Per-bundle Neo4j databases | Single-DB mode covers the demo; multi-DB needs Enterprise edition | The first multi-tenant deployment |
| LangGraph agent factory | Existing scenario + `agent_runtime.py` already covers HITL action drafting | Composition pressure forces it (see [scaling.md](scaling.md)) |
| Multi-reviewer / quorum on ontology-bound actions | Inherits the framework's single-reviewer assumption | Framework adds it |

## Authoring tutorial — first ontology, end to end

1. **Write your ontology.** Save as `supply_chain_v1.yaml` (or `.json`):

   ```yaml
   id: supply_chain_v1
   title: Supply Chain Ontology
   classes:
     Supplier:
       attributes:
         - { name: supplier_id, type: string, identifier: true }
         - { name: name, type: string }
         - { name: country, type: string }
         - { name: reliability_score, type: decimal }
   ```

2. **Upload it.** UI: Ontologies tab → Upload. API:

   ```bash
   curl -X POST http://localhost:8001/api/ontologies \
     -H "Authorization: Bearer $TOKEN" \
     -F "file=@supply_chain_v1.yaml"
   ```

3. **Write the mapping.** *Phase 1: by hand.* Drop
   `supply_chain_v1.mappings.yaml` into `backend/ontologies/`:

   ```yaml
   ontology_id: supply_chain_v1
   mappings:
     Supplier:
       sources:
         - data_source: suppliers_csv
           identifier_column: supplier_id
           attribute_map:
             supplier_id: supplier_id
             name: name
             country: country_iso
             reliability_score: reliability
   ```

   Or post the same body to `PUT /api/ontologies/supply_chain_v1/mappings`.

   *Phase 2 onward: from the UI.* The Ontologies tab will introspect
   each registered source's schema, ask the LLM to propose
   column→attribute mappings, render them with confidence badges, and
   let you edit and confirm in the browser:

   ```bash
   curl -X POST http://localhost:8001/api/ontologies/supply_chain_v1/mappings/suggest \
     -H "Authorization: Bearer $TOKEN" \
     -H "content-type: application/json" \
     -d '{"data_source_ids": ["suppliers_csv", "governance_postgres"]}'
   ```

4. **Try it from the playground.** *Phase 3.* New "Ontology query" tab:

   ```
   show me suppliers in NL with reliability below 0.5
   ```

   Results render as a grouped table with per-source provenance. *In
   Phase 1 you can still test the resolver via* `POST /api/ontology-query/structured`
   *with a hand-built `OntologyQuery` payload.*

5. **Author your first ontology-aware scenario.** *Phase 1.* Drop a YAML into
   `backend/scenarios/`:

   ```yaml
   id: SC-PP-SUPPLIER-LOOKUP
   title: "Supplier lookup"
   domain: "Procurement"
   autonomous: true
   actor_id: "agent-procurement-01"
   operator_role: { label: "Operator", name: "buyer.amartin" }
   action_type: "supplier_lookup"
   action_payload: { supplier_id: ":supplier_id" }
   match_keywords: ["supplier", "vendor", "lookup"]
   interpreted_as: "look up a supplier by id"
   clarifying_question: "Look up <code>:supplier_id</code> across all registered sources?"
   auto_approval_guardrail: "GR-AUTO-LOOKUP"
   auto_approval_reason: "Read-only ontology query."
   closing_message: "Done — supplier <code>:supplier_id</code> bound from {{sources}}."
   stages:
     agent_intake:
       binder: "OntologyAgentBinder/1.0"
     proposal:
       binder: "OntologyProposalBinder/1.0"
       ontology_queries:
         - ontology: supply_chain_v1
           class: Supplier
           where: { supplier_id: ":supplier_id" }
   outcomes:
     auto_execute: { headline: "Done", detail: "Supplier bound." }
   ```

6. **Restart uvicorn.** The new chip appears in the operator console.
   Type "look up supplier S-001"; the classifier picks the new
   scenario; the proposal binder fans out to every source the mapping
   covers; the autonomous outcome closes the case.

If your team adds a new data source for suppliers later, you only need
to extend the mapping — the scenario continues to work.

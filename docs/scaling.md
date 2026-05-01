# Scaling the HITL Context Framework

This document covers three architectural questions that come up once the basic
HITL flow is working:

1. **No-match UX** — what happens when the operator's prompt doesn't match a scenario?
2. **Auto-generated scenarios** — should adding a data source automatically generate scenarios?
3. **Scenario explosion** — how do we keep the system manageable as the catalog grows?

Each section explains the failure mode, the menu of options with trade-offs,
and a recommendation for *when* to ship each one. Skip ahead to
[the staged roadmap](#staged-roadmap) for the TL;DR.

---

## 1. No-match queries

### Failure mode today

[backend/agent_runtime.py](../backend/agent_runtime.py) returns
`scenario_id=None` when the LLM (or keyword fallback) can't classify a prompt.
The case is marked `phase="cancelled"` and the chat shows a generic
"I'm not sure I can act on that yet." Real operators will hit this often,
because (a) prompts come in with varied phrasing, and (b) the operator may
be asking for something genuinely novel.

### Options

| Approach | How it works | Falls down when… |
|---|---|---|
| **(a) Top-K suggestions** | Return the 3 highest-confidence scenarios as buttons in the chat. Operator picks or refines the prompt. | Truly novel requests still dead-end. |
| **(b) Clarifying dialog** | When confidence is low, the LLM asks a follow-up question rather than failing. | Adds 1–2 LLM round-trips per ambiguous case. |
| **(c) General-purpose fallback** | No-match → drop into a generic agent mode that picks data sources from the registry, drafts an action freeform, and forces HITL by default. | Trades safety for flexibility — reviewers see less-structured envelopes. Hardest to govern. |

### Recommendation

Ship **(a)** first. Small change, biggest UX win, doesn't sacrifice safety.
**(b)** is worth adding once you've watched enough operator sessions to know
*which* clarifications matter. **(c)** is the right north-star for true
agentic capability, but build it after you've seen what scenarios real
operators actually ask for — premature general-purpose mode is a footgun.

**Status:** (a) is **shipped** in this iteration. See
[backend/agent_runtime.py](../backend/agent_runtime.py) and
[frontend/src/components/Console.tsx](../frontend/src/components/Console.tsx).

---

## 2. Auto-generated scenarios per data source

### The question

Right now scenarios are hand-authored YAML and data sources are reusable
building blocks. Every new source requires someone to write a YAML to
expose it. Could we auto-generate scenarios when a source is added?

Yes — but be careful about *what* you auto-generate.

### Three levels

**Level 1 — Boilerplate lookup scenarios.** For every registered source,
auto-create a "look up X by id" scenario. Adding `products_csv` would
generate `SC-LOOKUP-products_csv` (autonomous, action_type `lookup`) that
just queries the source. Cheap, mechanical, gives every source instant
"show me…" behaviour. ~100 lines of registry hook.

**Level 2 — Schema-inferred CRUD.** Read the CSV columns / SQL schema,
generate filter/list scenarios per column or ontology_type. More powerful,
but the LLM's classification accuracy degrades as the catalog fills with
nearly-identical scenarios. The clarifying questions read like form labels
rather than user intent.

**Level 3 — On-demand LLM-drafted scenarios.** No-match query → LLM
examines the sources catalog, drafts a YAML on the fly, runs it once. The
scenario isn't persisted unless the operator confirms "save this". Most
flexible, but real engineering work: validation, safety checks on the
generated YAML, dedup against existing scenarios, schema constraints on
the action payload.

### Recommendation

**Level 1** is great cheap UX once your first few operators are using the
system. Build it when you add the source-management UI improvements.

**Level 3** is the actually-interesting pattern but probably a quarter of
work to do safely. Don't ship it until you've solved scenario explosion
(below) — otherwise auto-generation just makes the problem worse.

**Status:** not shipped.

---

## 3. Scenario explosion

### Failure modes

Once the catalog grows past ~20 scenarios:

- **Classification accuracy degrades** — the LLM has more candidates to
  pick from, and confusable pairs proliferate.
- **Maintenance burden** — minor product changes touch dozens of scenarios.
- **Operators get lost** — no one knows what scenarios exist, the chip
  row stops being a useful surface.

### Patterns to manage it

**Hierarchical classification.** Two-stage routing: first pick a *domain*
(Trade Compliance, Procurement, Logistics, …) from ~10 candidates, then
pick a specific scenario from the ~10 in that domain. Keeps each LLM prompt
small, accuracy stays high, and the LLM only sees relevant candidates.

**Templates over duplication.** Today SC-TC-007 and SC-TC-008 are nearly
identical — same domain, same roles, same outcomes, just different fact
sources. They could be one template with two variants:

```yaml
extends: trade_compliance_override_template
variants:
  - id: SC-TC-007
    fact_strategy: inline
  - id: SC-TC-008
    fact_strategy: live_sources
```

The scenario loader expands templates at load time. ~100 lines in
`scenario_loader.py`.

**Vector search over the scenario catalog.** Embed each scenario's
`interpreted_as` + `clarifying_question` once, do RAG-style retrieval to
pull top-K candidates for the LLM to classify against. The vector store
already shipped (the `policy_corpus`) does exactly this — extend it to
the scenarios themselves.

**Usage telemetry → archival.** Track which scenarios get triggered.
Anything not used in 90 days gets a "deprecate?" PR opened automatically.
Unglamorous but essential — without it the catalog only grows.

**Action primitives instead of scenarios.** The most ambitious move: stop
scaling scenarios at all. Instead, the agent has a small library of
*action primitives* (lookup, propose, override, escalate) and a registry
of *guardrails* and *data sources*. The LLM composes these on the fly.
Scenarios become emergent — generated documentation of common
compositions — rather than the source of truth. This is the direction
LangGraph / Anthropic's Computer Use / similar agent platforms are
pushing toward.

### Recommendation

Ship in this order, each when you hit the named threshold:

| When | What | Why |
|---|---|---|
| **Now** | Top-K suggestions (§1a) + Level-1 auto-lookup (§2) | Small wins, big UX delta |
| **At ~20 scenarios** | Templates + hierarchical classification | Cuts duplication, keeps classifier fast |
| **At ~50 scenarios** | Vector search retrieval + usage telemetry | Catalog stops being human-scannable |
| **Eventually** | Primitives + composition | Scenarios as cached compositions, not source of truth |

The trap to avoid is jumping straight to "primitives" before you've seen
what scenarios real operators actually use — premature primitives are as
bad as premature scenarios. Each step buys 2–3× headroom and is ~a week
of work.

---

## Staged roadmap

```
┌─────────────────────────────────────────────────────────────────┐
│  Now                                                            │
│  ─────                                                          │
│  ✓ Top-K suggestions when classifier confidence < 0.7           │
│  ◯ Level-1 auto-lookup scenarios per data source                │
│                                                                 │
│  At ~20 scenarios                                               │
│  ─────────────────                                              │
│  ◯ Scenario templates with variants                             │
│  ◯ Hierarchical classification (domain → action → scenario)     │
│                                                                 │
│  At ~50 scenarios                                               │
│  ─────────────────                                              │
│  ◯ Vector-search the scenario catalog                           │
│  ◯ Usage telemetry → archival pipeline                          │
│                                                                 │
│  Eventually                                                     │
│  ───────────                                                    │
│  ◯ Action primitives + composition                              │
│  ◯ On-demand LLM-drafted scenarios (Level 3)                    │
│  ◯ General-purpose no-match fallback                            │
└─────────────────────────────────────────────────────────────────┘
```

Each item is intended to be a small (1 week) shippable iteration.
Don't bundle them; ship one, watch operator behaviour change, decide
the next based on what you see.

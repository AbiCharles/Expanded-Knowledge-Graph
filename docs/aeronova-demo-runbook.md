# Aeronova demo runbook

A click-by-click guide for the FDE delivering the [Harness Demo Deck](Harness_Demo_Deck.pptx)
5-beat Aeronova storyline on the live app.

> This runbook ships with **W7 (seed data) + W2 (hidden-dependency UI
> callout)**. Beats marked ⏳ depend on later workstreams (W1 — case
> revisioning · W3 — compensation visibility · W4 — dynamic authority
> recalculation · W5 — baseline vs harness contrast). Treat ⏳ beats as
> **simulated narrative** until those workstreams land — the storyline
> still resolves, just without the live UI moment.

---

## One-time setup

1. **Re-seed Neo4j** so the Aeronova nodes are present:
   ```bash
   source .venv/bin/activate
   python3 share/tcs_kf_graph_data/seed_neo4j.py
   ```
   Expected node-count summary at the bottom: `Supplier: 22`, `HoldingCompany: 5`,
   `Program: 3`, plus the pre-existing carrier / alliance / PO / product counts.

2. **Restart the backend** so the new `SC-PP-AERONOVA-026` scenario and the
   extended `supply_chain` ontology / mappings are picked up:
   ```bash
   uvicorn backend.main:app --reload
   ```
   Watch the boot log: `scenarios=N · ontologies=M · mappings=M` — counts
   should each bump by one for the new scenario + extended mappings.

3. **Log in** as the demo operator (or the seeded admin) at the launched
   instance URL.

---

## The 5 beats

### Beat 0 · The mirror — _no app interaction_

Narrate slide 2 of the deck. No clicks. Sets up the war-room problem before
introducing any product.

### Beat 1 · The reveal (the hidden tier-2 dependency surfaces) ✅ ships today

**Action:** in the operator console prompt, paste:

```
Northwind Forge just filed Chapter 11 — assess Aeronova supply assurance
```

**Expected:** the agent classifies the case as `SC-PP-AERONOVA-026` and runs
the proposal-stage bindings. The envelope's **proposal** stage will surface:

- `Supplier(SUP-021)` — title: _Northwind Forge & Castings_; summary line
  ends with `· status: chapter_11_filed_2026-06-18`.
- `DownstreamDependent` — **3 rows** for SUP-001 (Hemlock), SUP-003 (Granite),
  SUP-016 (Crimson). Each summary names the chain back to Northwind.
- `ProgramImpact` — **3 rows** for the Aeronova flagships:
  - Mirage Avionics platform · **$48M revenue at risk** · $220k/day OTD penalty
  - Viper UAV sustainment · $11.5M · $85k/day
  - Comet satellite payload · $9M · $60k/day
- `AlternativeSupplier` — **Stillwater Alloys (SUP-022)** ranked top with
  summary `2-hop alternative · sibling via Northgate Industrial Holdings
  (HoldingCompany) · reliability 0.74 · qualification: lapsed (expired 2026-04-15)`.

**What to point at on the screen:** the `DownstreamDependent` rows + the
`ProgramImpact` total. The three programs are reached through ONE hidden
tier-2 node — that's the "3 programs exposed through 1 hidden tier-2
dependency" close-list bullet.

**Hidden-dependency callout (W2):** the `AlternativeSupplier` row for
SUP-022 (Stillwater Alloys) renders with an amber strip across the top
reading **"⚠ Hidden dependency · 2-hop relationship chain — no direct
contract path"**. The callout fires automatically because the cypher
returns `hops: 2` and the FactCard checks `hops >= 2`. Reinforces that
the proposed alternate isn't reached by any direct contract — it's only
visible through the graph walk via Northgate Industrial Holdings.

### Beat 2 · The contrast (supervisor vs harness) ⏳ partial

**Today (W7 + W2):** the `AlternativeSupplier` row for Stillwater renders
with three reveals stacked on one card:
1. The **Hidden-dependency callout** (amber strip, from W2)
2. The summary chip `qualification: lapsed (expired 2026-04-15)` (from W7)
3. The summary chip `sibling via Northgate Industrial Holdings` (existing)

A reviewer reading the envelope sees BOTH the same-parent trap AND the
qualification failure without expanding anything. Use the lapsed-cert
fact as the rejection rationale when you press **Reject**.

**Once W5 ships:** click **Replay as baseline** on the case. CompareModal
opens with the harness case on the right and the baseline case on the left;
the lapsed-qualification fact is highlighted as harness-only (the supervisor
without the governed review-stage queries doesn't pull qualification info,
so it would have green-lit Stillwater).

**Rejection rationale to pick (from the canned dropdown):**

> "Top swap candidate's quality-system qualification has lapsed — cannot
> ship to flagship-program SKUs until re-certified."

### Beat 3 · The re-plan (re-version on new evidence) ⏳ needs W1

**Today (W7 only):** narrate. The seed data is staged so a fourth program
impact will appear once `POST /api/cases/{id}/revise` exists — the runbook
will be updated to drop the explicit re-version click here.

**Once W1 ships:** click **Simulate new evidence** in the operator console.
A v2 revision of the case is appended; the Envelope's revision selector
flips to `v1 ▾ v2` and the diff gutter highlights the added program impact
(e.g., a previously-unmapped sub-assembly link that pulls a fourth program
into scope). LineagePanel shows a `Re-versioned (new evidence)` event with
the trigger reason.

**Talking point:** _"the same case, re-decided in place — not a new case,
not a re-do, not lost context. The original recommendation is still on the
audit trail; the new one supersedes it with the trigger noted."_

### Beat 4 · Reversible action cancelled and compensated ⏳ needs W3

**Today (W7 only):** narrate. The Aeronova scenario binds an outcome-stage
write action (`supply_assurance_review`) which is registered as
**Compensatable** in the existing actions registry.

**Once W3 ships:** after the **Approve** path fires the action, click
**Compensate** in the ActionsPanel. LineagePanel shows a paired strip:
`action.fired` (the original requisition) → `action.compensated`
(the reversal payload). The "Compensated 4m later" timestamp annotates the
connector.

**Talking point:** _"reversible work was just rolled back without stranding
anything. The compensation event is its own audit row, with the same case
ID. Reviewers don't have to remember which actions are which — the system
knows."_

### Beat 5 · Authority recalculated; only the one risky call escalated ⏳ needs W4

**Today (W7 only):** narrate. The Aeronova case's `ProgramImpact` sum
($48M + $11.5M + $9M ≈ $68M) crosses the $20M delegated-authority ceiling
named in the scenario's `agent_intake.payload`, so a real supply-assurance
deployment would auto-escalate.

**Once W4 ships:** the scenario gains a `risk_bands:` block keyed off
`revenue_at_risk_usd > 20_000_000`. When the agent runs, the LineagePanel
will show:

```
authority.recalculated · from auto-act → review_ready
  reason: revenue_at_risk_usd=68M exceeds delegated ceiling of 20M
```

and the FlowStage indicator will show the original `auto-act` ladder rung
struck through, the new `review_ready` rung emphasised.

**Talking point:** _"the system already knew this case crossed the
delegated-authority ceiling. The escalation isn't a config decision the
reviewer made — it's the policy, applied at the moment the program-impact
was known. The other two routine swaps proceeded auto."_

---

## Act 2 — capturing expert knowledge ✅ ships today

Already wired today via [InsightsModal](../frontend/src/components/InsightsModal.tsx).
The launcher relabel + heuristic-elicitation polish (part of W6) is a
launcher-prose change; the Insights flow itself is live.

**Action:** click **Insights** in the StatusBar → open a pattern → click
**Promote to chip**. Narrate the deck's two-tier story while the chip
materialises in the scenario YAML.

---

## Close — slide 8 mapping

| Close-list bullet | Workstream | Today? |
|---|---|---|
| Hidden tier-2 dependency surfaced before any decision | W7 + W2 | ✅ (amber callout on multi-hop facts) |
| Invalid "alternate" rejected — same parent, lapsed qualification | W7 + W2 + W5 | ✅ visible (callout + qualification chip) · ⏳ baseline contrast UI |
| A decision re-versioned the moment new evidence arrived | W1 | ⏳ |
| A reversible action cancelled and compensated, not stranded | W3 | ⏳ |
| Authority recalculated; only the one risky call escalated | W4 | ⏳ |
| One continuous audit trail across every platform | already shipped | ✅ |

---

## Troubleshooting

- **Scenario doesn't classify.** The prompt must hit one of the
  `match_keywords` in [SC-PP-AERONOVA-026.yaml](../backend/scenarios/SC-PP-AERONOVA-026.yaml).
  Use the runbook prompt verbatim or pick from the list (e.g. "supply
  assurance aeronova", "hidden tier-2 dependency").
- **ProgramImpact returns zero rows.** Re-run `python3 share/tcs_kf_graph_data/seed_neo4j.py`
  — the `INCLUDED_IN` edges only exist after the W7 cypher additions.
- **AlternativeSupplier doesn't show qualification info.** The
  `qualification_status` property is set by the new cypher seed; without
  re-seed, the suffix is omitted (the mapping is backwards-compatible, so
  no error — just a less-impactful summary).
- **Status field reads `active` for SUP-021.** The backfill `SET` block at
  the end of the cypher uses `WHERE s.qualification_status IS NULL` — it
  won't overwrite a `status` you set explicitly on SUP-021. If you accidentally
  cleared SUP-021's status, the simplest fix is a full re-seed.

# Pattern mining (Phase 3a)

The read side of the deck's "promote recurring patterns" step. Reads
the Phase 2 captures in [`case_highlighted_facts`](override-capture.md)
and exposes "for each scenario, which fact ontology types drive each
decision kind, and how often?" as the data feed Phase 3b (the admin
promotion flow) will consume.

Shipped surface:

- HTTP: `GET /api/insights/patterns` (admin-only)
- UI: an **Insights** modal on the operator status bar (only visible to admin role)

Phase 3b (not in this module) will add an admin-only "draft a new
scenario version from this pattern" flow on top of the same aggregates.

---

## API shape

```
GET /api/insights/patterns
```

Admin-only (403 otherwise). Returns:

```json
{
  "generated_at_seconds": 1781035200.0,
  "scenarios": [
    {
      "scenario_id": "SC-PP-008",
      "total_decided_cases": 6,
      "patterns": [
        {
          "decision_kind": "reject",
          "fact_ontology_type": "SanctionsProximity",
          "case_count": 2,
          "share_of_decision_kind": 100.0,
          "share_of_decisions": 33.3,
          "sample_fact_ids": ["SUP-001-PROX", "SUP-007-PROX"]
        },
        { "decision_kind": "request_more_info", "fact_ontology_type": "PriorOverride", "case_count": 2, ... }
      ]
    }
  ]
}
```

Sorted: scenarios by `total_decided_cases` desc; patterns within a
scenario by `case_count` desc.

Both share metrics are present because they answer different
questions:

| Metric | Interprets as |
|---|---|
| `share_of_decision_kind` | *"When the reviewer rejected SC-PP-008, how often did they cite this driver?"* — useful for the promotion threshold |
| `share_of_decisions` | *"Across all SC-PP-008 decisions, how prevalent is this driver?"* — useful for spotting balanced two-way drivers |

---

## SQL shape

```sql
SELECT scenario_id, decision_kind, fact_ontology_type,
       COUNT(DISTINCT case_id) AS n
  FROM case_highlighted_facts
 GROUP BY scenario_id, decision_kind, fact_ontology_type
 ORDER BY n DESC;
```

`COUNT(DISTINCT case_id)` rather than `COUNT(*)` because the Phase 2
denorm table has one row per highlighted fact per case (up to 3 per
case). Counting rows would over-inflate when the reviewer picked the
same ontology type twice for one case (uncommon, but allowed).

`sample_fact_ids` are pulled separately and clipped to 3 to keep the
response small.

---

## UI surface

Status bar → **Insights** (admin-only button) → modal opens. One block
per scenario; one table row per `(decision_kind, fact_ontology_type)`
pattern with: decision pill, ontology type, case count, both share
percentages, and up to 3 sample fact ids.

Empty state when no captures exist: *"No reviewer signal yet. Cases
will populate this view as reviewers flag load-bearing facts during
decisions."*

---

## Verification

### Backend

```bash
pytest tests/test_insights.py -v
```

5 tests: aggregation correctness, sample-id clipping, sort order,
admin-only access (403 for non-admin), empty-state response.

### Frontend

```bash
cd frontend && npm test -- src/components/__tests__/InsightsModal.test.tsx
```

4 tests: empty render, populated render with percentages + samples,
Esc closes, fetch errors render instead of looping on loading.

### Live verification

After deploying:

```bash
# log in via the UI as an admin user → status bar gains an "Insights"
# button next to "Metrics" → opens the modal.

# Or directly:
curl -H "Authorization: Bearer <admin-token>" \
     https://tcs-knowledge-fabric.fly.dev/api/insights/patterns | jq .
```

---

## Phase 3b — promote + demote

The admin-only action that turns a recurring pattern into a scenario
rule. The patterns endpoint above is the read side; this is the write
side that closes the compounding loop.

### Endpoints

```
POST /api/insights/patterns/promote
  body: { scenario_id, decision_kind, fact_ontology_type,
          suggested_rationale?, min_case_count?, min_share_of_kind_pct? }
  → { scenario_id, version, pattern_id, replaced, stats }

POST /api/insights/patterns/demote
  body: { scenario_id, pattern_id }
  → { scenario_id, version, pattern_id, remaining_patterns }
```

Both bump the scenario version via Phase 1 `register()`, so every
promote / demote is an immutable audit-trail snapshot — see the
Versions modal.

### Guardrails

| Guardrail | Default | Override |
|---|---|---|
| `min_case_count` | 2 | per-request body field |
| `min_share_of_kind_pct` | 50 | per-request body field |

Defaults are deliberately permissive so a small demo dataset can
illustrate the loop end-to-end. Production deployments should crank
both up (e.g. `min_case_count=10, min_share_of_kind_pct=80`) before
trusting promoted patterns to influence reviewer behaviour.

Guardrails are re-checked at promote time against the **live**
aggregate (not the value the UI rendered), so a stale modal can't
promote a pattern whose confidence has since decayed.

### Idempotent

Promoting the same `(scenario_id, decision_kind, fact_ontology_type)`
twice replaces the existing entry rather than appending. The
`pattern_id` is preserved across re-promotion so the audit trail stays
single-row per scenario+trigger.

### Promoted-pattern shape on the scenario YAML

```yaml
auto_promoted_patterns:
  - id: auto-7f3a1c
    decision_kind: reject
    trigger:
      ontology_type: SanctionsProximity
      min_facts: 1
    suggested_rationale: >-
      Reviewers cited SanctionsProximity in 8 of 8 reject decisions
      on this scenario (auto-promoted pattern).
    metadata:
      promoted_at: 2026-06-12T17:00:00Z
      promoted_by: admin
      source_case_count: 8
      source_share_of_kind_pct: 100.0
      source_total_decided: 12
```

### Case-detail integration

When a future case binds at least `min_facts` of `trigger.ontology_type`,
the case-detail endpoint surfaces a `matched_promoted_patterns: [...]`
field on the response. The frontend Envelope renders these as advisory
chips above the evidence map:

> **Compounding loop · 1 promoted pattern matched**
> **REJECT** · SanctionsProximity · matched 1 fact on this case
> Reviewers cited SanctionsProximity in 8 of 8 reject decisions on
> this scenario (auto-promoted pattern).
> Based on 8 prior cases · 100% of reject decisions · promoted 2026-06-12

Reviewer is not bound by the suggestion — it's evidence, not coercion.

### Verification

Backend: `pytest tests/test_insights.py` (13 tests including promote
success, idempotency replacement, case-count + share guardrails,
unknown-scenario 404, demote round-trip, admin-only).

Frontend: `cd frontend && npm test`:
- `InsightsModal.test.tsx` (4) — Phase 3a render + Esc + errors
- `InsightsModal.promote.test.tsx` (4) — confirm modal opens, cancel
  does nothing, success refreshes patterns, guardrail error keeps the
  modal open with the server error visible

### Live verification

After deploying:

1. Log in as admin → status bar → **Insights**.
2. Pick a pattern row → **Promote →**.
3. Confirmation modal appears; submit.
4. A toast confirms the scenario bumped to `vN+1`.
5. Re-open the scenario in the Edit modal → footer shows `Currently vN+1`
   and Version history lists the new snapshot.
6. Start a new case that binds the trigger ontology type → the
   advisory banner appears above the evidence map.

---

## Out of scope (deferred)

- **Time-bounded windows** — currently aggregates all-time. A
  `?since=` param + "patterns over the last 30 days" view will matter
  when scenario behaviour drifts.
- **Multi-trigger patterns** — currently each promoted pattern is one
  ontology type. Composite triggers (e.g. *"SanctionsProximity AND
  CarrierExposure"*) are a natural follow-up.
- **Per-scenario drill-down** — the modal lists every scenario; a
  detail page with the underlying case list is the obvious next step.
- **Reviewer one-click apply** — when a promoted pattern matches, the
  rationale modal could pre-fill the suggested_rationale. Not done
  yet; the chip is advisory only.

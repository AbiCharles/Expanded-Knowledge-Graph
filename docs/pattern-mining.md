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

## Out of scope (deferred to Phase 3b)

- **Promote button** — an admin action that takes a pattern row and
  drafts a new scenario version with the pattern encoded (e.g. auto-route
  any case whose binders surface a `SanctionsProximity` ≥ 1-hop hit to
  the procurement lead).
- **Confidence guardrails** — a minimum `case_count` + minimum
  `share_of_decision_kind` before a pattern is promotable.
- **Time-bounded windows** — currently aggregates all-time. A
  `?since=` param + "patterns over the last 30 days" view will matter
  when scenario behaviour drifts.
- **Per-scenario drill-down** — the modal currently lists every
  scenario; a per-scenario detail page with the underlying case list is
  the obvious next step.

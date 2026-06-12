# Override capture (Phase 2)

Phase 2 of the "compounding context" roadmap from the
[KF Framework Comparison deck](KF_Framework_Comparison_glossary.pptx).
Builds on [Phase 1 scenario versioning](scenario-versioning.md) by
adding a **structured record of which facts drove each decision**.

The deck's compounding-learning loop has three steps:

1. **Capture** — record which facts drove the override (this doc, Phase 2)
2. **Mine** — find recurring patterns across many cases (Phase 3)
3. **Promote** — turn high-confidence patterns into a new scenario version (Phase 3)

Phase 2 ships step 1.

---

## The model in one paragraph

Every decided case already carries an immutable lineage of the facts the
agent bound (that's the "passive snapshot" — it falls out of Phase 1 for
free, because lineage is append-only and the case is frozen after the
decision lands). On top of that, when a reviewer reaches a decision they
may optionally flag **up to three facts as load-bearing** — the ones
that tipped the call. Those picks are stored against the case in two
shapes: a JSON list on `CaseRecord.highlighted_fact_refs` for cheap
read-back, and one denormalised row per pick in `case_highlighted_facts`
so Phase 3 can `GROUP BY (scenario_id, decision_kind, fact_ontology_type)`
without un-marshalling JSON.

---

## "Both" mode

The deck offered a passive-vs-active choice; we ship both:

| Mode | What it captures | Available on |
|---|---|---|
| **Passive snapshot** | Every fact the agent bound, at decision time. Falls out of the existing append-only lineage. | Every case (HITL + autonomous). |
| **Active highlight** | Reviewer's pick of up to 3 load-bearing facts. Optional. | HITL cases only — autonomous decisions have no reviewer to ask. |

The passive snapshot is enough for Phase 3 to detect "this fact class
shows up in 80% of rejects on SC-PP-008." The active highlight tightens
the signal: "the reviewer specifically pointed at *this* SanctionsProximity
trail, not just any one of the 13 facts on the page."

---

## On-disk layout

### Case payload

```python
@dataclass
class CaseRecord:
    ...
    highlighted_fact_refs: list[dict] = field(default_factory=list)
    # each ref: {source, ontology_type, id, title?}
```

Lives in `cases.payload` JSON. Cheap to read alongside the rest of the case.

### Denormalised table

```sql
CREATE TABLE case_highlighted_facts (
    id                 INTEGER PRIMARY KEY,
    case_id            TEXT    NOT NULL REFERENCES cases(case_id) ON DELETE CASCADE,
    scenario_id        TEXT    NOT NULL,
    scenario_version   INTEGER,
    decision_kind      TEXT    NOT NULL,     -- approve | reject | request_more_info
    fact_source        TEXT    NOT NULL,
    fact_ontology_type TEXT    NOT NULL,
    fact_id            TEXT    NOT NULL,
    fact_title         TEXT,
    position           INTEGER NOT NULL,     -- 0..2, order the reviewer picked
    highlighted_at     DATETIME NOT NULL
);
CREATE INDEX idx_case_highlighted_facts_mining
    ON case_highlighted_facts(scenario_id, decision_kind, fact_ontology_type);
```

The (scenario_id, scenario_version, decision_kind, fact_ontology_type)
shape is exactly what Phase 3's mining queries need — no joins back to
`cases` required.

---

## HTTP API

```
POST  /api/decisions/{ticket_id}             body adds: highlighted_fact_refs?: HighlightedFactRef[]
GET   /api/cases/{case_id}/highlights        → { case_id, scenario_id, scenario_version, decision_kind, highlighted_fact_refs }
```

The POST validates **≤3 highlights** before touching the case store.
Each `HighlightedFactRef` is `{source, ontology_type, id, title?}` with
the same triple shape as `KnowledgeRef`.

---

## UI affordances

### Rationale modal — [Modals.tsx](../frontend/src/components/Modals.tsx)

Below the reason textarea: an optional **"Which facts were load-bearing?"**
section. Each fact the agent bound (flattened across stages) becomes a
chip; clicking toggles selection up to 3. Hitting the cap disables the
unselected chips with a tooltip.

### Approve modal — same picker

The approve path captures the same shape. Phase 3 mines both directions:
which facts drive **overrides** (reject / request_more_info) and which
drive **confirmations** (approve).

### Case-spec modal — [CaseSpecModal](../frontend/src/components/CaseSpecModal.tsx)

A new **"Reviewer marked these facts as load-bearing (N)"** section
under the Matched-because block, when present. Hides cleanly for
pre-Phase-2 cases and autonomous cases.

---

## Migration

The `case_highlighted_facts` table + the composite index are added by
the existing `_micro_migrate()` ALTER pattern in [`db.py`](../backend/persistence/db.py).
Idempotent: re-running against a populated DB is a no-op.

Cases from before Phase 2 shipped have `highlighted_fact_refs == []`
and produce no `case_highlighted_facts` rows. No backfill is performed.

---

## Verification

### Backend

```bash
pytest tests/test_highlighted_facts.py -v
```

Covers persistence round-trip, the position-overwrite semantic on
replay, idempotency on undecided cases, the validation cap, the
malformed-ref 422, and the read endpoint's empty-state response.

### Frontend

```bash
cd frontend && npm test -- src/components/__tests__/LoadBearingFactsPicker.test.tsx
```

Covers: picker renders one chip per fact, hides when there are no
facts, enforces the cap (disabling further chips), and threads the
picked refs through `onSubmit` in selection order.

### Edit cycle (manual)

1. Open a HITL scenario case (e.g. SC-PP-008) in the operator console.
2. Click **Reject** → rationale modal opens.
3. Tap any three fact chips under "Which facts were load-bearing?";
   confirm the counter reads `(3/3)` and a fourth chip is disabled.
4. Fill the reason, **Continue** → confirm screen lists the three
   highlights under "Load-bearing facts".
5. Submit. Re-open the case in the Case-spec modal → the
   "Reviewer marked these facts as load-bearing" section renders the
   same three.

---

## Out of scope (deferred to Phase 3)

- Pattern mining queries (cross-case aggregates, override-driver
  rankings).
- Reviewer feedback loop dashboards.
- Auto-promotion of recurring patterns into new scenario versions.
- Backfilling highlights for historical cases.

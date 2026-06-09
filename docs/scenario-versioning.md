# Scenario versioning

Phase 1 of the "compounding context" roadmap from the
[KF Framework Comparison deck](KF_Framework_Comparison_glossary.pptx).
It closes the deck's identified governance gap by making every scenario
edit immutable, every case pinnable to a known scenario state, and
historical content inspectable in the UI. Phases 2 (structured override
capture) and 3 (promotion / certification loop) build on this
foundation. See [framework-comparison-status.md](framework-comparison-status.md)
for where each deck element stands today.

---

## The model in one paragraph

Every scenario is now versioned. The live YAML on disk represents the
latest version; every prior version sits as an immutable snapshot at
`backend/scenarios/_versions/<id>/v<N>.yaml`. Editing a scenario through
the API (or the in-app Edit modal) does **not** overwrite the live file
silently — it writes a new immutable snapshot first, bumps the
in-memory `version` field, then rewrites the live YAML to match the new
state. The previous live content survives forever as the previous
version's snapshot. Every case records the exact `scenario_version` it
ran against at creation time, so reopening that case after a later edit
still shows the spec the case actually executed.

---

## On-disk layout

```
backend/scenarios/
  SC-PP-008.yaml                 ← live (binders read this; `version: 4`)
  SC-PP-CARRIER-EXP-022.yaml
  _versions/
    SC-PP-008/
      v1.yaml                    ← immutable
      v2.yaml
      v3.yaml
      v4.yaml                    ← matches live content byte-for-byte
    SC-PP-CARRIER-EXP-022/
      v1.yaml
```

`_versions/` has a leading underscore so `glob("*.yaml")` in
[`ScenarioRegistry.from_directory`](../backend/scenario_loader.py)
skips it. Snapshots are plain YAML, hand-inspectable + diffable via the
shell + `git`.

### Migration on first boot

`ScenarioRegistry.from_directory()` is idempotent. For each loaded YAML:

- If the YAML has no `version:` field AND no matching snapshot, it
  stamps `version: 1` and writes `_versions/<id>/v1.yaml` as the seed.
- If the YAML already carries `version: N`, it heals a missing
  `_versions/<id>/v<N>.yaml` by writing the current live content there.

No separate migration script — running the registry against an
un-migrated tree is the migration. Re-runs are no-ops.

---

## Registry API

[`backend/scenario_loader.py`](../backend/scenario_loader.py)

| Call | Returns | Notes |
|---|---|---|
| `register(scenario, persist=True)` | None | Bumps to `max(in-memory, on-disk) + 1`, writes the snapshot, then rewrites the live YAML. The new version number is stamped on `scenario["version"]` before the function returns. |
| `read_version(scenario_id, version)` | `dict \| None` | Reads `_versions/<id>/v<version>.yaml` on demand. No caching — Case-spec opens are infrequent. |
| `versions_of(scenario_id)` | `list[int]` | All `vN.yaml` files for a scenario, ascending. Empty for in-memory-only scenarios. |
| `saved_at_for_version(id, version)` | `float \| None` | Unix-seconds mtime of the snapshot. Powers the "saved at" timestamp in the Versions modal. |
| `unregister(id)` | None | Deletes the live file AND the entire `_versions/<id>/` directory. Scoped to the scenario; deleting the scenario deletes its history. |

---

## HTTP API

[`backend/api/scenarios.py`](../backend/api/scenarios.py)

```
GET  /api/scenarios/{id}                  → editable subset (live)
GET  /api/scenarios/{id}?full=1           → full live dict
GET  /api/scenarios/{id}?version=N        → full historical dict (snapshot)
GET  /api/scenarios/{id}/versions         → [ { version, saved_at, title } ] newest-first
PATCH /api/scenarios/{id}                 → bumps version; returns { scenario_id, updated, version }
```

The PATCH response surfaces the new version number so the UI can show a
confirmation like `Saved as v4. The prior content is preserved as v3.`

---

## Case → version binding

[`backend/case_record.py`](../backend/case_record.py),
[`backend/persistence/db.py`](../backend/persistence/db.py)

`CaseRecord` gains an `Optional[int] scenario_version` field. Persisted
as a new `cases.scenario_version INTEGER` column added via the existing
`_micro_migrate()` ALTER-TABLE step. Three creation paths stamp it:

| Path | Stamped version |
|---|---|
| `POST /api/cases` (initial classification) | live scenario's `version` at request time |
| `POST /api/cases/{id}/relink` | live version of the chosen scenario at relink time |
| `POST /api/cases/{id}/replay` | **live** version, not the original case's version — replays exercise post-edit behaviour by design |

Cases created before Phase 1 shipped have `scenario_version = NULL`.
The Case-spec modal falls back to the live `?full=1` endpoint for those.

---

## UI affordances

### Edit modal — [ScenarioEditModal](../frontend/src/components/ScenarioEditModal.tsx)

- Footer line: `Currently v3 · Saving creates v4`.
- `Version history →` link launches the Versions modal.
- On save success, a confirmation surfaces the new version number.

### Versions modal — [ScenarioVersionsModal](../frontend/src/components/ScenarioVersionsModal.tsx)

NEW. Two-column read-only view:

- Left: every version newest-first with `vN · title · saved-at`.
- Right: click a row → fetches `?version=N` and renders the full content.

### Case-spec modal — [CaseSpecModal](../frontend/src/components/CaseSpecModal.tsx)

- Header pill: `Ran against v3` next to the scenario id, when the case
  has a pinned version.
- Fetches the historical snapshot rather than the live spec, so a case
  opened after the scenario was edited still shows what executed.

---

## Verification

### Smoke test

```
$ source .venv/bin/activate
$ python3 -c "
from pathlib import Path
from backend.scenario_loader import ScenarioRegistry
reg = ScenarioRegistry.from_directory(Path('backend/scenarios'))
for sid in sorted(reg.ids())[:3]:
    sc = reg.get(sid)
    print(sid, 'version=', sc.get('version'), 'on-disk=', reg.versions_of(sid))
"
```

Expected output after migration: every scenario shows `version=1`,
`on-disk=[1]`.

### Edit cycle (manual)

1. Open the Knowledge → Scenarios tab in the app.
2. Pencil → edit a built-in scenario's title.
3. Save → confirmation alert reads `Saved as v2. The prior content is preserved as v1.`
4. Re-open the Edit modal → footer shows `Currently v2 · Saving creates v3`.
5. Click `Version history →` → both v1 and v2 rows visible; click v1 to read the original.

### Case → version pinning

1. Create a case on the just-edited scenario (now at v2). The case's
   `scenario_version` in the API response is `2`.
2. Edit the scenario again → live moves to v3.
3. Open the Case-spec modal on the original case → header pill reads
   `Ran against v2`; rendered stages match v2, not v3.

---

## Out of scope (deferred to Phase 2 / 3)

- **Diff view** between versions (Versions modal is read-only-current).
- **Rollback** (write a new version that copies an old one's content).
- **Per-version notes / changelog** in the YAML.
- **Override capture** — fact snapshots + optional reviewer highlights
  recorded against the case's pinned version.
- **Promotion** — admin-only flow that turns repeated override patterns
  into a new scenario version (auto-approval guardrails).

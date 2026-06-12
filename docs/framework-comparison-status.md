# Framework comparison — current status

A live companion to the
[KF Framework Comparison deck](KF_Framework_Comparison_glossary.pptx).
The deck scorecards each element of the Atlan / Prukalpa framework
("substrate," "skills," "compounding loop," and so on) against the
Knowledge Fabric and identifies one capability to build in three steps,
plus three elements to deliberately skip. This file tracks what's
**actually shipped** today so the deck and the running system don't
drift.

Status legend: ✅ done · 🟡 in flight · ⬜ to build · 🚫 deliberately out

---

## Substrate ("the three things an agent needs")

| Element | Deck verdict | Status | Where |
|---|---|---|---|
| Data sources (trusted, change-isolated) | Comparable | ✅ | `backend/datasources/` |
| Ontology (shared definitions, attributes, relations) | Comparable | ✅ | `backend/ontologies/`, [ontology.md](ontology.md) |
| Scenarios (procedural knowledge / "skills") | AHEAD | ✅ | `backend/scenarios/`, [scenarios.md](scenarios.md) |
| Activation / retrieval (the runtime itself) | Comparable | ✅ | `backend/orchestrator.py` |

## Norms + governance

| Element | Deck verdict | Status | Where |
|---|---|---|---|
| Decide → Auto → human-review spine | AHEAD | ✅ | `backend/orchestrator.py`, the RationaleModal in the UI |
| Append-only audit lineage | Comparable | ✅ | `backend/persistence/lineage_recorder.py` |
| Scenario versioning (change-isolation, replay) | Build #1 — **FOUNDATION** | ✅ | [scenario-versioning.md](scenario-versioning.md) — shipped Phase 1 |
| Approval / role gating on edits | Partial | 🟡 | Admin-only PATCH exists; structured approval workflow is part of Phase 3 |

## Compounding learning loop ("the deck's one missing capability")

| Element | Deck verdict | Status | Where |
|---|---|---|---|
| Structured override capture (decision + driver facts) | Build #2 | ✅ | [override-capture.md](override-capture.md) — shipped Phase 2 |
| Promotion / certification loop (pattern → new scenario version) | Build #3 — the payoff | 🟡 | Phase 3a (mining) ✅ [pattern-mining.md](pattern-mining.md); Phase 3b (admin promote UI) ⬜ |

## Out of scope (deliberately not built)

| Element | Status | Why |
|---|---|---|
| Activation as a separate layer | 🚫 | Our runtime already is the activation surface; a separate layer would just rename it. |
| Canonical knowledge ingestion (strategy / voice / positioning) | 🚫 | Serves open-ended "what is the company trying to do" questions; ours are bounded, rule-driven decisions. |
| Broad context mining (reverse-engineering from logs) | 🚫 (later) | Premature at our scale. Roadmap candidate once scenarios run into the hundreds. |

---

## Phase progress

| Phase | Scope | Status | Doc |
|---|---|---|---|
| Phase 1 | Scenario versioning + case → version pinning | ✅ live | [scenario-versioning.md](scenario-versioning.md) |
| Phase 2 | Structured override capture ("both" mode: passive snapshot + optional active highlight) | ✅ live | [override-capture.md](override-capture.md) |
| Phase 3a | Pattern mining + insights surface (admin-only) | ✅ live | [pattern-mining.md](pattern-mining.md) |
| Phase 3b | Promotion flow — pattern → new scenario version draft (admin approval) | ⬜ | TBD |

The deck's roadmap was a 3-step build. After Phase 1, the substrate
governance gap is closed: every case records the exact scenario state
it ran against, every edit creates an immutable artifact, and historic
content is inspectable in the UI. Phase 2 builds the data feed for
compounding; Phase 3 turns that data into the auto-resolution itself.

import { useEffect, useMemo, useState } from "react";
import { CaseFull, DecisionKind, FactRow } from "../types";

// =============================================================================
// Teams card modal
// =============================================================================
export function TeamsCardModal({
  active,
  onClose,
  onDecision,
}: {
  active: CaseFull;
  onClose: () => void;
  onDecision: (d: DecisionKind) => void;
}) {
  const sc = active.scenario!;
  return (
    <div className="modal-backdrop" onClick={(e) => e.target === e.currentTarget && onClose()}>
      <div className="teams-card">
        <div className="teams-header">
          <div className="teams-icon">T</div>
          <div>
            <div className="teams-app-name">TCS Knowledge Fabric · Reviewer</div>
            <div className="teams-channel">{sc.teams_channel}</div>
          </div>
          <button className="teams-close" onClick={onClose}>
            ×
          </button>
        </div>
        <div className="teams-body">
          <div className="tc-headline">{sc.teams_headline}</div>
          <div className="tc-sub">
            Case {active.case_id} · Ticket{" "}
            {active.lineage.find((l) => l.action === "submitted")?.detail?.match(/async-[a-f0-9]+/)?.[0] ?? "—"}
          </div>

          <div className="tc-section-label">Proposed action</div>
          <div className="tc-action-detail">
            <ActionPayload caseFull={active} />
          </div>

          {active.stages.map((s) => (
            <div key={s.stage}>
              <div className="tc-section-label">
                {s.stage.replace("_", " ")} · {s.binder}
              </div>
              {s.facts.map((f) => (
                <div className="tc-fact" key={`${f.source}-${f.id}`}>
                  <div className="tc-fact-title">
                    {f.title}{" "}
                    <span style={{ color: "var(--ink-muted)", fontWeight: 400 }}>
                      · {f.ontology_type}:{f.id}
                    </span>
                  </div>
                  <div className="tc-fact-payload">{f.summary}</div>
                </div>
              ))}
            </div>
          ))}
        </div>
        <div className="teams-actions">
          <button className="tc-btn tc-btn-approve" onClick={() => onDecision("approve")}>
            Approve
          </button>
          <button className="tc-btn tc-btn-info" onClick={() => onDecision("request_more_info")}>
            Need more info
          </button>
          <button className="tc-btn tc-btn-reject" onClick={() => onDecision("reject")}>
            Reject
          </button>
        </div>
      </div>
    </div>
  );
}

function ActionPayload({ caseFull }: { caseFull: CaseFull }) {
  // We don't have the action object directly on CaseFull — show scenario-derived payload
  // by extracting from action_payload via /api/scenarios is overkill. Render a
  // compact summary from the lineage detail.
  const detail = caseFull.lineage.find((l) => l.action === "bound" && l.stage === "proposal")?.detail;
  return (
    <>
      <div>
        <span className="k">action_type</span>
        {caseFull.scenario?.id || ""}
      </div>
      <div>
        <span className="k">case_id</span>
        {caseFull.case_id}
      </div>
      {detail && (
        <div>
          <span className="k">proposal</span>
          {detail}
        </div>
      )}
    </>
  );
}

// =============================================================================
// Phase 2 — load-bearing fact picker (shared by RationaleModal + ApproveModal)
// =============================================================================
// Backend caps at 3 (decisions.MAX_HIGHLIGHTED_FACTS). Mirrored here so
// the UI can disable further selections at the cap.
const MAX_HIGHLIGHTED_FACTS = 3;

function LoadBearingFactsPicker({
  active,
  selected,
  onChange,
}: {
  active: CaseFull;
  selected: import("../api").HighlightedFactRef[];
  onChange: (refs: import("../api").HighlightedFactRef[]) => void;
}) {
  // Flatten facts across stages — the picker should let the reviewer
  // single out anything the agent surfaced, not just the review stage.
  const allFacts = (active.stages || []).flatMap((s) =>
    s.facts.map((f) => ({
      source: f.source,
      ontology_type: f.ontology_type,
      id: f.id,
      title: f.title || null,
    })),
  );

  if (allFacts.length === 0) return null;

  const refKey = (r: { source: string; ontology_type: string; id: string }) =>
    `${r.source}|${r.ontology_type}|${r.id}`;
  const selectedKeys = new Set(selected.map(refKey));

  const toggle = (fact: import("../api").HighlightedFactRef) => {
    const key = refKey(fact);
    if (selectedKeys.has(key)) {
      onChange(selected.filter((r) => refKey(r) !== key));
      return;
    }
    if (selected.length >= MAX_HIGHLIGHTED_FACTS) return;  // hit the cap
    onChange([...selected, fact]);
  };

  return (
    <div className="rationale-loadbearing">
      <div className="rationale-section-label">
        Which facts were load-bearing? · optional · pick up to {MAX_HIGHLIGHTED_FACTS}
        <span className="loadbearing-count">
          {" "}({selected.length}/{MAX_HIGHLIGHTED_FACTS})
        </span>
      </div>
      <div className="loadbearing-help">
        Phase 2 of the compounding loop. When you flag the 1–3 facts that
        tipped the decision, the platform learns which evidence patterns
        actually drive overrides — feeding the eventual auto-promotion of
        new scenario versions.
      </div>
      <div className="loadbearing-chips">
        {allFacts.map((f, idx) => {
          const isOn = selectedKeys.has(refKey(f));
          const atCap = !isOn && selected.length >= MAX_HIGHLIGHTED_FACTS;
          return (
            <button
              key={`${refKey(f)}|${idx}`}
              type="button"
              className={`loadbearing-chip${isOn ? " on" : ""}${atCap ? " disabled" : ""}`}
              onClick={() => toggle(f)}
              disabled={atCap}
              aria-pressed={isOn}
              title={atCap ? `Cap of ${MAX_HIGHLIGHTED_FACTS} reached` : undefined}
            >
              <span className="loadbearing-chip-type">{f.ontology_type}</span>
              <span className="loadbearing-chip-id">{f.id}</span>
              {f.title && <span className="loadbearing-chip-title">{f.title}</span>}
            </button>
          );
        })}
      </div>
    </div>
  );
}

// =============================================================================
// Rationale modal — two views: edit + confirm
// =============================================================================
export function RationaleModal({
  active,
  decision,
  onClose,
  onSubmit,
}: {
  active: CaseFull;
  decision: "reject" | "request_more_info";
  onClose: () => void;
  onSubmit: (
    rationale: string,
    followUp: string | null,
    highlightedRefs: import("../api").HighlightedFactRef[],
  ) => void;
}) {
  const isReject = decision === "reject";
  const reasons = active.scenario?.rationale_reasons?.[decision] ?? [];
  const [text, setText] = useState("");
  const [followUp, setFollowUp] = useState("");
  const [view, setView] = useState<"edit" | "confirm">("edit");
  // Phase 2 — reviewer's optional load-bearing fact picks. Ordered =
  // the order they were tapped; capped at MAX_HIGHLIGHTS by the API.
  const [highlightedRefs, setHighlightedRefs] = useState<
    import("../api").HighlightedFactRef[]
  >([]);

  return (
    <div
      className="modal-backdrop layer-2"
      onClick={(e) => e.target === e.currentTarget && onClose()}
    >
      <div className="rationale-card">
        <div className={`rationale-header${isReject ? "" : " mode-info"}`}>
          <div className="rationale-eyebrow">Reviewer rationale required</div>
          <div className="rationale-title">{isReject ? "Decline this action" : "Request more information"}</div>
        </div>

        {view === "edit" && (
          <>
            <div className="rationale-body">
              <div className="rationale-section-label">Quick-pick reasons · click to fill</div>
              <div className="rationale-chips">
                {reasons.map((r) => (
                  <button
                    key={r}
                    className={`rationale-chip${text === r ? " selected" : ""}`}
                    onClick={() => setText(r)}
                  >
                    {r}
                  </button>
                ))}
              </div>

              <div className="rationale-section-label">Reason</div>
              <textarea
                className="rationale-textarea"
                placeholder="Type or edit the reason for your decision…"
                value={text}
                onChange={(e) => setText(e.target.value)}
                onKeyDown={(e) => {
                  if ((e.metaKey || e.ctrlKey) && e.key === "Enter" && text.trim().length >= 4)
                    setView("confirm");
                }}
              />

              <div className="rationale-section-label" style={{ marginTop: 18 }}>
                Follow-up reminder · optional
              </div>
              <div className="followup-chips">
                {[
                  ["", "No follow-up"],
                  ["24h", "24 hours"],
                  ["3d", "3 days"],
                  ["1w", "1 week"],
                ].map(([val, label]) => (
                  <button
                    key={val}
                    className={`fu-chip${followUp === val ? " selected" : ""}`}
                    onClick={() => setFollowUp(val)}
                  >
                    {label}
                  </button>
                ))}
              </div>
              <LoadBearingFactsPicker
                active={active}
                selected={highlightedRefs}
                onChange={setHighlightedRefs}
              />
              <div className="rationale-help">
                This reason and any follow-up will be recorded in the audit lineage and shown back to the operator.
              </div>
            </div>
            <div className="rationale-footer">
              <button className="rationale-cancel" onClick={onClose}>
                ← Back to review
              </button>
              <button
                className={`rationale-submit${isReject ? "" : " mode-info"}`}
                disabled={text.trim().length < 4}
                onClick={() => setView("confirm")}
              >
                Continue
              </button>
            </div>
          </>
        )}

        {view === "confirm" && (
          <>
            <div className="rationale-body">
              <div className={`confirm-warning${isReject ? " mode-reject" : ""}`}>
                <div className="confirm-icon">!</div>
                <div className="confirm-warning-text">
                  <strong>{isReject ? "Are you sure you want to reject this action?" : "Are you sure you want to request more information?"}</strong>
                  <div>
                    {isReject
                      ? "Once submitted, this decision is recorded in the audit log and the agent is notified. The action will be aborted."
                      : "Once submitted, the case loops back to review with your questions appended. The agent will not execute until you decide again."}
                  </div>
                </div>
              </div>
              <div className="rationale-section-label">Your reason</div>
              <div className="confirm-quote">"{text}"</div>
              {followUp && (
                <>
                  <div className="rationale-section-label">Follow-up</div>
                  <div className="confirm-followup">⏱ Revisit in {followUpLabel(followUp)}</div>
                </>
              )}
              {highlightedRefs.length > 0 && (
                <>
                  <div className="rationale-section-label">Load-bearing facts</div>
                  <div className="confirm-highlights">
                    {highlightedRefs.map((r, i) => (
                      <div key={`${r.source}|${r.id}|${i}`} className="confirm-highlight-row">
                        <span className="confirm-highlight-pos">{i + 1}.</span>
                        <span className="confirm-highlight-type">{r.ontology_type}</span>
                        <span className="confirm-highlight-id">{r.id}</span>
                        {r.title && <span className="confirm-highlight-title">{r.title}</span>}
                      </div>
                    ))}
                  </div>
                </>
              )}
            </div>
            <div className="rationale-footer">
              <button className="rationale-cancel" onClick={() => setView("edit")}>
                ← Back to edit
              </button>
              <button
                className={`rationale-submit${isReject ? "" : " mode-info"}`}
                onClick={() => onSubmit(text, followUp || null, highlightedRefs)}
              >
                {isReject ? "Yes, reject" : "Yes, send back"}
              </button>
            </div>
          </>
        )}
      </div>
    </div>
  );
}

function followUpLabel(fu: string): string {
  if (fu === "24h") return "24 hours";
  if (fu === "3d") return "3 days";
  if (fu === "1w") return "1 week";
  return fu;
}

// =============================================================================
// Approve confirmation modal
// =============================================================================
export function ApproveModal({
  active,
  onCancel,
  onConfirm,
}: {
  active: CaseFull;
  onCancel: () => void;
  onConfirm: (highlightedRefs: import("../api").HighlightedFactRef[]) => void;
}) {
  const msg = active.scenario?.execute_message || "The agent will proceed with this action.";
  // Phase 2 — even on approve, the reviewer can mark which facts
  // CONFIRMED the agent's recommendation. Phase 3 mines both directions
  // (overrides + confirmations) to learn which evidence patterns matter.
  const [highlightedRefs, setHighlightedRefs] = useState<
    import("../api").HighlightedFactRef[]
  >([]);
  return (
    <div className="modal-backdrop layer-2" onClick={(e) => e.target === e.currentTarget && onCancel()}>
      <div className="approve-card">
        <div className="approve-header">
          <div className="approve-eyebrow">Confirm action</div>
          <div className="approve-title">Confirm execute</div>
        </div>
        <div className="approve-body">
          <div className="approve-msg" dangerouslySetInnerHTML={{ __html: msg }} />
          <LoadBearingFactsPicker
            active={active}
            selected={highlightedRefs}
            onChange={setHighlightedRefs}
          />
        </div>
        <div className="approve-footer">
          <button className="rationale-cancel" onClick={onCancel}>
            Cancel
          </button>
          <button className="approve-submit" onClick={() => onConfirm(highlightedRefs)}>
            Confirm execute
          </button>
        </div>
      </div>
    </div>
  );
}

// =============================================================================
// Auto-approve badge (autonomous scenarios)
// =============================================================================
export function AutoApproveModal({
  guardrailId,
  reason,
  onClose,
}: {
  guardrailId: string;
  reason: string;
  onClose: () => void;
}) {
  // Auto-dismiss after 6s. Long enough to read; the Dismiss button is there
  // for anyone who wants to clear it sooner or keep it on screen longer (the
  // timer cancels if the user clicks).
  useEffect(() => {
    const t = setTimeout(onClose, 6000);
    return () => clearTimeout(t);
  }, [onClose]);

  return (
    <div className="auto-toast" role="status" aria-live="polite">
      <button
        className="auto-toast-close"
        onClick={onClose}
        type="button"
        aria-label="Dismiss"
      >
        ×
      </button>
      <div className="auto-toast-eyebrow">Autonomous decision · auto-approved</div>
      <div className="auto-toast-guardrail">{guardrailId}</div>
      <div className="auto-toast-reason">{reason}</div>
      <div className="auto-toast-progress" aria-hidden="true" />
    </div>
  );
}

// =============================================================================
// Comparison modal — fetches both cases and renders side by side
// =============================================================================
export function CompareModal({
  cases,
  onClose,
}: {
  cases: [CaseFull, CaseFull];
  onClose: () => void;
}) {
  const [a, b] = useMemo(() => cases, [cases]);
  // W5 / Beat 2 — order so the HARNESS case is on the left and the BASELINE
  // case is on the right when one of them is baseline. Reading L→R then
  // matches the deck's narrative: "the harness saw X; the baseline saw Y".
  const baselineMode = !!(a.baseline || b.baseline);
  const harness = baselineMode ? (a.baseline ? b : a) : a;
  const baseline = baselineMode ? (a.baseline ? a : b) : b;
  // Compute "facts the harness saw that the baseline didn't" by gathering
  // every (source, ontology_type, id) triple on each side and diffing.
  // The review-stage queries that baseline mode skipped show up here as
  // facts present only on the harness side.
  const harnessOnlyFacts = useMemo(() => {
    if (!baselineMode) return [];
    const baselineKeys = new Set(
      (baseline.stages ?? []).flatMap((s) =>
        s.facts.map((f) => `${f.source}|${f.ontology_type}|${f.id}`),
      ),
    );
    const out: { stage: string; fact: FactRow }[] = [];
    for (const stage of harness.stages ?? []) {
      for (const fact of stage.facts) {
        const k = `${fact.source}|${fact.ontology_type}|${fact.id}`;
        if (!baselineKeys.has(k)) {
          out.push({ stage: stage.stage, fact });
        }
      }
    }
    return out;
  }, [baselineMode, baseline, harness]);

  // W5 / Beat 2 — pull the actual write-action args each side fired so
  // the comparison can lead with "harness picked Ironcrest, baseline
  // picked Stillwater" rather than just listing fact counts. We look
  // for the common Aeronova-shape args (alt_supplier_*) so the
  // contrast renders for that scenario; falls back gracefully when
  // those fields aren't present (other scenarios just show "approve
  // ran against X args").
  const actionPick = useMemo(() => {
    if (!baselineMode) return null;
    const pickFrom = (c: CaseFull) => {
      const args = c.execution_result?.args ?? null;
      if (!args) return null;
      const altId = args["alt_supplier_id"];
      const altName = args["alt_supplier_name"];
      if (!altId && !altName) return null;
      return {
        altId: String(altId ?? ""),
        altName: String(altName ?? ""),
      };
    };
    const h = pickFrom(harness);
    const b = pickFrom(baseline);
    if (!h && !b) return null;
    return { harness: h, baseline: b };
  }, [baselineMode, harness, baseline]);

  return (
    <div className="modal-backdrop" onClick={(e) => e.target === e.currentTarget && onClose()}>
      <div className="compare-modal">
        <div className="compare-header">
          <div className="compare-title">
            {baselineMode
              ? "Baseline vs harness — same decision label, different supplier"
              : "Side-by-side replay comparison"}
          </div>
          <button className="compare-close" onClick={onClose}>
            ×
          </button>
        </div>
        {baselineMode && (
          <div className="compare-banner">
            {actionPick && (
              <div className="compare-action-pick-box">
                <div className="compare-action-pick-eyebrow">
                  Both runs ended at <strong>approve</strong> — but committed to different suppliers
                </div>
                <div className="compare-action-pick-grid">
                  <div className="compare-action-pick-cell harness">
                    <div className="compare-action-pick-label">Harness picked</div>
                    <div className="compare-action-pick-value">
                      {actionPick.harness?.altId ?? "—"}
                      {actionPick.harness?.altName ? (
                        <span className="compare-action-pick-name">
                          {" · "}{actionPick.harness.altName}
                        </span>
                      ) : null}
                    </div>
                    <div className="compare-action-pick-note">
                      Qualified · JV partner of the failing supplier · reliability 0.91
                    </div>
                  </div>
                  <div className="compare-action-pick-cell baseline">
                    <div className="compare-action-pick-label">Baseline picked</div>
                    <div className="compare-action-pick-value">
                      {actionPick.baseline?.altId ?? "—"}
                      {actionPick.baseline?.altName ? (
                        <span className="compare-action-pick-name">
                          {" · "}{actionPick.baseline.altName}
                        </span>
                      ) : null}
                    </div>
                    <div className="compare-action-pick-note">
                      ⚠ Same parent (Northgate Industrial Holdings) as the failing supplier
                      · qualification lapsed 2026-04-15 · can't ship to flagship-program SKUs
                    </div>
                  </div>
                </div>
              </div>
            )}
            <div className="compare-banner-text">
              <strong>
                {harnessOnlyFacts.length} review-stage fact
                {harnessOnlyFacts.length === 1 ? "" : "s"}
              </strong>
              {" "}drove the harness toward the safer pick — facts a supervisor
              without the governed knowledge layer would not have seen
              {harnessOnlyFacts.length > 0 ? ":" : "."}
            </div>
            {harnessOnlyFacts.length > 0 && (
              <ul className="compare-banner-facts">
                {harnessOnlyFacts.map(({ stage, fact }, i) => (
                  <li
                    key={`${fact.source}|${fact.id}|${i}`}
                    className="compare-banner-fact-row"
                  >
                    <div className="compare-banner-fact-meta">
                      <span className="compare-banner-fact-type">
                        {fact.ontology_type}
                      </span>
                      <span className="compare-banner-fact-stage">
                        · stage {stage}
                      </span>
                    </div>
                    {fact.title && (
                      <div className="compare-banner-fact-title">
                        {fact.title}
                      </div>
                    )}
                    {fact.summary && (
                      <div className="compare-banner-fact-summary">
                        {fact.summary}
                      </div>
                    )}
                  </li>
                ))}
              </ul>
            )}
          </div>
        )}
        <div className="compare-body">
          <CompareSide
            caseFull={baselineMode ? harness : a}
            kind={baselineMode ? "harness" : a.replay_decision ? "replay" : "original"}
          />
          <div className="compare-divider" />
          <CompareSide
            caseFull={baselineMode ? baseline : b}
            kind={baselineMode ? "baseline" : b.replay_decision ? "replay" : "original"}
          />
        </div>
      </div>
    </div>
  );
}

function CompareSide({
  caseFull,
  kind,
}: {
  caseFull: CaseFull;
  kind: "original" | "replay" | "harness" | "baseline";
}) {
  const sc = caseFull.scenario;
  const decision = caseFull.decision_kind || "—";
  const o = sc?.outcomes?.[decision];
  const decisionColor =
    decision === "approve"
      ? "var(--emerald)"
      : decision === "reject"
      ? "var(--crimson)"
      : "var(--amber)";
  const decisionLabel = decision === "request_more_info" ? "More info" : decision;

  // W5 / Beat 2 — per-stage fact counts so the side-by-side surfaces
  // the gap in evidence between harness and baseline. The empty review
  // stage on a baseline side is the literal narrative ("no review
  // evidence").
  const stageCounts = (caseFull.stages ?? []).map((s) => ({
    stage: s.stage,
    count: s.facts.length,
  }));
  const reviewCount = stageCounts.find((s) => s.stage === "review")?.count ?? 0;
  const isBaselineKind = kind === "baseline";

  // Decision subtitle reads as a one-liner sketching the EVIDENCE behind
  // the decision. Differentiates "informed by N review facts" from
  // "naive — no review evidence" so identical "APPROVE" pills on both
  // sides aren't ambiguous.
  const decisionSubtitle = isBaselineKind
    ? "naive — no review-stage evidence"
    : reviewCount > 0
    ? `informed by ${reviewCount} review-stage fact${reviewCount === 1 ? "" : "s"}`
    : "no review-stage facts surfaced";

  return (
    <div className="compare-side">
      <div className={`compare-side-eyebrow compare-side-eyebrow-${kind}`}>
        {caseFull.case_id} · {kind}
      </div>
      <div className="compare-side-headline">{sc?.title}</div>

      <div className="compare-block">
        <div className="compare-block-label">Operator prompt</div>
        <div className="compare-block-content">{caseFull.prompt}</div>
      </div>
      <div className="compare-block" style={{ borderColor: decisionColor }}>
        <div className="compare-block-label" style={{ color: decisionColor }}>
          Reviewer decision · {decisionLabel}
        </div>
        <div className="compare-block-content">
          <strong>{o?.headline}</strong>
          <br />
          {o?.detail}
          <div className="compare-decision-subtitle">{decisionSubtitle}</div>
        </div>
      </div>
      <div className="compare-block">
        <div className="compare-block-label">Evidence by stage</div>
        <div className="compare-stage-rows">
          {stageCounts.map((s) => {
            const isReview = s.stage === "review";
            const isEmpty = s.count === 0;
            const cls =
              isReview && isEmpty && isBaselineKind
                ? "compare-stage-row baseline-skipped"
                : isReview && !isEmpty
                ? "compare-stage-row review-evidence"
                : "compare-stage-row";
            return (
              <div key={s.stage} className={cls}>
                <span className="compare-stage-name">{s.stage}</span>
                <span className="compare-stage-count">
                  {s.count} fact{s.count === 1 ? "" : "s"}
                </span>
                {isReview && isEmpty && isBaselineKind && (
                  <span className="compare-stage-tag">⚠ skipped</span>
                )}
                {isReview && !isEmpty && (
                  <span className="compare-stage-tag review">●</span>
                )}
              </div>
            );
          })}
        </div>
      </div>
      {/* W5 / Beat 2 — on the harness side, show the actual review-stage
          facts the baseline missed (title + summary). On the baseline
          side, show why the review stage is empty. */}
      {(kind === "harness" || kind === "baseline") && (
        <div className="compare-block">
          <div className="compare-block-label">
            {kind === "harness"
              ? "Review-stage evidence (the baseline didn't see this)"
              : "Review-stage evidence"}
          </div>
          <div className="compare-block-content compare-review-facts">
            {kind === "baseline" ? (
              <div className="compare-review-empty">
                ⚠ Baseline reviewer had <strong>no review-stage evidence</strong>.
                The review queries were skipped because the supervisor lacks
                the governed knowledge layer that surfaces PriorOverride +
                PolicyExcerpt + similar governance-store lookups.
              </div>
            ) : (
              (() => {
                const reviewFacts =
                  caseFull.stages?.find((s) => s.stage === "review")?.facts ?? [];
                if (reviewFacts.length === 0) {
                  return (
                    <div className="compare-review-empty">
                      (no review-stage facts on the harness side either)
                    </div>
                  );
                }
                return (
                  <ul className="compare-review-fact-list">
                    {reviewFacts.map((f, i) => (
                      <li
                        key={`${f.source}|${f.id}|${i}`}
                        className="compare-review-fact"
                      >
                        <div className="compare-review-fact-meta">
                          <span className="compare-review-fact-type">
                            {f.ontology_type}
                          </span>
                        </div>
                        {f.title && (
                          <div className="compare-review-fact-title">
                            {f.title}
                          </div>
                        )}
                        {f.summary && (
                          <div className="compare-review-fact-summary">
                            {f.summary}
                          </div>
                        )}
                      </li>
                    ))}
                  </ul>
                );
              })()
            )}
          </div>
        </div>
      )}
      {caseFull.lineage.find((l) => l.action === "decided")?.detail && (
        <div className="compare-block" style={{ borderColor: decisionColor }}>
          <div className="compare-block-label" style={{ color: decisionColor }}>
            Reviewer's reason
          </div>
          <div className="compare-block-content" style={{ fontStyle: "italic" }}>
            "{caseFull.lineage.find((l) => l.action === "decided")?.detail}"
          </div>
        </div>
      )}
      <div className="compare-block">
        <div className="compare-block-label">Lineage</div>
        <div className="compare-block-content">
          {caseFull.lineage.map((ev) => (
            <div className="compare-lineage-event" key={ev.sequence}>
              <span className="seq">#{String(ev.sequence).padStart(2, "0")}</span>
              {ev.stage} · {ev.actor} — {ev.detail}
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}

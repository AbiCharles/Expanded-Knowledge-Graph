// Types mirror the backend Pydantic shapes. Hand-maintained — small surface
// and we'd rather avoid a code-gen step for this.

export type DecisionKind = "approve" | "reject" | "request_more_info";
export type Phase =
  | "awaiting_clarification"
  | "binding"
  | "review_ready"
  | "reviewing"
  | "complete"
  | "cancelled";

export interface ScenarioRow {
  id: string;
  title: string;
  domain: string;
  autonomous: boolean;
  // Immutable version number this scenario is currently at. Bumped on
  // every edit; the case-spec modal renders historic snapshots via
  // `?version=N`. Null on the rare in-memory-only scenarios.
  version?: number | null;
  suggested_prompt: string;
  // Unix-seconds freshness; backend sorts newest-first. Optional because
  // older API responses may not have it.
  mtime?: number | null;
  run_count?: number;
  last_run_at?: string | null;
  approve_count?: number;
  reject_count?: number;
  auto_count?: number;
  // Unique backing-source kinds (csv | sqlite | postgres | http |
  // vector_store | neo4j) and source ids that the scenario's
  // ontology_queries resolve through. Empty for hand-authored fact-only
  // chips. Surfaced as a badge on the chip so operators can tell at a
  // glance which physical store(s) a chip routes to.
  source_kinds?: string[];
  source_ids?: string[];
  // Surfaces the scenario in the operator console's "Pinned" row above the
  // collapsible Suggestions panel. Used for demo-headlining scenarios so the
  // primary one-click path is always visible without expanding the catalogue.
  pinned?: boolean;
}

export interface FactRow {
  source: string;
  ontology_type: string;
  id: string;
  uri: string | null;
  title: string | null;
  summary: string | null;
  via_ontology?: string | null;
  via_source_binding?: string | null;
  // Correlates this fact back to the ontology_query that produced it.
  // Null/undefined for inline facts authored directly in the scenario.
  query_index?: number | null;
  // Structured multi-hop depth markers from graph resolvers (Neo4j cypher
  // RETURNing `hops` / `tier` columns). Used to render a "hidden dependency"
  // callout when the entity is reached through 2+ relationship hops or sits
  // at tier 2+ in a supply-chain walk. Absent for facts that have no graph-
  // distance semantics (inline facts, single-node lookups, etc.).
  hops?: number | null;
  tier?: number | null;
  // Role + path markers (Neo4j-resolved). `status` carries an operational
  // state like `chapter_11_filed_YYYY-MM-DD` and drives the FAILING role
  // pill on Supplier facts. `via_path` is the human-readable relationship
  // vector ("sibling via Northgate Industrial Holdings (HoldingCompany)")
  // used inside the hidden-dependency callout. `via_node_id` is the
  // intermediate graph-node ID (e.g. `HOLD-005`) used by GraphViz to draw
  // the highlighted chain.
  status?: string | null;
  via_path?: string | null;
  via_node_id?: string | null;
}

// One ontology_query issued by the stage binder. The frontend's
// QueryPlanPanel uses this to render "why these cards?" and to enable
// click-to-highlight against the facts grid.
export interface QuerySpec {
  index: number;
  ontology_type: string;
  ontology: string | null;
  where: Record<string, unknown>;
  purpose: string;
  max_results: number;
  fact_count: number;
}

export interface StagePayload {
  stage: string;
  binder: string;
  facts: FactRow[];
  queries?: QuerySpec[];
}

export interface LineageEvent {
  sequence: number;
  stage: string;
  actor: string;
  action: string;
  knowledge_refs: { source: string; ontology_type: string; id: string; version?: string | null; uri?: string | null }[];
  timestamp: string;
  detail: string | null;
}

export interface CreateCaseResponse {
  case_id: string;
  scenario_id: string | null;
  interpreted_as: string;
  clarifying_question: string;
  confidence: number;
  candidates: ScenarioCandidate[];
  // Present only when the planner detected a multi-scenario question.
  pipeline?: PipelineForecast | null;
}

// The planner's ordered pipeline + projected Outcome DAG (mirrors
// PipelineOut in backend/api/cases.py). Rendered by PipelineForecastPanel.
export interface PipelineStepPlan {
  scenario_id: string;
  title: string;
  why: string;
}
export interface PipelineForecast {
  steps: PipelineStepPlan[];
  rationale: string;
  confidence: number;
  forecast: OutcomePlan;
}

export interface ScenarioCandidate {
  scenario_id: string;
  title: string;
  confidence: number;
}

export interface CaseSummary {
  case_id: string;
  prompt: string;
  scenario_id: string | null;
  // The immutable scenario version this case ran against (or null for
  // cases created before the versioning migration ran). The Case-spec
  // modal uses this to fetch the historical version snapshot rather
  // than the live scenario, so reviewers see exactly what the agent
  // executed.
  scenario_version?: number | null;
  phase: Phase;
  decision_kind: string | null;
  interpreted_as: string | null;
  clarifying_question: string | null;
  confidence: number;
  candidates: ScenarioCandidate[];
  sibling_case_ids: string[];
  replay_decision: DecisionKind | null;
  // W5 / Beat 2 — true when this case is a baseline replay (review-stage
  // queries skipped so the case represents "what a supervisor without the
  // governed knowledge layer would have surfaced").
  baseline?: boolean;
}

export interface ScenarioMeta {
  id: string;
  title: string;
  domain: string;
  autonomous: boolean;
  operator_role?: { label: string; name: string };
  reviewer_role?: { label: string; name: string };
  teams_channel?: string;
  teams_headline?: string;
  execute_message?: string;
  rationale_reasons: { reject?: string[]; request_more_info?: string[] };
  outcomes: Record<string, { headline: string; detail: string }>;
  auto_approval_guardrail?: string;
  auto_approval_reason?: string;
  // The write-action target the orchestrator will dispatch on approve
  // (HITL) or directly (autonomous). Drives the Action Preview card
  // shown before the reviewer acts, and the CHOSEN highlight on the
  // matching evidence card (e.g. the FreightRate row whose total
  // matches the executor's target cost).
  executor?: {
    action_id: string;
    arguments: Record<string, string | number | boolean | null>;
  } | null;
}

// Phase 3b — an auto_promoted_pattern from the scenario that matched
// at least N facts of the configured ontology_type on this case.
// Surfaced as an advisory chip on the Envelope so the reviewer sees
// "in 8 of 8 similar cases, reviewers rejected for this ontology
// type" before they decide.
export interface MatchedPromotedPattern {
  id: string;
  decision_kind: string;
  suggested_rationale: string | null;
  trigger: { ontology_type: string; min_facts: number };
  metadata: {
    promoted_at?: string;
    promoted_by?: string;
    source_case_count?: number;
    source_share_of_kind_pct?: number;
    source_total_decided?: number;
  };
  matched_fact_count: number;
  matched_fact_ids: string[];
}

// W1 / Beat 3 — immutable snapshot of a case's stages at a point in time.
// v1 lands when the initial decision is recorded; v2+ come from /revise
// calls (narrative triggers or generic refresh).
export interface CaseRevision {
  revision_no: number;
  // Same shape as CaseFull.stages so the Envelope can render any
  // historical revision through the same FactCard code path it uses
  // for the live state.
  stages_snapshot: StagePayload[];
  decision: string | null;
  // "initial" for v1, a trigger id ("ironcrest_qual_lapsed", etc.) for
  // narrative triggers, or "generic_refresh" for the diff-the-current-
  // state path.
  triggered_by: string;
  trigger_label: string;
  // ISO-8601 UTC.
  created_at: string;
}

export interface CaseFull extends CaseSummary {
  stages: StagePayload[];
  lineage: LineageEvent[];
  scenario?: ScenarioMeta;
  closing_message?: string;
  execution_result?: ExecutionResult | null;
  // W1 / Beat 3 — revision history. Empty until the case completes;
  // [v1, v2, v3...] in order once it does.
  revisions?: CaseRevision[];
  current_revision?: number;
  // Result of a manual /compensate call (W3 — deck Beat 4). Populated
  // when the FDE clicks the Compensate button on a compensatable
  // executed action and the reversal succeeds (or fails — `ok=false`
  // captures a failed compensation).
  compensation_result?: ExecutionResult | null;
  // W4 / Beat 5 — dynamic authority recalculation. Populated by the
  // orchestrator after the proposal stage when a scenario's `risk_bands`
  // block matches. `escalated: true` means an autonomous scenario was
  // demoted to review_ready; the FlowStage banner reads this to render
  // the ladder override.
  risk_band?: {
    band: string;
    matched_field?: string | null;
    matched_value?: number | string | null;
    threshold?: number | string | null;
    op?: string | null;
    escalated?: boolean;
    reason?: string | null;
  } | null;
  matched_promoted_patterns?: MatchedPromotedPattern[];
}

// Result of a write action's executor (sql_update or http_request). Populated
// by the orchestrator on autonomous + post-approve paths. Used by the UI to
// render a before/after diff in the closing message.
export interface ExecutionResult {
  action_id: string;
  ok: boolean;
  detail: string;
  response_status?: number | null;
  args?: Record<string, unknown>;
  // Pre-mutation snapshot captured by the executor's before_select_sql.
  // Keys are the columns the SELECT returned (e.g. carrier_id, status,
  // total_cost_usd). Used by the before/after diff card; reliable even
  // after server restart (the bound Booking fact may not survive).
  before?: Record<string, unknown> | null;
}

export interface QueueRow {
  ticket_id: string;
  case_id: string;
  scenario_id: string;
  rendered_card: any;
}

// SSE event payloads
export interface StageBoundEvent {
  case_id: string;
  stage: StagePayload;
  lineage: LineageEvent[];
}
export interface ReviewReadyEvent {
  case_id: string;
  ticket_id: string;
  stage: StagePayload;
  rendered_card: any;
}
export interface DecidedEvent {
  case_id: string;
  decision: DecisionKind;
  rationale: string;
  reviewer_id: string;
  follow_up: string | null;
  outcome: { headline: string; detail: string };
  closing_message: string;
  lineage: LineageEvent[];
}
export interface DataSourceRow {
  id: string;
  kind: "csv" | "sqlite" | "http" | "postgres" | "vector_store" | "neo4j";
  default: boolean;
  description: string;
  config_summary: Record<string, unknown>;
}

export interface SampleFact {
  source: string;
  ontology_type: string;
  id: string;
  title: string | null;
  summary: string | null;
  confidence: number | null;
}

export interface AutoApprovedEvent {
  case_id: string;
  guardrail_id: string;
  reason: string;
  outcome: { headline: string; detail: string };
  closing_message: string;
  lineage: LineageEvent[];
}

// =============================================================================
// Multi-scenario Outcome DAG — mirrors backend/outcome_plan.py. Returned by
// POST /api/graph/outcome-tree. Nodes/edges render on Cytoscape; `outcomes`
// is the ranked side-panel list.
// =============================================================================
export type OutcomeNodeKind = "question" | "scenario_step" | "decision" | "outcome";
export type EdgeBasis = "author" | "history" | "default" | "agent" | "structural";

export interface OutcomeNode {
  id: string;
  label: string;
  kind: OutcomeNodeKind;
  scenario_id?: string | null;
  step_index?: number | null;
  outcome_kind?: string | null;
  // Aggregate probability of reaching this node (outcome terminals only).
  probability?: number | null;
  accent: string;
}

export interface OutcomeEdge {
  id: string;
  source: string;
  target: string;
  label: string;
  probability: number;
  basis: EdgeBasis;
  rationale: string;
  accent: string;
}

export interface OutcomeSummary {
  id: string;
  label: string;
  outcome_kind?: string | null;
  scenario_id?: string | null;
  probability: number;
  // One entry per distinct root→outcome path (list of edge ids).
  path_edge_ids: string[][];
}

export interface OutcomePlan {
  question: string;
  scenario_ids: string[];
  nodes: OutcomeNode[];
  edges: OutcomeEdge[];
  outcomes: OutcomeSummary[];
  stats: Record<string, number>;
}

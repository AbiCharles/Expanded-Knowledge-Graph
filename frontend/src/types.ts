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
  suggested_prompt: string;
  // Unix-seconds freshness; backend sorts newest-first. Optional because
  // older API responses may not have it.
  mtime?: number | null;
  run_count?: number;
  last_run_at?: string | null;
  approve_count?: number;
  reject_count?: number;
  auto_count?: number;
}

export interface FactRow {
  source: string;
  ontology_type: string;
  id: string;
  uri: string | null;
  title: string | null;
  summary: string | null;
}

export interface StagePayload {
  stage: string;
  binder: string;
  facts: FactRow[];
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
  phase: Phase;
  decision_kind: string | null;
  interpreted_as: string | null;
  clarifying_question: string | null;
  confidence: number;
  candidates: ScenarioCandidate[];
  sibling_case_ids: string[];
  replay_decision: DecisionKind | null;
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
}

export interface CaseFull extends CaseSummary {
  stages: StagePayload[];
  lineage: LineageEvent[];
  scenario?: ScenarioMeta;
  closing_message?: string;
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

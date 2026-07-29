// Thin fetch wrappers. All paths are relative — Vite proxies /api → :8001 in dev.
// Every call goes through authedFetch which attaches the bearer token.

import { authedFetch } from "./auth";
import {
  CaseFull,
  CaseSummary,
  CreateCaseResponse,
  DataSourceRow,
  DecisionKind,
  OutcomePlan,
  PipelineState,
  QueueRow,
  SampleFact,
  ScenarioRow,
} from "./types";

async function jsonOrThrow<T>(resp: Response): Promise<T> {
  if (!resp.ok) {
    const body = await resp.text();
    throw new Error(`${resp.status} ${resp.statusText}: ${body}`);
  }
  return resp.json() as Promise<T>;
}

export async function listScenarios(): Promise<ScenarioRow[]> {
  return jsonOrThrow(await authedFetch("/api/scenarios"));
}

// Multi-scenario pipeline (Phase 2). `confirmPipeline` kicks off the real
// chained HITL execution; `getPipeline` returns live state for polling.
export async function confirmPipeline(
  pipelineId: string
): Promise<{ pipeline_id: string; status: string }> {
  return jsonOrThrow(
    await authedFetch(`/api/pipelines/${pipelineId}/confirm`, { method: "POST" })
  );
}

export async function getPipeline(pipelineId: string): Promise<PipelineState> {
  return jsonOrThrow(await authedFetch(`/api/pipelines/${pipelineId}`));
}

// Approve one whole pathway; the backend executes it end-to-end, auto-applying
// that path's decisions and firing each step's action (no per-step prompts).
export async function approvePath(
  pipelineId: string,
  pathId: string
): Promise<{ pipeline_id: string; status: string; path_id: string }> {
  return jsonOrThrow(
    await authedFetch(`/api/pipelines/${pipelineId}/approve-path`, {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ path_id: pathId }),
    })
  );
}

// Stitch several scenarios into one probability-weighted Outcome DAG.
// `context` can carry optional signals for the hybrid probability model,
// e.g. { reliability_score: 0.8 }.
export async function outcomeTree(
  question: string,
  scenarioIds: string[],
  context: Record<string, unknown> = {}
): Promise<OutcomePlan> {
  return jsonOrThrow(
    await authedFetch("/api/graph/outcome-tree", {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ question, scenario_ids: scenarioIds, context }),
    })
  );
}

export async function listCases(): Promise<CaseSummary[]> {
  return jsonOrThrow(await authedFetch("/api/cases"));
}

export async function getCase(caseId: string): Promise<CaseFull> {
  return jsonOrThrow(await authedFetch(`/api/cases/${caseId}`));
}

export async function createCase(prompt: string): Promise<CreateCaseResponse> {
  return jsonOrThrow(
    await authedFetch("/api/cases", {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ prompt }),
    })
  );
}

export async function confirmCase(caseId: string): Promise<void> {
  await jsonOrThrow(
    await authedFetch(`/api/cases/${caseId}/confirm`, { method: "POST" })
  );
}

export async function cancelCase(caseId: string): Promise<void> {
  await jsonOrThrow(
    await authedFetch(`/api/cases/${caseId}/cancel`, { method: "POST" })
  );
}

export async function deleteCase(caseId: string): Promise<void> {
  await jsonOrThrow(
    await authedFetch(`/api/cases/${caseId}`, { method: "DELETE" })
  );
}

export async function clearCases(phase: "complete" | "cancelled" = "complete"): Promise<{ count: number }> {
  return jsonOrThrow(
    await authedFetch(`/api/cases?phase=${phase}`, { method: "DELETE" })
  );
}

export async function relinkCase(caseId: string, scenarioId: string): Promise<{
  case_id: string;
  scenario_id: string;
  interpreted_as: string;
  clarifying_question: string;
}> {
  return jsonOrThrow(
    await authedFetch(`/api/cases/${caseId}/relink`, {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ scenario_id: scenarioId }),
    })
  );
}

export async function replayCase(
  caseId: string,
  decision: DecisionKind | null,
  opts?: { baseline?: boolean },
): Promise<{ case_id: string }> {
  return jsonOrThrow(
    await authedFetch(`/api/cases/${caseId}/replay`, {
      method: "POST",
      headers: { "content-type": "application/json" },
      // W5 / Beat 2 — when `baseline: true`, the backend auto-defaults the
      // decision to "approve" (a naive baseline reviewer without governance
      // context is most likely to greenlight), so the caller doesn't need
      // to supply one.
      body: JSON.stringify({ decision, baseline: opts?.baseline ?? false }),
    }),
  );
}

export async function listQueue(): Promise<QueueRow[]> {
  return jsonOrThrow(await authedFetch("/api/decisions/queue"));
}

// Phase 2 — read-back of the reviewer-flagged load-bearing facts for a
// closed case. Empty `highlighted_fact_refs` when the reviewer skipped,
// when the case was autonomous, or when the case predates Phase 2.
export interface CaseHighlights {
  case_id: string;
  scenario_id: string | null;
  scenario_version: number | null;
  decision_kind: string | null;
  highlighted_fact_refs: Array<HighlightedFactRef & { position: number; highlighted_at: string | null }>;
}

export async function getCaseHighlights(caseId: string): Promise<CaseHighlights> {
  return jsonOrThrow(await authedFetch(`/api/cases/${caseId}/highlights`));
}

// Phase 3a — mining endpoint over the Phase 2 captures. Admin-only.
// "For each scenario, which fact ontology types drove each decision
// kind, and how often?" Phase 3b will use the same shape as input to
// a "draft a new scenario version" admin flow.
export interface PatternRow {
  decision_kind: string;
  fact_ontology_type: string;
  case_count: number;
  share_of_decisions: number;      // % of all decisions on this scenario
  share_of_decision_kind: number;  // % of decisions of THIS kind on this scenario
  sample_fact_ids: string[];
}
export interface ScenarioPatterns {
  scenario_id: string;
  total_decided_cases: number;
  patterns: PatternRow[];
}
export interface PatternsResponse {
  generated_at_seconds: number;
  scenarios: ScenarioPatterns[];
}

export async function getInsightsPatterns(): Promise<PatternsResponse> {
  return jsonOrThrow(await authedFetch("/api/insights/patterns"));
}

// Phase 3b — promote a recurring pattern into the scenario YAML so
// future cases see an advisory chip when the trigger fires. Bumps the
// scenario version automatically (Phase 1 register).
export interface PromoteIn {
  scenario_id: string;
  decision_kind: "approve" | "reject" | "request_more_info";
  fact_ontology_type: string;
  suggested_rationale?: string;
  min_case_count?: number;
  min_share_of_kind_pct?: number;
}
export interface PromoteOut {
  scenario_id: string;
  version: number;
  pattern_id: string;
  replaced: boolean;
  stats: {
    case_count: number;
    decisions_of_kind: number;
    decisions_total: number;
    share_of_kind_pct: number;
  };
}
export async function promotePattern(args: PromoteIn): Promise<PromoteOut> {
  return jsonOrThrow(await authedFetch("/api/insights/patterns/promote", {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify(args),
  }));
}

export async function demotePattern(args: { scenario_id: string; pattern_id: string }): Promise<{
  scenario_id: string;
  version: number;
  pattern_id: string;
  remaining_patterns: number;
}> {
  return jsonOrThrow(await authedFetch("/api/insights/patterns/demote", {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify(args),
  }));
}

// Phase 2 — reviewer-flagged load-bearing fact ref. Matches the backend
// HighlightedFactRef Pydantic shape; the (source, ontology_type, id)
// triple is the same identity used in KnowledgeRef / FactRow.
export interface HighlightedFactRef {
  source: string;
  ontology_type: string;
  id: string;
  title?: string | null;
}

export async function postDecision(
  ticketId: string,
  args: {
    decision: DecisionKind;
    reviewer_id: string;
    rationale: string;
    follow_up?: string | null;
    highlighted_fact_refs?: HighlightedFactRef[];
  }
): Promise<void> {
  await jsonOrThrow(
    await authedFetch(`/api/decisions/${ticketId}`, {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify(args),
    })
  );
}

// =============================================================================
// Data sources
// =============================================================================
export async function listDataSources(): Promise<DataSourceRow[]> {
  return jsonOrThrow(await authedFetch("/api/data-sources"));
}

export async function testDataSource(id: string): Promise<{ ok: boolean; sample_facts: SampleFact[] }> {
  return jsonOrThrow(
    await authedFetch(`/api/data-sources/${id}/test`, { method: "POST" })
  );
}

export async function deleteDataSource(id: string): Promise<void> {
  await jsonOrThrow(
    await authedFetch(`/api/data-sources/${id}`, { method: "DELETE" })
  );
}

export async function uploadCsv(args: {
  file: File;
  id: string;
  ontology_type: string;
  id_field: string;
  title_field: string;
  summary_template: string;
  description?: string;
}): Promise<{ id: string }> {
  const fd = new FormData();
  fd.append("file", args.file);
  fd.append("id", args.id);
  fd.append("ontology_type", args.ontology_type);
  fd.append("id_field", args.id_field);
  fd.append("title_field", args.title_field);
  fd.append("summary_template", args.summary_template);
  if (args.description) fd.append("description", args.description);
  const resp = await authedFetch("/api/data-sources/upload", { method: "POST", body: fd });
  return jsonOrThrow(resp);
}

export async function addDataSource(args: {
  id: string;
  kind: "sqlite" | "http" | "postgres" | "vector_store" | "neo4j";
  description?: string;
  config: Record<string, unknown>;
}): Promise<{ id: string }> {
  return jsonOrThrow(
    await authedFetch("/api/data-sources", {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify(args),
    })
  );
}

export async function testPostgres(dsn: string): Promise<{ ok: boolean; message: string }> {
  return jsonOrThrow(
    await authedFetch("/api/data-sources/test-postgres", {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ dsn }),
    })
  );
}

export async function testNeo4j(args: {
  uri: string;
  user?: string;
  password?: string;
  database?: string;
}): Promise<{ ok: boolean; message: string }> {
  return jsonOrThrow(
    await authedFetch("/api/data-sources/test-neo4j", {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify(args),
    })
  );
}

export async function runCypher(
  sourceId: string,
  args: { cypher: string; params?: Record<string, unknown>; limit?: number }
): Promise<RunQueryResult> {
  const resp = await authedFetch(`/api/data-sources/${sourceId}/run-cypher`, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({
      cypher: args.cypher,
      params: args.params ?? {},
      limit: args.limit ?? 50,
    }),
  });
  if (!resp.ok) {
    const text = await resp.text();
    return { ok: false, error: `${resp.status}: ${text}` };
  }
  return resp.json();
}

export interface RunQueryResult {
  ok: boolean;
  columns?: string[];
  rows?: unknown[][];
  limit?: number;
  error?: string;
}

export async function runQuery(
  sourceId: string,
  args: { sql: string; params?: Record<string, unknown>; limit?: number }
): Promise<RunQueryResult> {
  const resp = await authedFetch(`/api/data-sources/${sourceId}/run-query`, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({ sql: args.sql, params: args.params ?? {}, limit: args.limit ?? 50 }),
  });
  if (!resp.ok) {
    const text = await resp.text();
    return { ok: false, error: `${resp.status}: ${text}` };
  }
  return resp.json();
}

export interface SaveScenarioArgs {
  scenario_id?: string;
  title: string;
  description?: string;
  data_source: string;
  ontology_type?: string;
  sql: string;
  params?: Record<string, unknown>;
  match_keywords?: string[];
  clarifying_question?: string;
  closing_message?: string;
  suggested_prompt?: string;
}

export async function saveScenario(args: SaveScenarioArgs): Promise<{ scenario_id: string }> {
  return jsonOrThrow(
    await authedFetch("/api/scenarios", {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify(args),
    })
  );
}

export async function deleteScenario(scenarioId: string): Promise<void> {
  await jsonOrThrow(
    await authedFetch(`/api/scenarios/${scenarioId}`, { method: "DELETE" })
  );
}

export interface EditScenarioArgs {
  title?: string;
  match_keywords?: string[];
  interpreted_as?: string;
  clarifying_question?: string;
  suggested_prompt?: string;
  description?: string;
}

export interface EditScenarioResult {
  scenario_id: string;
  updated: number;
  version: number;
}

export async function editScenario(
  scenarioId: string,
  args: EditScenarioArgs,
): Promise<EditScenarioResult> {
  return jsonOrThrow(
    await authedFetch(`/api/scenarios/${scenarioId}`, {
      method: "PATCH",
      headers: { "content-type": "application/json" },
      body: JSON.stringify(args),
    })
  );
}

export async function getScenario(scenarioId: string): Promise<any> {
  return jsonOrThrow(
    await authedFetch(`/api/scenarios/${scenarioId}`)
  );
}

// Full parsed scenario dict (stages, ontology_queries, outcomes,
// closing_messages, rationale_reasons, …) — used by the read-only
// Case-spec modal. The non-?full=1 endpoint returns only the editable
// subset the editor modal needs. Pass `version` to fetch a specific
// historical snapshot (always full content).
export async function getScenarioFull(
  scenarioId: string,
  opts: { version?: number } = {},
): Promise<any> {
  const qs = opts.version != null
    ? `?version=${opts.version}`
    : `?full=1`;
  return jsonOrThrow(
    await authedFetch(`/api/scenarios/${scenarioId}${qs}`)
  );
}

export interface ScenarioVersionRow {
  version: number;
  saved_at: number | null;  // unix seconds
  title: string;
}

// Every saved version of a scenario, newest-first. Used by
// ScenarioVersionsModal to render the history list.
export async function listScenarioVersions(
  scenarioId: string,
): Promise<ScenarioVersionRow[]> {
  return jsonOrThrow(
    await authedFetch(`/api/scenarios/${scenarioId}/versions`)
  );
}

export interface MetricsSummary {
  scope: string;
  totals: { all_cases: number; complete: number; in_progress: number };
  cases_by_status: { phase: string; count: number }[];
  decisions_by_scenario: { scenario_id: string; approve: number; reject: number; request_more_info: number; auto_execute: number; in_progress: number }[];
  cases_per_day: { date: string; count: number }[];
  top_rejection_reasons: { reason: string; count: number }[];
}

export async function getMetrics(): Promise<MetricsSummary> {
  return jsonOrThrow(await authedFetch("/api/metrics/summary"));
}

export interface AutofillSuggestion {
  source: "llm" | "fallback";
  title: string;
  match_keywords: string[];
  clarifying_question: string;
  suggested_prompt: string;
}

export async function autofillScenario(args: {
  title?: string;
  data_source: string;
  sql: string;
  sample_rows?: unknown[];
  ontology_type?: string;
}): Promise<AutofillSuggestion> {
  return jsonOrThrow(
    await authedFetch("/api/scenarios/autofill", {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify(args),
    })
  );
}

// =============================================================================
// Ontologies (Phase 2)
// =============================================================================
export interface OntologySummary {
  id: string;
  title: string;
  namespace: string | null;
  class_count: number;
  has_mapping: boolean;
}

export interface OntologyAttribute {
  name: string;
  type: string;
  identifier: boolean;
  required: boolean;
  description: string | null;
}

export interface OntologyRelation {
  name: string;
  target: string;
  cardinality: string;
  inverse: string | null;
  description: string | null;
}

export interface OntologyClassDetail {
  name: string;
  description: string | null;
  attributes: OntologyAttribute[];
  relations: OntologyRelation[];
  identifier_attribute: string | null;
}

export interface SourceBinding {
  data_source: string;
  identifier_column: string;
  attribute_map: Record<string, string>;
  // Phase 3.C: kind-specific binding hints. Connectors prefer these
  // over anything in the source spec.
  table?: string | null;
  query_template?: string | null;
  http_path_template?: string | null;
  confidence: number | null;
  suggested_by: string | null;
  confirmed_by: string | null;
  confirmed_at: string | null;
  notes: string | null;
}

export interface ClassMapping {
  sources: SourceBinding[];
  relations: Record<string, unknown>;
}

export interface MappingDoc {
  ontology_id: string;
  mappings: Record<string, ClassMapping>;
}

export interface ColumnInfo {
  name: string;
  type: string;
  nullable: boolean | null;
  sample_values: unknown[];
}

export interface TableInfo {
  name: string;
  columns: ColumnInfo[];
  sample_row_count: number;
}

export interface SourceSchema {
  source_id: string;
  kind: string;
  tables: TableInfo[];
  note: string | null;
}

export interface SuggestMappingsResponse {
  ontology_id: string;
  llm: string;
  schemas: SourceSchema[];
  mapping: MappingDoc;
}

export async function listOntologies(): Promise<OntologySummary[]> {
  return jsonOrThrow(await authedFetch("/api/ontologies"));
}

export async function getOntologyClasses(id: string): Promise<OntologyClassDetail[]> {
  return jsonOrThrow(await authedFetch(`/api/ontologies/${id}/classes`));
}

export async function uploadOntologyFile(file: File): Promise<{ id: string; title: string; class_count: number }> {
  const fd = new FormData();
  fd.append("file", file);
  return jsonOrThrow(
    await authedFetch("/api/ontologies", { method: "POST", body: fd })
  );
}

export async function uploadOntologyRaw(args: { content?: string; document?: unknown }): Promise<{ id: string; title: string; class_count: number }> {
  return jsonOrThrow(
    await authedFetch("/api/ontologies/raw", {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify(args),
    })
  );
}

export async function deleteOntology(id: string): Promise<void> {
  await jsonOrThrow(
    await authedFetch(`/api/ontologies/${id}`, { method: "DELETE" })
  );
}

export async function getMappings(id: string): Promise<MappingDoc> {
  return jsonOrThrow(await authedFetch(`/api/ontologies/${id}/mappings`));
}

export async function putMappings(id: string, mapping: MappingDoc): Promise<void> {
  await jsonOrThrow(
    await authedFetch(`/api/ontologies/${id}/mappings`, {
      method: "PUT",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ document: mapping }),
    })
  );
}

export async function suggestMappings(
  id: string,
  data_source_ids: string[]
): Promise<SuggestMappingsResponse> {
  return jsonOrThrow(
    await authedFetch(`/api/ontologies/${id}/mappings/suggest`, {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ data_source_ids }),
    })
  );
}

// Phase 3.C: per-class chip generation, opt-in. Replaces the old
// per-source SC-AUTO-* auto-generation.
export async function generateLookupChip(
  ontologyId: string,
  className: string
): Promise<{ scenario_id: string; title: string; binding_count: number }> {
  return jsonOrThrow(
    await authedFetch(
      `/api/ontologies/${ontologyId}/classes/${className}/scenario`,
      { method: "POST" }
    )
  );
}

export async function removeLookupChip(
  ontologyId: string,
  className: string
): Promise<void> {
  await jsonOrThrow(
    await authedFetch(
      `/api/ontologies/${ontologyId}/classes/${className}/scenario`,
      { method: "DELETE" }
    )
  );
}

export async function getDataSourceSchema(id: string): Promise<SourceSchema> {
  return jsonOrThrow(await authedFetch(`/api/data-sources/${id}/schema`));
}

export interface OntologyQueryFact {
  source: string;
  ontology_type: string;
  id: string;
  title: string | null;
  summary: string | null;
  via_ontology: string | null;
  via_source_binding: string | null;
}

export interface OntologyQueryResult {
  ontology: string;
  class: string;
  where: Record<string, unknown>;
  purpose: string;
  fact_count: number;
  facts: OntologyQueryFact[];
  llm?: string;
}

export async function runStructuredOntologyQuery(args: {
  ontology: string;
  class: string;
  where?: Record<string, unknown>;
  include_relations?: string[];
  max_results?: number;
}): Promise<OntologyQueryResult> {
  return jsonOrThrow(
    await authedFetch("/api/ontology-query/structured", {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify(args),
    })
  );
}

export async function runNLOntologyQuery(args: {
  ontology: string;
  prompt: string;
  max_results?: number;
}): Promise<OntologyQueryResult> {
  return jsonOrThrow(
    await authedFetch("/api/ontology-query", {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify(args),
    })
  );
}

// =============================================================================
// Write actions (Phase 3.E)
// =============================================================================
export interface ActionSummary {
  id: string;
  title: string;
  description: string | null;
  hitl: boolean;
  executor_kind: string;
  target_source: string | null;
  argument_count: number;
  default: boolean;
  // Reversibility marker (W3, deck Beat 4). Drives the LineagePanel
  // Compensate button — only `compensatable` actions surface the
  // control when they've fired successfully.
  reversibility_class?: "idempotent" | "compensatable" | "irreversible";
}

export async function listActions(): Promise<ActionSummary[]> {
  return jsonOrThrow(await authedFetch("/api/actions"));
}

export async function getAction(id: string): Promise<unknown> {
  return jsonOrThrow(await authedFetch(`/api/actions/${id}`));
}

// Reverse a previously-executed compensatable action on this case.
// Backend looks up case.execution_result, runs the action's compensation
// executor, and emits an action.compensated lineage event.
export async function compensateCase(
  caseId: string,
): Promise<{ case_id: string; action_id: string; ok: boolean; detail: string }> {
  return jsonOrThrow(
    await authedFetch(`/api/cases/${caseId}/compensate`, { method: "POST" }),
  );
}

// W1 / Beat 3 — case revisioning.
export interface ReviseTrigger {
  id: string;
  label: string;
  explainer: string;
}

export interface ReviseTriggersResponse {
  case_id: string;
  scenario_id: string | null;
  triggers: ReviseTrigger[];
  supports_generic_refresh: boolean;
}

export async function listReviseTriggers(
  caseId: string,
): Promise<ReviseTriggersResponse> {
  return jsonOrThrow(
    await authedFetch(`/api/cases/${caseId}/revise/triggers`),
  );
}

export interface ReviseResponse {
  case_id: string;
  revision_no: number;
  trigger_label?: string;
  new_decision?: string;
  no_change?: boolean;
  detail?: string;
  // Generic-refresh path returns how many facts were re-checked across
  // the proposal + review stages. Useful for surfacing concrete result
  // text to the operator ("Re-ran 12 facts · no material change").
  facts_checked?: number;
}

export async function reviseCase(
  caseId: string,
  triggerId: string,
): Promise<ReviseResponse> {
  return jsonOrThrow(
    await authedFetch(`/api/cases/${caseId}/revise`, {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ trigger_id: triggerId }),
    }),
  );
}

export async function uploadActionRaw(args: {
  content?: string;
  document?: unknown;
}): Promise<{ id: string; title: string }> {
  return jsonOrThrow(
    await authedFetch("/api/actions/raw", {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify(args),
    })
  );
}

export async function deleteAction(id: string): Promise<void> {
  await jsonOrThrow(
    await authedFetch(`/api/actions/${id}`, { method: "DELETE" })
  );
}

// =============================================================================
// Graph subgraph (Neo4j) — backs the GraphPanel viz in the envelope.
// =============================================================================
export interface GraphNode {
  id: string;
  label: string;
  type: string;
  accent?: "" | "anchor" | "risk" | "risk_path" | "alt";
}
export interface GraphEdge {
  source: string;
  target: string;
  type: string;
  accent?: "" | "risk_path";
}
export interface SubgraphResponse {
  nodes: GraphNode[];
  edges: GraphEdge[];
  stats: Record<string, number>;
}

export async function getSupplierSubgraph(
  supplier_id: string,
  depth = 4,
): Promise<SubgraphResponse> {
  return jsonOrThrow(
    await authedFetch("/api/graph/subgraph", {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ supplier_id, depth }),
    })
  );
}

// =============================================================================
// Agent orchestrator companion service
// =============================================================================
// Lives at a separate origin (VITE_AGENT_ORCHESTRATOR_URL) — defaults to
// localhost:8002 for dev, swap via env at build time for Fly.

const AGENT_ORCH_URL =
  (import.meta.env.VITE_AGENT_ORCHESTRATOR_URL as string | undefined) ||
  "http://127.0.0.1:8002";

export interface AgentEvent {
  type:
    | "news_source_detected"
    | "risk_detected"
    | "investigation_started"
    | "agent_thinking"
    | "fabric_query"
    | "fabric_response"
    | "tier1_buyers_found"
    | "programs_at_risk_identified"
    | "alternates_surfaced"
    | "subagents_spawned"
    | "subagent_started"
    | "subagent_progress"
    | "subagent_completed"
    | "run_completed"
    | "error";
  agent_id: string;
  at: string;
  payload: Record<string, any>;
  fabric_link?: string | null;
}

export async function agentRunStart(): Promise<{ run_id: string }> {
  const resp = await fetch(`${AGENT_ORCH_URL}/api/agent-run/start`, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: "{}",
  });
  if (!resp.ok) throw new Error(`agent-run/start ${resp.status}`);
  return await resp.json();
}

// EventSource-based stream. Returns the underlying EventSource so the
// caller can close it on unmount. Each named event lands in onEvent
// already JSON-parsed; the `done` event triggers onDone.
export function agentRunStream(
  runId: string,
  onEvent: (ev: AgentEvent) => void,
  onDone: () => void,
  onError: (err: any) => void,
): EventSource {
  const es = new EventSource(`${AGENT_ORCH_URL}/api/agent-run/${runId}/events`);
  const types: AgentEvent["type"][] = [
    "news_source_detected",
    "risk_detected",
    "investigation_started",
    "agent_thinking",
    "fabric_query",
    "fabric_response",
    "tier1_buyers_found",
    "programs_at_risk_identified",
    "alternates_surfaced",
    "subagents_spawned",
    "subagent_started",
    "subagent_progress",
    "subagent_completed",
    "run_completed",
    "error",
  ];
  for (const t of types) {
    es.addEventListener(t, (e: MessageEvent) => {
      try {
        onEvent(JSON.parse(e.data) as AgentEvent);
      } catch (err) {
        onError(err);
      }
    });
  }
  es.addEventListener("done", () => {
    onDone();
    es.close();
  });
  es.onerror = (err) => {
    onError(err);
    es.close();
  };
  return es;
}

// =============================================================================
// W8 — Aeronova findings drop-box. The agent orchestrator POSTs these
// after each run; the fabric's pathways graph overlays them on the
// terminal nodes (PM names on Program nodes, ✓/⚠ outreach status on
// alternate-supplier nodes).
// =============================================================================
export interface AeronovaFindings {
  program_managers: Record<string, string>;  // program_id → "name @ Aeronova (Program)"
  alternate_outreach: {
    primary: { supplier_id: string; name: string; via?: string }[];
    blocked: { supplier_id: string; name: string; via?: string; reason?: string }[];
  };
  posted_at?: string;
  run_id?: string;
}

export async function getAeronovaFindings(): Promise<AeronovaFindings | null> {
  const resp = await fetch("/api/aeronova/findings");
  if (!resp.ok) return null;
  const body = await resp.json();
  return body || null;
}

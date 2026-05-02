// Thin fetch wrappers. All paths are relative — Vite proxies /api → :8000 in dev.

import {
  CaseFull,
  CaseSummary,
  CreateCaseResponse,
  DataSourceRow,
  DecisionKind,
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
  return jsonOrThrow(await fetch("/api/scenarios"));
}

export async function listCases(): Promise<CaseSummary[]> {
  return jsonOrThrow(await fetch("/api/cases"));
}

export async function getCase(caseId: string): Promise<CaseFull> {
  return jsonOrThrow(await fetch(`/api/cases/${caseId}`));
}

export async function createCase(prompt: string): Promise<CreateCaseResponse> {
  return jsonOrThrow(
    await fetch("/api/cases", {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ prompt }),
    })
  );
}

export async function confirmCase(caseId: string): Promise<void> {
  await jsonOrThrow(
    await fetch(`/api/cases/${caseId}/confirm`, { method: "POST" })
  );
}

export async function cancelCase(caseId: string): Promise<void> {
  await jsonOrThrow(
    await fetch(`/api/cases/${caseId}/cancel`, { method: "POST" })
  );
}

export async function deleteCase(caseId: string): Promise<void> {
  await jsonOrThrow(
    await fetch(`/api/cases/${caseId}`, { method: "DELETE" })
  );
}

export async function clearCases(phase: "complete" | "cancelled" = "complete"): Promise<{ count: number }> {
  return jsonOrThrow(
    await fetch(`/api/cases?phase=${phase}`, { method: "DELETE" })
  );
}

export async function relinkCase(caseId: string, scenarioId: string): Promise<{
  case_id: string;
  scenario_id: string;
  interpreted_as: string;
  clarifying_question: string;
}> {
  return jsonOrThrow(
    await fetch(`/api/cases/${caseId}/relink`, {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ scenario_id: scenarioId }),
    })
  );
}

export async function replayCase(caseId: string, decision: DecisionKind): Promise<{ case_id: string }> {
  return jsonOrThrow(
    await fetch(`/api/cases/${caseId}/replay`, {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ decision }),
    })
  );
}

export async function listQueue(): Promise<QueueRow[]> {
  return jsonOrThrow(await fetch("/api/decisions/queue"));
}

export async function postDecision(
  ticketId: string,
  args: { decision: DecisionKind; reviewer_id: string; rationale: string; follow_up?: string | null }
): Promise<void> {
  await jsonOrThrow(
    await fetch(`/api/decisions/${ticketId}`, {
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
  return jsonOrThrow(await fetch("/api/data-sources"));
}

export async function testDataSource(id: string): Promise<{ ok: boolean; sample_facts: SampleFact[] }> {
  return jsonOrThrow(
    await fetch(`/api/data-sources/${id}/test`, { method: "POST" })
  );
}

export async function deleteDataSource(id: string): Promise<void> {
  await jsonOrThrow(
    await fetch(`/api/data-sources/${id}`, { method: "DELETE" })
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
  const resp = await fetch("/api/data-sources/upload", { method: "POST", body: fd });
  return jsonOrThrow(resp);
}

export async function addDataSource(args: {
  id: string;
  kind: "sqlite" | "http" | "postgres" | "vector_store";
  description?: string;
  config: Record<string, unknown>;
}): Promise<{ id: string }> {
  return jsonOrThrow(
    await fetch("/api/data-sources", {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify(args),
    })
  );
}

export async function testPostgres(dsn: string): Promise<{ ok: boolean; message: string }> {
  return jsonOrThrow(
    await fetch("/api/data-sources/test-postgres", {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ dsn }),
    })
  );
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
  const resp = await fetch(`/api/data-sources/${sourceId}/run-query`, {
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
    await fetch("/api/scenarios", {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify(args),
    })
  );
}

export async function deleteScenario(scenarioId: string): Promise<void> {
  await jsonOrThrow(
    await fetch(`/api/scenarios/${scenarioId}`, { method: "DELETE" })
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

export async function editScenario(scenarioId: string, args: EditScenarioArgs): Promise<void> {
  await jsonOrThrow(
    await fetch(`/api/scenarios/${scenarioId}`, {
      method: "PATCH",
      headers: { "content-type": "application/json" },
      body: JSON.stringify(args),
    })
  );
}

export async function getScenario(scenarioId: string): Promise<any> {
  return jsonOrThrow(
    await fetch(`/api/scenarios/${scenarioId}`)
  );
}

export interface AutofillSuggestion {
  source: "llm" | "fallback";
  match_keywords: string[];
  clarifying_question: string;
  suggested_prompt: string;
}

export async function autofillScenario(args: {
  title: string;
  data_source: string;
  sql: string;
  sample_rows?: unknown[];
  ontology_type?: string;
}): Promise<AutofillSuggestion> {
  return jsonOrThrow(
    await fetch("/api/scenarios/autofill", {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify(args),
    })
  );
}

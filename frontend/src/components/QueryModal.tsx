import { useState } from "react";
import * as api from "../api";
import { DataSourceRow } from "../types";

type ParamRow = { key: string; value: string };

export function QueryModal({
  source,
  onClose,
  onScenarioSaved,
}: {
  source: DataSourceRow;
  onClose: () => void;
  onScenarioSaved?: () => void;
}) {
  const [sql, setSql] = useState(starterSqlFor(source));
  const [params, setParams] = useState<ParamRow[]>(starterParamsFor(source));
  const [limit, setLimit] = useState(50);
  const [busy, setBusy] = useState(false);
  const [result, setResult] = useState<api.RunQueryResult | null>(null);
  const [saveOpen, setSaveOpen] = useState(false);
  const [savedAs, setSavedAs] = useState<string | null>(null);

  const run = async () => {
    setBusy(true);
    setResult(null);
    try {
      const obj: Record<string, unknown> = {};
      for (const p of params) {
        if (p.key.trim()) obj[p.key.trim()] = p.value;
      }
      const r = await api.runQuery(source.id, { sql, params: obj, limit });
      setResult(r);
    } finally {
      setBusy(false);
    }
  };

  const updateParam = (i: number, patch: Partial<ParamRow>) =>
    setParams((rows) => rows.map((r, idx) => (idx === i ? { ...r, ...patch } : r)));
  const addParam = () => setParams((r) => [...r, { key: "", value: "" }]);
  const removeParam = (i: number) => setParams((r) => r.filter((_, idx) => idx !== i));

  return (
    <div
      className="modal-backdrop layer-2"
      onClick={(e) => e.target === e.currentTarget && onClose()}
    >
      <div className="query-modal">
        <div className="ds-header">
          <div>
            <div className="ds-eyebrow">Query playground</div>
            <div className="ds-title">
              {source.id} <span className={`ds-kind ds-kind-${source.kind}`}>{source.kind}</span>
            </div>
          </div>
          <button className="teams-close" onClick={onClose}>
            ×
          </button>
        </div>

        <div className="query-body">
          <label className="query-section-label">SQL</label>
          <textarea
            className="query-sql"
            value={sql}
            onChange={(e) => setSql(e.target.value)}
            placeholder="SELECT id, title, summary FROM table WHERE col = :name LIMIT :max_results"
            rows={8}
            spellCheck={false}
          />

          <div className="query-controls-row">
            <div className="query-params">
              <label className="query-section-label">Named params (optional)</label>
              {params.map((p, i) => (
                <div key={i} className="query-param-row">
                  <input
                    placeholder="name"
                    value={p.key}
                    onChange={(e) => updateParam(i, { key: e.target.value })}
                  />
                  <span className="query-param-sep">=</span>
                  <input
                    placeholder="value"
                    value={p.value}
                    onChange={(e) => updateParam(i, { value: e.target.value })}
                  />
                  <button className="query-param-x" onClick={() => removeParam(i)} title="remove">
                    ×
                  </button>
                </div>
              ))}
              <button className="query-add-param" onClick={addParam}>
                + Add param
              </button>
              <div className="query-hint">
                <code>:max_results</code> is auto-bound to your limit if you don't set it.
              </div>
            </div>
            <div className="query-limit-block">
              <label className="query-section-label">Limit</label>
              <input
                type="number"
                min={1}
                max={100}
                className="query-limit"
                value={limit}
                onChange={(e) => setLimit(parseInt(e.target.value || "50", 10))}
              />
            </div>
          </div>

          <div className="query-actions">
            <button className="primary" onClick={run} disabled={busy || !sql.trim()}>
              {busy ? "Running…" : "Run query"}
            </button>
          </div>

          {result && <ResultPanel result={result} />}

          {savedAs && (
            <div className="query-saved-banner">
              ✓ Saved as scenario <code>{savedAs}</code>. The chip is in the operator console — close this modal to use it.
            </div>
          )}

          {result?.ok && !saveOpen && !savedAs && (
            <button
              className="query-save-toggle"
              onClick={() => setSaveOpen(true)}
            >
              + Save this query as a scenario
            </button>
          )}

          {saveOpen && !savedAs && (
            <SaveScenarioForm
              source={source}
              sql={sql}
              params={params}
              result={result}
              onCancel={() => setSaveOpen(false)}
              onSaved={(sid) => {
                setSavedAs(sid);
                setSaveOpen(false);
                onScenarioSaved?.();
              }}
            />
          )}
        </div>
      </div>
    </div>
  );
}

// =============================================================================
// Save-as-scenario sub-form
// =============================================================================
function SaveScenarioForm({
  source,
  sql,
  params,
  result,
  onCancel,
  onSaved,
}: {
  source: DataSourceRow;
  sql: string;
  params: ParamRow[];
  result: api.RunQueryResult | null;
  onCancel: () => void;
  onSaved: (scenarioId: string) => void;
}) {
  const [title, setTitle] = useState("");
  const [keywords, setKeywords] = useState("");
  const [clarifier, setClarifier] = useState("");
  const [prompt, setPrompt] = useState("");
  const [ontology, setOntology] = useState(
    (source.config_summary?.ontology_type as string | undefined) ||
    (source.config_summary?.ontology_types as string[] | undefined)?.[0] ||
    "Record"
  );
  const [busy, setBusy] = useState(false);
  const [autofilling, setAutofilling] = useState(false);
  const [autofillSource, setAutofillSource] = useState<"llm" | "fallback" | null>(null);
  const [error, setError] = useState<string | null>(null);

  const onAutofill = async () => {
    setAutofilling(true);
    setError(null);
    try {
      const sampleRows = (result?.rows || []).slice(0, 3).map((row) =>
        Object.fromEntries((result?.columns || []).map((c, i) => [c, row[i]]))
      );
      const r = await api.autofillScenario({
        title: title.trim() || undefined,
        data_source: source.id,
        sql,
        sample_rows: sampleRows,
        ontology_type: ontology,
      });
      // Only overwrite the title if the operator left it blank — once they've
      // typed something they presumably want it kept.
      if (!title.trim()) setTitle(r.title);
      setKeywords(r.match_keywords.join(", "));
      setClarifier(r.clarifying_question);
      setPrompt(r.suggested_prompt);
      setAutofillSource(r.source);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setAutofilling(false);
    }
  };

  const submit = async () => {
    if (!title.trim()) {
      setError("title is required");
      return;
    }
    setBusy(true);
    setError(null);
    try {
      const obj: Record<string, unknown> = {};
      for (const p of params) {
        if (p.key.trim()) obj[p.key.trim()] = p.value;
      }
      const result = await api.saveScenario({
        title: title.trim(),
        data_source: source.id,
        ontology_type: ontology,
        sql,
        params: obj,
        match_keywords: keywords
          .split(",")
          .map((k) => k.trim())
          .filter(Boolean),
        clarifying_question: clarifier.trim() || undefined,
        suggested_prompt: prompt.trim() || undefined,
      });
      onSaved(result.scenario_id);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="query-save-form">
      <div className="query-save-header">
        Save as scenario
        <button
          className="query-autofill-btn"
          onClick={onAutofill}
          disabled={autofilling || !sql.trim()}
          title={
            !sql.trim()
              ? "Run a query first — the AI uses the SQL + sample rows to suggest fields"
              : "Ask the AI to suggest a title, keywords, clarifying question, and chip prompt"
          }
        >
          {autofilling ? "Suggesting…" : "✨ Suggest with AI"}
        </button>
      </div>
      {autofillSource && (
        <div className="query-autofill-badge">
          {autofillSource === "llm"
            ? "✓ Filled by LLM — review and edit before saving."
            : "⚠ No LLM credentials — used keyword-derived defaults. Edit before saving."}
        </div>
      )}
      <label>Title (required)
        <input
          value={title}
          onChange={(e) => setTitle(e.target.value)}
          placeholder="e.g. Outcome counts by scenario"
        />
      </label>
      <label>Suggested prompt (chip text)
        <input
          value={prompt}
          onChange={(e) => setPrompt(e.target.value)}
          placeholder="e.g. Show me outcome counts"
        />
      </label>
      <label>Match keywords (comma-separated)
        <input
          value={keywords}
          onChange={(e) => setKeywords(e.target.value)}
          placeholder="e.g. outcome, count, stats"
        />
      </label>
      <label>Clarifying question (optional)
        <textarea
          value={clarifier}
          onChange={(e) => setClarifier(e.target.value)}
          rows={2}
          placeholder="What the agent asks before running. HTML allowed."
        />
      </label>
      <label>Ontology type
        <input value={ontology} onChange={(e) => setOntology(e.target.value)} />
      </label>
      <div className="query-save-help">
        The saved scenario is autonomous (read-only · no human review). It runs
        the SQL above against <code>{source.id}</code>. Edit the SQL or params
        in the playground first, then save.{" "}
        <a
          href="#"
          onClick={(e) => {
            e.preventDefault();
            window.dispatchEvent(new CustomEvent("open-scenarios-help"));
          }}
        >
          Field reference →
        </a>
      </div>
      {error && <div className="query-save-error">{error}</div>}
      <div className="query-save-actions">
        <button onClick={onCancel}>Cancel</button>
        <button className="primary" disabled={busy || !title.trim()} onClick={submit}>
          {busy ? "Saving…" : "Save scenario"}
        </button>
      </div>
    </div>
  );
}

function ResultPanel({ result }: { result: api.RunQueryResult }) {
  if (!result.ok) {
    return (
      <div className="query-result query-result-error">
        <strong>Error</strong>
        <pre>{result.error}</pre>
      </div>
    );
  }
  const cols = result.columns ?? [];
  const rows = result.rows ?? [];
  return (
    <div className="query-result">
      <div className="query-result-meta">
        {rows.length} row{rows.length === 1 ? "" : "s"} · {cols.length} column{cols.length === 1 ? "" : "s"}
        {typeof result.limit === "number" && rows.length === result.limit && ` · capped at limit`}
      </div>
      {rows.length === 0 ? (
        <div className="query-result-empty">No rows returned.</div>
      ) : (
        <div className="query-result-table-wrap">
          <table className="query-result-table">
            <thead>
              <tr>{cols.map((c) => <th key={c}>{c}</th>)}</tr>
            </thead>
            <tbody>
              {rows.map((r, i) => (
                <tr key={i}>
                  {r.map((v, j) => (
                    <td key={j} title={String(v ?? "")}>
                      {v == null ? <span className="query-null">NULL</span> : String(v)}
                    </td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}

// =============================================================================
// Starter content per source — gives the user something runnable on first open.
//   * For governance_sqlite specifically (the seeded demo store), pre-fill an
//     aggregation that returns real data.
//   * For any other SQLite source, list the tables so the user can see what's
//     available before writing real SQL.
//   * For Postgres, the same "list tables" trick using information_schema.
// =============================================================================
function starterSqlFor(source: DataSourceRow): string {
  if (source.kind === "sqlite") {
    // Schema introspection — one row per table, comma-list of columns with types.
    return [
      "-- Tables and their columns. Pick one and write real SQL against it.",
      "SELECT m.name AS table_name,",
      "       GROUP_CONCAT(p.name || ' (' || p.type || ')', ', ') AS columns",
      "FROM sqlite_master m, pragma_table_info(m.name) p",
      "WHERE m.type = 'table'",
      "GROUP BY m.name",
      "ORDER BY m.name",
      "LIMIT :max_results",
    ].join("\n");
  }
  if (source.kind === "postgres") {
    return [
      "-- Tables and their columns. Pick one and write real SQL against it.",
      "SELECT table_name,",
      "       string_agg(column_name || ' (' || data_type || ')', ', ' ORDER BY ordinal_position) AS columns",
      "FROM information_schema.columns",
      "WHERE table_schema = 'public'",
      "GROUP BY table_name",
      "ORDER BY table_name",
      "LIMIT :max_results",
    ].join("\n");
  }
  return "";
}

function starterParamsFor(_source: DataSourceRow): ParamRow[] {
  return [{ key: "", value: "" }];
}

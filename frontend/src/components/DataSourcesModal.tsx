import { useEffect, useState } from "react";
import * as api from "../api";
import { DataSourceRow, SampleFact } from "../types";
import { QueryModal } from "./QueryModal";

type AddMode = null | "csv" | "http" | "sqlite" | "postgres" | "vector";

export function DataSourcesModal({
  onClose,
  onScenariosChanged,
}: {
  onClose: () => void;
  onScenariosChanged?: () => void;
}) {
  const [rows, setRows] = useState<DataSourceRow[]>([]);
  const [addMode, setAddMode] = useState<AddMode>(null);
  const [samples, setSamples] = useState<Record<string, SampleFact[]>>({});
  const [loadingId, setLoadingId] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [queryOpenFor, setQueryOpenFor] = useState<DataSourceRow | null>(null);

  const refresh = async () => {
    try {
      setRows(await api.listDataSources());
    } catch (e) {
      setError((e as Error).message);
    }
  };
  useEffect(() => {
    refresh();
  }, []);

  const onTest = async (id: string) => {
    setLoadingId(id);
    setError(null);
    try {
      const result = await api.testDataSource(id);
      setSamples((s) => ({ ...s, [id]: result.sample_facts }));
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setLoadingId(null);
    }
  };

  const onDelete = async (id: string) => {
    if (!confirm(`Remove data source "${id}"?`)) return;
    try {
      await api.deleteDataSource(id);
      await refresh();
      // Removing a source also tears down its SC-AUTO-* scenario.
      onScenariosChanged?.();
    } catch (e) {
      setError((e as Error).message);
    }
  };

  return (
    <div
      className="modal-backdrop"
      onClick={(e) => e.target === e.currentTarget && onClose()}
    >
      <div className="ds-modal">
        <div className="ds-header">
          <div>
            <div className="ds-eyebrow">Data sources</div>
            <div className="ds-title">Connections & uploads</div>
          </div>
          <button className="teams-close" onClick={onClose}>
            ×
          </button>
        </div>

        {error && <div className="ds-error">{error}</div>}

        {addMode === null && (
          <>
            <div className="ds-body">
              {rows.map((r) => (
                <div key={r.id} className="ds-row">
                  <div className="ds-row-main">
                    <div className="ds-row-id">
                      {r.id}{" "}
                      <span className={`ds-kind ds-kind-${r.kind}`}>{r.kind}</span>
                      {r.default && <span className="ds-default">default</span>}
                    </div>
                    <div className="ds-row-desc">{r.description}</div>
                    <div className="ds-row-config">
                      {Object.entries(r.config_summary).map(([k, v]) => (
                        <span key={k}>
                          {k}=<code>{Array.isArray(v) ? v.join(",") : String(v)}</code>{" "}
                        </span>
                      ))}
                    </div>
                  </div>
                  <div className="ds-row-actions">
                    <button onClick={() => onTest(r.id)} disabled={loadingId === r.id}>
                      {loadingId === r.id ? "…" : "Test"}
                    </button>
                    {(r.kind === "sqlite" || r.kind === "postgres") && (
                      <button onClick={() => setQueryOpenFor(r)}>Query</button>
                    )}
                    {!r.default && (
                      <button className="ds-danger" onClick={() => onDelete(r.id)}>
                        Remove
                      </button>
                    )}
                  </div>
                  {samples[r.id] && (
                    <div className="ds-samples">
                      <div className="ds-samples-label">
                        Sample facts ({samples[r.id].length})
                      </div>
                      {samples[r.id].length === 0 && (
                        <div className="ds-empty">no rows returned</div>
                      )}
                      {samples[r.id].map((f, i) => (
                        <div key={i} className="ds-sample">
                          <span className="ds-sample-id">
                            [{f.source}] {f.ontology_type}:{f.id}
                          </span>
                          <span className="ds-sample-title">{f.title}</span>
                          <span className="ds-sample-summary">{f.summary}</span>
                          {f.confidence != null && (
                            <span className="ds-sample-conf">cos={f.confidence.toFixed(3)}</span>
                          )}
                        </div>
                      ))}
                    </div>
                  )}
                </div>
              ))}
            </div>
            <div className="ds-footer">
              <button onClick={() => setAddMode("csv")}>+ Upload CSV</button>
              <button onClick={() => setAddMode("http")}>+ Add HTTP</button>
              <button onClick={() => setAddMode("sqlite")}>+ Add SQLite</button>
              <button onClick={() => setAddMode("postgres")}>+ Add Postgres</button>
              <button onClick={() => setAddMode("vector")}>+ Add Vector store</button>
            </div>
          </>
        )}

        {addMode === "csv" && <AddCsvForm onClose={() => setAddMode(null)} onAdded={refresh} setError={setError} />}
        {addMode === "http" && <AddHttpForm onClose={() => setAddMode(null)} onAdded={refresh} setError={setError} />}
        {addMode === "sqlite" && <AddSqliteForm onClose={() => setAddMode(null)} onAdded={refresh} setError={setError} />}
        {addMode === "postgres" && <AddPostgresForm onClose={() => setAddMode(null)} onAdded={refresh} setError={setError} />}
        {addMode === "vector" && <AddVectorForm onClose={() => setAddMode(null)} onAdded={refresh} setError={setError} />}
      </div>
      {queryOpenFor && (
        <QueryModal
          source={queryOpenFor}
          onClose={() => setQueryOpenFor(null)}
          onScenarioSaved={() => onScenariosChanged?.()}
        />
      )}
    </div>
  );
}

// =============================================================================
// Add forms
// =============================================================================
type AddFormProps = {
  onClose: () => void;
  onAdded: () => void;
  setError: (s: string | null) => void;
};

function AddCsvForm({ onClose, onAdded, setError }: AddFormProps) {
  const [file, setFile] = useState<File | null>(null);
  const [id, setId] = useState("");
  const [ontology, setOntology] = useState("Record");
  const [idField, setIdField] = useState("id");
  const [titleField, setTitleField] = useState("name");
  const [summary, setSummary] = useState("");
  const [busy, setBusy] = useState(false);

  const submit = async () => {
    if (!file || !id) {
      setError("ID and file required");
      return;
    }
    setBusy(true);
    try {
      await api.uploadCsv({
        file,
        id,
        ontology_type: ontology,
        id_field: idField,
        title_field: titleField,
        summary_template: summary,
      });
      onAdded();
      onClose();
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="ds-add-form">
      <h3>Upload CSV</h3>
      <label>File
        <input type="file" accept=".csv" onChange={(e) => setFile(e.target.files?.[0] ?? null)} />
      </label>
      <label>Source id <input value={id} onChange={(e) => setId(e.target.value)} placeholder="my_csv_data" /></label>
      <label>Ontology type <input value={ontology} onChange={(e) => setOntology(e.target.value)} /></label>
      <label>id_field <input value={idField} onChange={(e) => setIdField(e.target.value)} /></label>
      <label>title_field <input value={titleField} onChange={(e) => setTitleField(e.target.value)} /></label>
      <label>summary_template
        <input
          value={summary}
          onChange={(e) => setSummary(e.target.value)}
          placeholder="e.g. {field1} · {field2}"
        />
      </label>
      <div className="ds-form-actions">
        <button onClick={onClose}>Cancel</button>
        <button className="primary" disabled={busy} onClick={submit}>
          {busy ? "Uploading…" : "Upload"}
        </button>
      </div>
    </div>
  );
}

function AddHttpForm({ onClose, onAdded, setError }: AddFormProps) {
  const [id, setId] = useState("");
  const [baseUrl, setBaseUrl] = useState("https://");
  const [ontology, setOntology] = useState("Record");
  const [pathTpl, setPathTpl] = useState("/items/{id}");
  const [busy, setBusy] = useState(false);

  const submit = async () => {
    if (!id || !baseUrl || !ontology) {
      setError("All fields required");
      return;
    }
    setBusy(true);
    try {
      await api.addDataSource({
        id,
        kind: "http",
        config: { base_url: baseUrl, paths: { [ontology]: pathTpl } },
      });
      onAdded();
      onClose();
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="ds-add-form">
      <h3>Add HTTP source</h3>
      <label>Source id <input value={id} onChange={(e) => setId(e.target.value)} /></label>
      <label>Base URL <input value={baseUrl} onChange={(e) => setBaseUrl(e.target.value)} /></label>
      <label>Ontology type <input value={ontology} onChange={(e) => setOntology(e.target.value)} /></label>
      <label>Path template <input value={pathTpl} onChange={(e) => setPathTpl(e.target.value)} placeholder="/posts/{id}" /></label>
      <div className="ds-form-actions">
        <button onClick={onClose}>Cancel</button>
        <button className="primary" disabled={busy} onClick={submit}>{busy ? "…" : "Add"}</button>
      </div>
    </div>
  );
}

function AddSqliteForm({ onClose, onAdded, setError }: AddFormProps) {
  const [id, setId] = useState("");
  const [path, setPath] = useState("");
  const [ontology, setOntology] = useState("Record");
  const [sql, setSql] = useState("");
  const [busy, setBusy] = useState(false);
  const pathPlaceholder = "backend/data/governance.sqlite";
  const sqlPlaceholder =
    "SELECT id, name AS title, description AS summary FROM table LIMIT :max_results";

  const submit = async () => {
    setBusy(true);
    try {
      await api.addDataSource({
        id,
        kind: "sqlite",
        config: { path, queries: { [ontology]: sql } },
      });
      onAdded();
      onClose();
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="ds-add-form">
      <h3>Add SQLite source</h3>
      <label>Source id <input value={id} onChange={(e) => setId(e.target.value)} /></label>
      <label>Path <input value={path} onChange={(e) => setPath(e.target.value)} placeholder={pathPlaceholder} /></label>
      <label>Ontology type <input value={ontology} onChange={(e) => setOntology(e.target.value)} /></label>
      <label>SQL (use :name params, must SELECT id, title, summary)
        <textarea
          value={sql}
          onChange={(e) => setSql(e.target.value)}
          rows={4}
          placeholder={sqlPlaceholder}
        />
      </label>
      <div className="ds-form-actions">
        <button onClick={onClose}>Cancel</button>
        <button className="primary" disabled={busy || !id.trim() || !path.trim() || !sql.trim()} onClick={submit}>{busy ? "…" : "Add"}</button>
      </div>
    </div>
  );
}

function AddPostgresForm({ onClose, onAdded, setError }: AddFormProps) {
  const [id, setId] = useState("");
  const [dsn, setDsn] = useState("");
  const [ontology, setOntology] = useState("PriorOverride");
  const [sql, setSql] = useState("");
  const dsnPlaceholder = "postgresql://hitl:hitl@localhost:5432/governance";
  const sqlPlaceholder =
    "SELECT case_id AS id, scenario_id AS title, outcome || ' — ' || rationale AS summary FROM prior_cases WHERE scenario_id = :scenario_id ORDER BY decided_at DESC LIMIT :max_results";
  const [tested, setTested] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const test = async () => {
    setBusy(true);
    try {
      const r = await api.testPostgres(dsn);
      setTested(r.ok ? "✓ connection ok" : `✗ ${r.message}`);
    } finally {
      setBusy(false);
    }
  };

  const submit = async () => {
    setBusy(true);
    try {
      await api.addDataSource({
        id,
        kind: "postgres",
        config: { dsn, queries: { [ontology]: sql } },
      });
      onAdded();
      onClose();
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="ds-add-form">
      <h3>Add Postgres source</h3>
      <label>Source id <input value={id} onChange={(e) => setId(e.target.value)} /></label>
      <label>DSN
        <input value={dsn} onChange={(e) => setDsn(e.target.value)} placeholder={dsnPlaceholder} />
      </label>
      <button onClick={test} disabled={busy || !dsn.trim()} style={{ alignSelf: "flex-start" }}>Test connection</button>
      {tested && <div className="ds-test-result">{tested}</div>}
      <label>Ontology type <input value={ontology} onChange={(e) => setOntology(e.target.value)} /></label>
      <label>SQL
        <textarea value={sql} onChange={(e) => setSql(e.target.value)} rows={4} placeholder={sqlPlaceholder} />
      </label>
      <div className="ds-form-actions">
        <button onClick={onClose}>Cancel</button>
        <button className="primary" disabled={busy || !id.trim() || !dsn.trim() || !sql.trim()} onClick={submit}>{busy ? "…" : "Add"}</button>
      </div>
    </div>
  );
}

function AddVectorForm({ onClose, onAdded, setError }: AddFormProps) {
  const [id, setId] = useState("");
  const [folder, setFolder] = useState("");
  const [indexPath, setIndexPath] = useState("");
  const [ontology, setOntology] = useState("PolicyExcerpt");
  const [topK, setTopK] = useState(3);
  const [model, setModel] = useState("text-embedding-3-small");
  const [busy, setBusy] = useState(false);

  const folderPlaceholder = "backend/data/policy_corpus/";
  const indexPlaceholder = "backend/data/<id>.npz";

  const submit = async () => {
    setBusy(true);
    try {
      await api.addDataSource({
        id,
        kind: "vector_store",
        config: {
          folder,
          index_path: indexPath || `backend/data/${id}.npz`,
          ontology_type: ontology,
          top_k: topK,
          embed_model: model,
        },
      });
      onAdded();
      onClose();
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="ds-add-form">
      <h3>Add Vector store source</h3>
      <label>Source id <input value={id} onChange={(e) => setId(e.target.value)} /></label>
      <label>Folder (path containing .md / .txt to embed)
        <input value={folder} onChange={(e) => setFolder(e.target.value)} placeholder={folderPlaceholder} />
      </label>
      <label>Index path (.npz cache; auto-derived if blank)
        <input value={indexPath} onChange={(e) => setIndexPath(e.target.value)} placeholder={indexPlaceholder} />
      </label>
      <label>Ontology type <input value={ontology} onChange={(e) => setOntology(e.target.value)} /></label>
      <label>Top K <input type="number" min={1} max={20} value={topK} onChange={(e) => setTopK(parseInt(e.target.value || "3", 10))} /></label>
      <label>Embedding model <input value={model} onChange={(e) => setModel(e.target.value)} /></label>
      <div className="ds-add-help" style={{ fontSize: 11, color: "var(--ink-muted)", fontStyle: "italic" }}>
        Documents are embedded once at registration time using the OpenAI key from <code>.env</code>.
        Without a key the source registers but returns empty results until you add one and restart.
      </div>
      <div className="ds-form-actions">
        <button onClick={onClose}>Cancel</button>
        <button className="primary" disabled={busy || !id.trim() || !folder.trim()} onClick={submit}>{busy ? "Embedding…" : "Add"}</button>
      </div>
    </div>
  );
}

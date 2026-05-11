import { useEffect, useState } from "react";
import * as api from "../api";
import { DataSourceRow, SampleFact } from "../types";
import { QueryModal } from "./QueryModal";

type AddMode = null | "csv" | "http" | "sqlite" | "postgres" | "vector" | "neo4j";

export function DataSourcesModal({
  onClose,
  onScenariosChanged,
  embedded = false,
}: {
  onClose: () => void;
  onScenariosChanged?: () => void;
  // When true, render without the modal backdrop + outer dark header — the
  // KnowledgeModal mounts us inside its tab and provides those itself.
  embedded?: boolean;
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

  const body = (
    <>
      {!embedded && (
        <div className="ds-header">
          <div>
            <div className="ds-eyebrow">Data sources</div>
            <div className="ds-title">Connections & uploads</div>
          </div>
          <button className="teams-close" onClick={onClose}>
            ×
          </button>
        </div>
      )}

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
                    {(r.kind === "sqlite" || r.kind === "postgres" || r.kind === "neo4j") && (
                      <button onClick={() => setQueryOpenFor(r)}>
                        {r.kind === "neo4j" ? "Cypher" : "Query"}
                      </button>
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
              <button onClick={() => setAddMode("neo4j")}>+ Add Neo4j</button>
            </div>
          </>
        )}

      {addMode === "csv" && <AddCsvForm onClose={() => setAddMode(null)} onAdded={refresh} setError={setError} />}
      {addMode === "http" && <AddHttpForm onClose={() => setAddMode(null)} onAdded={refresh} setError={setError} />}
      {addMode === "sqlite" && <AddSqliteForm onClose={() => setAddMode(null)} onAdded={refresh} setError={setError} />}
      {addMode === "postgres" && <AddPostgresForm onClose={() => setAddMode(null)} onAdded={refresh} setError={setError} />}
      {addMode === "vector" && <AddVectorForm onClose={() => setAddMode(null)} onAdded={refresh} setError={setError} />}
      {addMode === "neo4j" && <AddNeo4jForm onClose={() => setAddMode(null)} onAdded={refresh} setError={setError} />}

      {queryOpenFor && (
        <QueryModal
          source={queryOpenFor}
          onClose={() => setQueryOpenFor(null)}
          onScenarioSaved={() => onScenariosChanged?.()}
        />
      )}
    </>
  );

  if (embedded) {
    return body;
  }
  return (
    <div
      className="modal-backdrop"
      onClick={(e) => e.target === e.currentTarget && onClose()}
    >
      <div className="ds-modal">{body}</div>
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
        // Phase 3.C: ontology binding moved to the mapping doc. The form
        // still passes a placeholder so the multipart endpoint signature
        // stays satisfied; the connector ignores it for ontology purposes.
        ontology_type: "Record",
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
      <label>id_field <input value={idField} onChange={(e) => setIdField(e.target.value)} /></label>
      <label>title_field <input value={titleField} onChange={(e) => setTitleField(e.target.value)} /></label>
      <label>summary_template
        <input
          value={summary}
          onChange={(e) => setSummary(e.target.value)}
          placeholder="e.g. {field1} · {field2}"
        />
      </label>
      <div className="ds-add-help" style={{ fontSize: 11, color: "var(--ink-muted)", fontStyle: "italic" }}>
        After upload, map this CSV to one or more ontology classes via{" "}
        <strong>Ontologies → Mappings</strong> to make it queryable from
        scenarios.
      </div>
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
  const [busy, setBusy] = useState(false);

  const submit = async () => {
    if (!id || !baseUrl) {
      setError("ID and base URL required");
      return;
    }
    setBusy(true);
    try {
      await api.addDataSource({
        id,
        kind: "http",
        config: { base_url: baseUrl },
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
      <div className="ds-add-help" style={{ fontSize: 11, color: "var(--ink-muted)", fontStyle: "italic" }}>
        Path templates (e.g. <code>/items/{`{id}`}</code>) live in the mapping
        doc. After saving, open <strong>Ontologies → Mappings</strong> to
        bind classes and supply per-class path templates.
      </div>
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
  const [busy, setBusy] = useState(false);
  const pathPlaceholder = "backend/data/governance.sqlite";

  const submit = async () => {
    setBusy(true);
    try {
      await api.addDataSource({
        id,
        kind: "sqlite",
        config: { path },
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
      <div className="ds-add-help" style={{ fontSize: 11, color: "var(--ink-muted)", fontStyle: "italic" }}>
        SQL queries live in the mapping doc. After saving, open{" "}
        <strong>Ontologies → Mappings</strong> to bind classes; each binding
        carries its own <code>query_template</code> (or you can leave it
        blank to auto-generate a <code>SELECT *</code>).
      </div>
      <div className="ds-form-actions">
        <button onClick={onClose}>Cancel</button>
        <button className="primary" disabled={busy || !id.trim() || !path.trim()} onClick={submit}>{busy ? "…" : "Add"}</button>
      </div>
    </div>
  );
}

function AddPostgresForm({ onClose, onAdded, setError }: AddFormProps) {
  const [id, setId] = useState("");
  const [dsn, setDsn] = useState("");
  const dsnPlaceholder = "postgresql://hitl:hitl@localhost:5432/governance";
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
        config: { dsn },
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
      <div className="ds-add-help" style={{ fontSize: 11, color: "var(--ink-muted)", fontStyle: "italic" }}>
        SQL queries live in the mapping doc. After saving, open{" "}
        <strong>Ontologies → Mappings</strong> to bind classes; each binding
        carries its own <code>query_template</code> (or auto-generates a{" "}
        <code>SELECT *</code> if you leave it blank).
      </div>
      <div className="ds-form-actions">
        <button onClick={onClose}>Cancel</button>
        <button className="primary" disabled={busy || !id.trim() || !dsn.trim()} onClick={submit}>{busy ? "…" : "Add"}</button>
      </div>
    </div>
  );
}

function AddVectorForm({ onClose, onAdded, setError }: AddFormProps) {
  const [id, setId] = useState("");
  const [folder, setFolder] = useState("");
  const [indexPath, setIndexPath] = useState("");
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
      <label>Top K <input type="number" min={1} max={20} value={topK} onChange={(e) => setTopK(parseInt(e.target.value || "3", 10))} /></label>
      <label>Embedding model <input value={model} onChange={(e) => setModel(e.target.value)} /></label>
      <div className="ds-add-help" style={{ fontSize: 11, color: "var(--ink-muted)", fontStyle: "italic" }}>
        Documents are embedded once at registration time using the OpenAI key from <code>.env</code>.
        Without a key the source registers but returns empty results until you add one and restart.
        Bind to an ontology class via <strong>Ontologies → Mappings</strong>.
      </div>
      <div className="ds-form-actions">
        <button onClick={onClose}>Cancel</button>
        <button className="primary" disabled={busy || !id.trim() || !folder.trim()} onClick={submit}>{busy ? "Embedding…" : "Add"}</button>
      </div>
    </div>
  );
}


function AddNeo4jForm({ onClose, onAdded, setError }: AddFormProps) {
  const [id, setId] = useState("");
  const [uri, setUri] = useState("bolt://localhost:7687");
  const [user, setUser] = useState("neo4j");
  const [password, setPassword] = useState("");
  const [database, setDatabase] = useState("");
  const [tested, setTested] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const test = async () => {
    setBusy(true);
    try {
      const r = await api.testNeo4j({ uri, user, password, database: database || undefined });
      setTested(r.ok ? "✓ connection ok" : `✗ ${r.message}`);
    } finally {
      setBusy(false);
    }
  };

  const submit = async () => {
    setBusy(true);
    try {
      const config: Record<string, unknown> = { uri };
      if (user) config.user = user;
      if (password) config.password = password;
      if (database) config.database = database;
      await api.addDataSource({ id, kind: "neo4j" as const, config });
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
      <h3>Add Neo4j source</h3>
      <label>Source id <input value={id} onChange={(e) => setId(e.target.value)} placeholder="graph_local" /></label>
      <label>Bolt URI
        <input value={uri} onChange={(e) => setUri(e.target.value)} placeholder="bolt://localhost:7687" />
      </label>
      <label>User <input value={user} onChange={(e) => setUser(e.target.value)} /></label>
      <label>Password <input type="password" value={password} onChange={(e) => setPassword(e.target.value)} /></label>
      <label>Database (optional — leave blank for default)
        <input value={database} onChange={(e) => setDatabase(e.target.value)} placeholder="neo4j" />
      </label>
      <button onClick={test} disabled={busy || !uri.trim()} style={{ alignSelf: "flex-start" }}>Test connection</button>
      {tested && <div className="ds-test-result">{tested}</div>}
      <div className="ds-add-help" style={{ fontSize: 11, color: "var(--ink-muted)", fontStyle: "italic" }}>
        Cypher templates live in the mapping doc. After saving, open <strong>Ontologies → Mappings</strong> to bind ontology classes; each binding carries its own <code>query_template</code> (Cypher MATCH … RETURN …).
        Read-only: write/mutate Cypher is rejected by the safety guard before reaching the driver.
      </div>
      <div className="ds-form-actions">
        <button onClick={onClose}>Cancel</button>
        <button className="primary" disabled={busy || !id.trim() || !uri.trim()} onClick={submit}>{busy ? "…" : "Add"}</button>
      </div>
    </div>
  );
}

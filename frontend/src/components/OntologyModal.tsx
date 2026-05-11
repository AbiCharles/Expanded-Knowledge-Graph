import { useEffect, useState } from "react";
import * as api from "../api";
import {
  ClassMapping,
  MappingDoc,
  OntologyClassDetail,
  OntologyQueryResult,
  OntologySummary,
  SourceBinding,
  SourceSchema,
} from "../api";
import { DataSourceRow } from "../types";

// One modal: ontology list on the left, selected-ontology detail on the right
// (classes + mappings). Mirrors DataSourcesModal's visual language.

// =============================================================================
// Built-in sample — pairs with the seeded products_csv + governance_sqlite
// sources so the "Suggest mappings" flow works out of the box.
// =============================================================================
const SAMPLE_ONTOLOGY = {
  id: "supply_chain_demo",
  title: "Supply chain demo",
  namespace: "sc",
  description: "Built-in sample for testing the ontology layer end-to-end.",
  classes: {
    Product: {
      description: "An item we sell — pairs with products_csv.",
      attributes: [
        { name: "product_id", type: "string", identifier: true },
        { name: "name", type: "string" },
        { name: "category", type: "string" },
        { name: "eccn", type: "string" },
      ],
    },
    PriorOverride: {
      description: "A historical case — pairs with governance_sqlite.prior_cases.",
      attributes: [
        { name: "case_id", type: "string", identifier: true },
        { name: "scenario_id", type: "string" },
        { name: "outcome", type: "string" },
        { name: "rationale", type: "string" },
      ],
    },
  },
};

const SAMPLE_YAML = `id: supply_chain_demo
title: Supply chain demo
namespace: sc
classes:
  Product:
    description: An item we sell — pairs with products_csv.
    attributes:
      - { name: product_id, type: string, identifier: true }
      - { name: name, type: string }
      - { name: category, type: string }
      - { name: eccn, type: string }
  PriorOverride:
    description: A historical case — pairs with governance_sqlite.prior_cases.
    attributes:
      - { name: case_id, type: string, identifier: true }
      - { name: scenario_id, type: string }
      - { name: outcome, type: string }
      - { name: rationale, type: string }`;

export function OntologyModal({
  onClose,
  embedded = false,
  onScenariosChanged,
}: {
  onClose: () => void;
  // When true, render without the modal backdrop + outer dark header — the
  // KnowledgeModal mounts us inside its tab and provides those itself.
  embedded?: boolean;
  // Bubbled from KnowledgeModal → App so generating a lookup chip refreshes
  // the operator console's chip list immediately.
  onScenariosChanged?: () => void;
}) {
  const [ontologies, setOntologies] = useState<OntologySummary[]>([]);
  const [sources, setSources] = useState<DataSourceRow[]>([]);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const refresh = async () => {
    try {
      const [os, ds] = await Promise.all([api.listOntologies(), api.listDataSources()]);
      setOntologies(os);
      setSources(ds);
    } catch (e) {
      setError((e as Error).message);
    }
  };
  useEffect(() => {
    refresh();
  }, []);

  // Auto-select the first ontology once we have any
  useEffect(() => {
    if (selectedId === null && ontologies.length > 0) {
      setSelectedId(ontologies[0].id);
    }
  }, [ontologies, selectedId]);

  const selected = ontologies.find((o) => o.id === selectedId) || null;

  const onUpload = async (file: File) => {
    setError(null);
    try {
      const result = await api.uploadOntologyFile(file);
      await refresh();
      setSelectedId(result.id);
    } catch (e) {
      setError((e as Error).message);
    }
  };

  const onLoadSample = async () => {
    setError(null);
    try {
      const result = await api.uploadOntologyRaw({ document: SAMPLE_ONTOLOGY });
      await refresh();
      setSelectedId(result.id);
    } catch (e) {
      setError((e as Error).message);
    }
  };

  const onDelete = async (id: string) => {
    if (!confirm(`Remove ontology "${id}" and any mapping?`)) return;
    try {
      await api.deleteOntology(id);
      if (selectedId === id) setSelectedId(null);
      await refresh();
    } catch (e) {
      setError((e as Error).message);
    }
  };

  const body = (
    <>
      {!embedded && (
        <div className="ds-header">
          <div>
            <div className="ds-eyebrow">Ontologies</div>
            <div className="ds-title">Schema + source mappings</div>
          </div>
          <button className="teams-close" onClick={onClose}>
            ×
          </button>
        </div>
      )}

      {error && <div className="ds-error">{error}</div>}

        <div
          style={{
            display: "grid",
            gridTemplateColumns: "260px 1fr",
            gap: 16,
            padding: "0 16px 16px",
            // Crucial: the parent .ds-modal is overflow:hidden, so this row
            // is the scroll boundary. Without min-height:0 the grid would
            // stretch to its content and the modal would clip.
            flex: 1,
            minHeight: 0,
            overflow: "hidden",
          }}
        >
          {/* Left: upload (always visible) + list */}
          <div style={{ display: "flex", flexDirection: "column", gap: 12, minHeight: 0 }}>
            <UploadBlock
              onUpload={onUpload}
              onLoadSample={onLoadSample}
              hasSample={ontologies.some((o) => o.id === SAMPLE_ONTOLOGY.id)}
              hasOntologies={ontologies.length > 0}
            />
            <div style={{ fontSize: 12, fontWeight: 600, color: "var(--ink-soft)" }}>
              Loaded ontologies
            </div>
            <div
              style={{
                display: "flex",
                flexDirection: "column",
                gap: 4,
                overflowY: "auto",
                paddingRight: 4,
              }}
            >
              {ontologies.length === 0 && (
                <div
                  style={{
                    fontSize: 12,
                    color: "var(--ink-soft)",
                    padding: 12,
                    border: "1px dashed var(--border)",
                    borderRadius: 4,
                  }}
                >
                  No ontologies uploaded yet — pick a file above.
                </div>
              )}
              {ontologies.map((o) => (
                <button
                  key={o.id}
                  onClick={() => setSelectedId(o.id)}
                  style={{
                    cursor: "pointer",
                    background: o.id === selectedId ? "rgba(0,201,183,0.08)" : "transparent",
                    border: o.id === selectedId ? "1px solid var(--cyan)" : "1px solid var(--border)",
                    padding: 8,
                    borderRadius: 4,
                    textAlign: "left",
                  }}
                >
                  <div style={{ fontWeight: 600, fontSize: 13 }}>{o.title}</div>
                  <div style={{ fontSize: 11, color: "var(--ink-soft)" }}>
                    <code>{o.id}</code> · {o.class_count} class
                    {o.class_count === 1 ? "" : "es"}{" "}
                    {o.has_mapping ? "· mapped" : "· no mapping"}
                  </div>
                </button>
              ))}
            </div>
          </div>

          {/* Right: selected detail (own scroll region) */}
          <div style={{ overflowY: "auto", paddingRight: 4, minHeight: 0 }}>
            {selected ? (
              <OntologyDetail
                ontology={selected}
                sources={sources}
                onDelete={() => onDelete(selected.id)}
                onMappingChanged={refresh}
                onScenariosChanged={onScenariosChanged}
              />
            ) : (
              <EmptyDetail
                hasOntologies={ontologies.length > 0}
                onLoadSample={onLoadSample}
                sampleAlreadyLoaded={ontologies.some((o) => o.id === SAMPLE_ONTOLOGY.id)}
              />
            )}
          </div>
        </div>
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
      <div className="ds-modal" style={{ maxWidth: 1100, width: "90vw" }}>
        {body}
      </div>
    </div>
  );
}

function EmptyDetail({
  hasOntologies,
  onLoadSample,
  sampleAlreadyLoaded,
}: {
  hasOntologies: boolean;
  onLoadSample: () => void;
  sampleAlreadyLoaded: boolean;
}) {
  return (
    <div style={{ fontSize: 12, color: "var(--ink-soft)", padding: 24, lineHeight: 1.5 }}>
      {hasOntologies ? (
        <>Pick an ontology on the left to view its classes and manage mappings.</>
      ) : (
        <>
          <div style={{ fontWeight: 600, color: "var(--ink)", marginBottom: 6 }}>
            Get started
          </div>
          Upload an ontology file (YAML or JSON) using the picker on the left, or
          load the built-in sample below to see the full flow without authoring
          your own.

          <div
            style={{
              marginTop: 14,
              padding: 12,
              background: "rgba(0,201,183,0.05)",
              border: "1px dashed var(--cyan)",
              borderRadius: 4,
            }}
          >
            <div
              style={{
                display: "flex",
                alignItems: "center",
                justifyContent: "space-between",
                marginBottom: 6,
              }}
            >
              <strong style={{ color: "var(--ink)", fontSize: 12 }}>
                Sample: <code>{SAMPLE_ONTOLOGY.id}</code>
              </strong>
              <button
                onClick={onLoadSample}
                disabled={sampleAlreadyLoaded}
                style={{ fontSize: 12 }}
              >
                {sampleAlreadyLoaded ? "Already loaded" : "Load sample"}
              </button>
            </div>
            <div style={{ fontSize: 11, color: "var(--ink-soft)", marginBottom: 8 }}>
              Two classes — <code>Product</code> pairs with the seeded{" "}
              <code>products_csv</code>, <code>PriorOverride</code> pairs with{" "}
              <code>governance_sqlite.prior_cases</code>. After loading, the
              Mappings tab's <em>Suggest mappings</em> button will demo
              cross-source dispatch in one click.
            </div>
            <pre
              style={{
                fontSize: 11,
                margin: 0,
                padding: 8,
                background: "white",
                border: "1px solid var(--border)",
                borderRadius: 3,
                whiteSpace: "pre-wrap",
                maxHeight: 240,
                overflow: "auto",
              }}
            >
              {SAMPLE_YAML}
            </pre>
          </div>

          <div style={{ marginTop: 14, fontSize: 11 }}>
            Once an ontology is loaded you can:
            <ul style={{ marginTop: 6, paddingLeft: 18 }}>
              <li>browse classes, attributes, and relations</li>
              <li>ask the LLM to suggest source mappings</li>
              <li>review the proposals and Save to commit the mapping doc</li>
            </ul>
          </div>
        </>
      )}
    </div>
  );
}

// =============================================================================
// Upload (file picker)
// =============================================================================
function UploadBlock({
  onUpload,
  onLoadSample,
  hasSample,
  hasOntologies,
}: {
  onUpload: (file: File) => void;
  onLoadSample: () => void;
  hasSample: boolean;
  hasOntologies: boolean;
}) {
  const [busy, setBusy] = useState(false);
  return (
    <div
      style={{
        padding: 12,
        border: hasOntologies ? "1px dashed var(--border)" : "2px dashed var(--cyan)",
        background: hasOntologies ? "transparent" : "rgba(0,201,183,0.04)",
        borderRadius: 4,
      }}
    >
      <div style={{ fontSize: 12, fontWeight: 600, marginBottom: 6 }}>
        {hasOntologies ? "Upload another" : "Upload ontology"}
      </div>
      <div style={{ fontSize: 11, color: "var(--ink-soft)", marginBottom: 8 }}>
        Accepts <code>.yaml</code>, <code>.yml</code>, or <code>.json</code>
      </div>
      <input
        type="file"
        accept=".yaml,.yml,.json,application/json,text/yaml,application/x-yaml"
        disabled={busy}
        onChange={async (e) => {
          const file = e.target.files?.[0];
          if (!file) return;
          setBusy(true);
          try {
            await onUpload(file);
          } finally {
            setBusy(false);
            e.target.value = "";
          }
        }}
        style={{ fontSize: 12, width: "100%" }}
      />
      <button
        onClick={onLoadSample}
        disabled={hasSample}
        title={
          hasSample
            ? "The supply_chain_demo sample is already loaded"
            : "Load the built-in sample ontology (no file needed)"
        }
        style={{ fontSize: 11, marginTop: 8, width: "100%" }}
      >
        {hasSample ? "Sample already loaded" : "Or load built-in sample"}
      </button>
    </div>
  );
}

// =============================================================================
// Detail panel (classes + mappings, tabbed)
// =============================================================================
function OntologyDetail({
  ontology,
  sources,
  onDelete,
  onMappingChanged,
  onScenariosChanged,
}: {
  ontology: OntologySummary;
  sources: DataSourceRow[];
  onDelete: () => void;
  onMappingChanged: () => void;
  onScenariosChanged?: () => void;
}) {
  const [tab, setTab] = useState<"classes" | "mappings" | "query">("classes");
  const [classes, setClasses] = useState<OntologyClassDetail[]>([]);
  const [mapping, setMapping] = useState<MappingDoc | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    setLoading(true);
    Promise.all([
      api.getOntologyClasses(ontology.id),
      api.getMappings(ontology.id),
    ])
      .then(([cs, m]) => {
        setClasses(cs);
        setMapping(m);
      })
      .catch(console.error)
      .finally(() => setLoading(false));
  }, [ontology.id]);

  return (
    <div>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 8 }}>
        <div>
          <div style={{ fontSize: 16, fontWeight: 600 }}>{ontology.title}</div>
          <div style={{ fontSize: 11, color: "var(--ink-soft)" }}>
            <code>{ontology.id}</code>
            {ontology.namespace && <> · namespace <code>{ontology.namespace}</code></>}
          </div>
        </div>
        <button className="ds-danger" onClick={onDelete} style={{ fontSize: 11 }}>
          Delete ontology
        </button>
      </div>

      <div style={{ display: "flex", gap: 4, borderBottom: "1px solid var(--border)" }}>
        <TabButton active={tab === "classes"} onClick={() => setTab("classes")}>
          Classes ({classes.length})
        </TabButton>
        <TabButton active={tab === "mappings"} onClick={() => setTab("mappings")}>
          Mappings
        </TabButton>
        <TabButton active={tab === "query"} onClick={() => setTab("query")}>
          Query
        </TabButton>
      </div>

      {loading && <div style={{ padding: 16, fontSize: 12 }}>Loading…</div>}

      {!loading && tab === "classes" && <ClassesView classes={classes} />}

      {!loading && tab === "mappings" && (
        <MappingsView
          ontologyId={ontology.id}
          classes={classes}
          mapping={mapping}
          sources={sources}
          onMappingChanged={() => {
            onMappingChanged();
            api.getMappings(ontology.id).then(setMapping).catch(console.error);
          }}
          onScenariosChanged={onScenariosChanged}
        />
      )}

      {!loading && tab === "query" && (
        <QueryView
          ontologyId={ontology.id}
          classes={classes}
          hasMapping={mapping !== null && Object.keys(mapping.mappings || {}).length > 0}
        />
      )}
    </div>
  );
}

function TabButton({ active, onClick, children }: { active: boolean; onClick: () => void; children: React.ReactNode }) {
  return (
    <button
      onClick={onClick}
      style={{
        background: "none",
        border: "none",
        borderBottom: active ? "2px solid var(--cyan)" : "2px solid transparent",
        padding: "8px 12px",
        fontSize: 13,
        fontWeight: active ? 600 : 400,
        cursor: "pointer",
      }}
    >
      {children}
    </button>
  );
}

// -----------------------------------------------------------------------------
// Classes view
// -----------------------------------------------------------------------------
function ClassesView({ classes }: { classes: OntologyClassDetail[] }) {
  return (
    <div style={{ paddingTop: 12, display: "flex", flexDirection: "column", gap: 12 }}>
      {classes.map((c) => (
        <div key={c.name} className="ds-row" style={{ padding: 10 }}>
          <div style={{ fontWeight: 600, fontSize: 13 }}>
            {c.name}
            {c.identifier_attribute && (
              <span
                style={{
                  marginLeft: 8,
                  fontSize: 10,
                  background: "rgba(0,201,183,0.12)",
                  color: "var(--cyan)",
                  padding: "2px 6px",
                  borderRadius: 3,
                }}
              >
                id: {c.identifier_attribute}
              </span>
            )}
          </div>
          {c.description && (
            <div style={{ fontSize: 11, color: "var(--ink-soft)", marginTop: 2 }}>
              {c.description}
            </div>
          )}
          <div style={{ marginTop: 6, fontSize: 11 }}>
            <span style={{ color: "var(--ink-soft)" }}>Attributes: </span>
            {c.attributes.map((a, i) => (
              <span key={a.name}>
                {i > 0 && ", "}
                <code>{a.name}</code>
                <span style={{ color: "var(--ink-soft)" }}>:{a.type}</span>
                {a.identifier && <span style={{ color: "var(--cyan)" }}>*</span>}
              </span>
            ))}
          </div>
          {c.relations.length > 0 && (
            <div style={{ marginTop: 4, fontSize: 11 }}>
              <span style={{ color: "var(--ink-soft)" }}>Relations: </span>
              {c.relations.map((r, i) => (
                <span key={r.name}>
                  {i > 0 && ", "}
                  <code>{r.name}</code> → <code>{r.target}</code>{" "}
                  <span style={{ color: "var(--ink-soft)" }}>({r.cardinality})</span>
                </span>
              ))}
            </div>
          )}
        </div>
      ))}
    </div>
  );
}

// -----------------------------------------------------------------------------
// Mappings view
// -----------------------------------------------------------------------------
function MappingsView({
  ontologyId,
  classes,
  mapping,
  sources,
  onMappingChanged,
  onScenariosChanged,
}: {
  ontologyId: string;
  classes: OntologyClassDetail[];
  mapping: MappingDoc | null;
  sources: DataSourceRow[];
  onMappingChanged: () => void;
  onScenariosChanged?: () => void;
}) {
  // Local working copy of the mapping doc — edits stay local until "Save"
  const [draft, setDraft] = useState<MappingDoc>(
    mapping || { ontology_id: ontologyId, mappings: {} }
  );
  const [schemas, setSchemas] = useState<SourceSchema[]>([]);
  const [suggestionLLM, setSuggestionLLM] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [info, setInfo] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [savedThisSession, setSavedThisSession] = useState(false);
  const [hasSuggestion, setHasSuggestion] = useState(false);
  // Default-tick all sources — the LLM is the right judge of which ones
  // actually fit; this saves the user a step in the common case.
  const [picked, setPicked] = useState<Set<string>>(
    new Set(sources.map((s) => s.id))
  );

  // Reset draft + ticks when the ontology changes or sources arrive late
  useEffect(() => {
    setDraft(mapping || { ontology_id: ontologyId, mappings: {} });
  }, [mapping, ontologyId]);
  useEffect(() => {
    setPicked((prev) => (prev.size === 0 ? new Set(sources.map((s) => s.id)) : prev));
  }, [sources]);

  const onSuggest = async () => {
    setError(null);
    setInfo(null);
    setSavedThisSession(false);
    setBusy(true);
    try {
      const ids = Array.from(picked);
      const result = await api.suggestMappings(ontologyId, ids);
      setDraft(result.mapping);
      setSchemas(result.schemas);
      setSuggestionLLM(result.llm);
      setHasSuggestion(true);
      setInfo(
        `Drafted ${countBindings(result.mapping)} binding(s) from ${
          result.schemas.length
        } source(s). Review the per-class panels below — edit any dropdowns the LLM got wrong, then click Save mapping.`
      );
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  };

  const onSave = async () => {
    setError(null);
    setBusy(true);
    try {
      await api.putMappings(ontologyId, draft);
      onMappingChanged();
      setSavedThisSession(true);
      setInfo(null);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  };

  const totalBindings = countBindings(draft);

  return (
    <div style={{ paddingTop: 12 }}>
      <div
        style={{
          fontSize: 12,
          color: "var(--ink-soft)",
          marginBottom: 10,
          lineHeight: 1.5,
        }}
      >
        A <strong>mapping</strong> tells the OntologyResolver which data
        source(s) back each ontology class, and which column holds each
        attribute. Walk through the three steps below — the LLM does the
        first draft; you confirm or fix it; saving writes
        <code> backend/ontologies/{ontologyId}.mappings.yaml</code>.
      </div>

      {/* Source picker — always visible so the next step is obvious */}
      <div
        style={{
          padding: 12,
          marginBottom: 12,
          border: "1px solid var(--cyan)",
          background: "rgba(0,201,183,0.04)",
          borderRadius: 4,
        }}
      >
        <NumberedStep n={1} title="Pick the sources to ask the LLM about">
          Each ticked source will be inspected (table list, columns, sample
          values) and shown to the LLM alongside every ontology class. The
          LLM decides on its own which sources fit which classes — ticking
          a source that doesn't fit just means "the LLM will look at it and
          decide it doesn't apply." Default: all ticked.
        </NumberedStep>
        {sources.length === 0 ? (
          <div style={{ fontSize: 12, color: "var(--crimson)" }}>
            No data sources registered yet — open <strong>Data sources</strong>{" "}
            in the status bar and add one (or wait for the seeded ones to
            load) before suggesting mappings.
          </div>
        ) : (
          <div
            style={{
              display: "grid",
              gridTemplateColumns: "repeat(auto-fill, minmax(200px, 1fr))",
              gap: 4,
              marginBottom: 8,
            }}
          >
            {sources.map((s) => (
              <label
                key={s.id}
                style={{ fontSize: 12, display: "flex", alignItems: "center", gap: 6 }}
              >
                <input
                  type="checkbox"
                  checked={picked.has(s.id)}
                  onChange={(e) => {
                    const next = new Set(picked);
                    if (e.target.checked) next.add(s.id);
                    else next.delete(s.id);
                    setPicked(next);
                  }}
                />
                <code>{s.id}</code>{" "}
                <span style={{ color: "var(--ink-soft)" }}>({s.kind})</span>
              </label>
            ))}
          </div>
        )}

        <NumberedStep n={2} title="Get a draft mapping">
          Click <em>Suggest mappings</em> to ask the LLM. One call per
          (class × table) pair. With <code>LLM_PROVIDER=fake</code> the
          backend falls back to a deterministic name-matcher.
        </NumberedStep>
        <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
          <button onClick={onSuggest} disabled={busy || picked.size === 0 || sources.length === 0}>
            {busy ? "Asking LLM…" : `Suggest mappings (${picked.size})`}
          </button>
          {suggestionLLM && (
            <span style={{ fontSize: 11, color: "var(--ink-soft)" }}>
              Drafted via <code>{suggestionLLM}</code>
              {suggestionLLM === "fake" && " (LLM unavailable — name-match fallback)"}
            </span>
          )}
        </div>

        <NumberedStep n={3} title="Review the proposals, then save">
          Each class panel below shows the draft binding(s). Confidence
          badges:{" "}
          <ConfidenceBadge value={0.9} /> high · <ConfidenceBadge value={0.7} /> plausible · <ConfidenceBadge value={0.4} /> guess.
          Adjust dropdowns or remove bindings you don't want; then save
          to commit. The mapping is what makes <code>ontology_queries:</code>{" "}
          blocks in scenarios resolve to real data.
        </NumberedStep>
        <button onClick={onSave} disabled={busy || totalBindings === 0}>
          {busy ? "Saving…" : `Save mapping (${totalBindings} binding${totalBindings === 1 ? "" : "s"})`}
        </button>

        <NumberedStep n={4} title="Optional: turn classes into operator chips">
          After saving the mapping, each class panel below has a{" "}
          <strong>Generate lookup chip</strong> button. Clicking it creates
          an autonomous <code>SC-ONTO-&lt;ontology&gt;-&lt;Class&gt;</code>{" "}
          chip on the operator console (the left-side suggestions list).
          Operators can then click that chip — or type a matching prompt —
          to fan-out a read-only lookup across every source the mapping
          covers, all without writing a scenario YAML by hand. Click the
          button again later to refresh the chip if the mapping changes;
          delete the chip with the modal's edit button or the API.
        </NumberedStep>
      </div>

      {info && <div style={{ fontSize: 12, color: "var(--ink-soft)", marginBottom: 8 }}>{info}</div>}
      {error && <div className="ds-error">{error}</div>}
      {savedThisSession && <SavedNextSteps ontologyId={ontologyId} classes={classes} />}

      {!hasSuggestion && totalBindings === 0 && (
        <div
          style={{
            padding: 14,
            border: "1px dashed var(--border)",
            borderRadius: 4,
            fontSize: 12,
            color: "var(--ink-soft)",
            marginBottom: 12,
            textAlign: "center",
          }}
        >
          No bindings yet. Click <strong>Suggest mappings</strong> above to
          have the LLM draft them, or add bindings by hand via{" "}
          <code>PUT /api/ontologies/{ontologyId}/mappings</code>.
        </div>
      )}

      <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
        {classes.map((c) => {
          const classMapping = draft.mappings[c.name] || { sources: [], relations: {} };
          const classSchemas = schemas.filter((s) =>
            classMapping.sources.some((b) => b.data_source === s.source_id)
          );
          return (
            <ClassMappingEditor
              key={c.name}
              classDetail={c}
              classMapping={classMapping}
              classSchemas={classSchemas}
              ontologyId={ontologyId}
              onChipChanged={() => {
                onMappingChanged();
                // Refresh the operator-console chip list at the App level so
                // the newly-generated SC-ONTO-* chip appears immediately.
                onScenariosChanged?.();
              }}
              onChange={(updated) =>
                setDraft({
                  ...draft,
                  mappings: { ...draft.mappings, [c.name]: updated },
                })
              }
            />
          );
        })}
      </div>
    </div>
  );
}

// -----------------------------------------------------------------------------
// Small helpers used by MappingsView
// -----------------------------------------------------------------------------
function NumberedStep({ n, title, children }: { n: number; title: string; children: React.ReactNode }) {
  return (
    <div style={{ margin: n === 1 ? "0 0 8px" : "12px 0 8px" }}>
      <div style={{ fontSize: 12, fontWeight: 600, marginBottom: 4 }}>
        {n}. {title}
      </div>
      <div style={{ fontSize: 11, color: "var(--ink-soft)", lineHeight: 1.5 }}>{children}</div>
    </div>
  );
}

function ConfidenceBadge({ value }: { value: number }) {
  return (
    <span
      style={{
        fontSize: 10,
        padding: "1px 5px",
        borderRadius: 3,
        background:
          value >= 0.85
            ? "rgba(47,125,95,0.15)"
            : value >= 0.6
              ? "rgba(214,158,46,0.15)"
              : "rgba(179,58,58,0.10)",
        color:
          value >= 0.85
            ? "var(--emerald)"
            : value >= 0.6
              ? "var(--amber)"
              : "var(--crimson)",
      }}
    >
      {(value * 100).toFixed(0)}%
    </span>
  );
}

function SavedNextSteps({
  ontologyId,
  classes,
}: {
  ontologyId: string;
  classes: OntologyClassDetail[];
}) {
  const firstClass = classes[0]?.name || "Class";
  const firstAttr = classes[0]?.attributes[0]?.name || "id";
  return (
    <div
      style={{
        marginBottom: 12,
        padding: 12,
        border: "1px solid var(--emerald)",
        background: "rgba(47,125,95,0.06)",
        borderRadius: 4,
      }}
    >
      <div style={{ fontSize: 12, fontWeight: 600, color: "var(--emerald)", marginBottom: 6 }}>
        ✓ Mapping saved. What's next?
      </div>
      <div style={{ fontSize: 11, color: "var(--ink-soft)", marginBottom: 8, lineHeight: 1.5 }}>
        The OntologyResolver can now serve queries for this ontology. Two
        ways to use it:
      </div>
      <ul style={{ fontSize: 11, paddingLeft: 18, margin: 0, lineHeight: 1.6 }}>
        <li>
          <strong>Try a query directly</strong> via{" "}
          <code>POST /api/ontology-query/structured</code> (Phase 1 endpoint —
          a UI playground lands in Phase 3):
          <pre
            style={{
              fontSize: 11,
              padding: 6,
              background: "white",
              border: "1px solid var(--border)",
              borderRadius: 3,
              margin: "4px 0",
              whiteSpace: "pre-wrap",
            }}
          >{`curl -X POST http://localhost:8001/api/ontology-query/structured \\
  -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' \\
  -d '{"ontology": "${ontologyId}", "class": "${firstClass}", "where": {}, "max_results": 3}'`}</pre>
        </li>
        <li>
          <strong>Reference it from a scenario.</strong> Add an{" "}
          <code>ontology_queries:</code> block to a scenario YAML in{" "}
          <code>backend/scenarios/</code> and restart uvicorn:
          <pre
            style={{
              fontSize: 11,
              padding: 6,
              background: "white",
              border: "1px solid var(--border)",
              borderRadius: 3,
              margin: "4px 0",
              whiteSpace: "pre-wrap",
            }}
          >{`stages:
  proposal:
    binder: OntologyProposalBinder/1.0
    ontology_queries:
      - ontology: ${ontologyId}
        class: ${firstClass}
        where: { ${firstAttr}: ":${firstAttr}" }`}</pre>
          The agent then binds facts via this mapping when the scenario fires.
        </li>
      </ul>
    </div>
  );
}

function countBindings(m: MappingDoc): number {
  return Object.values(m.mappings).reduce((acc, cm) => acc + (cm.sources?.length || 0), 0);
}

// -----------------------------------------------------------------------------
// Per-class mapping editor
// -----------------------------------------------------------------------------
function ClassMappingEditor({
  classDetail,
  classMapping,
  classSchemas,
  ontologyId,
  onChipChanged,
  onChange,
}: {
  classDetail: OntologyClassDetail;
  classMapping: ClassMapping;
  classSchemas: SourceSchema[];
  ontologyId: string;
  onChipChanged?: () => void;
  onChange: (updated: ClassMapping) => void;
}) {
  const [chipBusy, setChipBusy] = useState(false);
  const [chipMsg, setChipMsg] = useState<string | null>(null);
  const updateBinding = (idx: number, next: SourceBinding) => {
    const sources = [...classMapping.sources];
    sources[idx] = next;
    onChange({ ...classMapping, sources });
  };
  const removeBinding = (idx: number) => {
    onChange({
      ...classMapping,
      sources: classMapping.sources.filter((_, i) => i !== idx),
    });
  };
  const generateChip = async () => {
    setChipBusy(true);
    setChipMsg(null);
    try {
      const r = await api.generateLookupChip(ontologyId, classDetail.name);
      setChipMsg(
        `✓ Created chip "${r.title}" (id ${r.scenario_id}, ${r.binding_count} ` +
        `binding${r.binding_count === 1 ? "" : "s"}). It now appears in the ` +
        "operator console on the left — click it to run an autonomous lookup."
      );
      onChipChanged?.();
    } catch (e) {
      setChipMsg(`✗ ${(e as Error).message}`);
    } finally {
      setChipBusy(false);
    }
  };

  return (
    <div className="ds-row" style={{ padding: 10 }}>
      <div
        style={{
          display: "flex",
          alignItems: "center",
          justifyContent: "space-between",
          marginBottom: 6,
        }}
      >
        <div style={{ fontWeight: 600, fontSize: 13 }}>
          {classDetail.name}{" "}
          <span style={{ fontSize: 10, color: "var(--ink-soft)", fontWeight: 400 }}>
            ({classDetail.attributes.length} attribute
            {classDetail.attributes.length === 1 ? "" : "s"})
          </span>
        </div>
        <button
          onClick={generateChip}
          disabled={chipBusy || classMapping.sources.length === 0}
          title={
            classMapping.sources.length === 0
              ? "Add a source binding (Suggest mappings) and Save first — a chip needs at least one source backing this class."
              : `Create an autonomous SC-ONTO-${ontologyId}-${classDetail.name} ` +
                "chip on the operator console (left-side suggestions list). " +
                "Operators click the chip to run a read-only lookup that fans " +
                "out to every source the mapping covers."
          }
          style={{ fontSize: 11 }}
        >
          {chipBusy ? "…" : "Generate lookup chip"}
        </button>
      </div>
      {chipMsg && (
        <div style={{ fontSize: 11, color: "var(--ink-soft)", marginBottom: 6 }}>
          {chipMsg}
        </div>
      )}
      {classMapping.sources.length === 0 && (
        <div style={{ fontSize: 11, color: "var(--ink-soft)", padding: 8 }}>
          No source bindings — click "Suggest mappings" above or add one by hand
          via the API.
        </div>
      )}
      {classMapping.sources.map((binding, idx) => {
        const schema = classSchemas.find((s) => s.source_id === binding.data_source);
        // Pull column candidates from the schema's first table for the editor's
        // dropdowns. If we don't have a schema, fall back to whatever the
        // binding already references (so manual edits aren't blocked).
        const columnCandidates =
          schema?.tables[0]?.columns.map((c) => c.name) ||
          [binding.identifier_column, ...Object.values(binding.attribute_map)].filter(Boolean);
        return (
          <BindingRow
            key={idx}
            classDetail={classDetail}
            binding={binding}
            columnCandidates={Array.from(new Set(columnCandidates))}
            onChange={(b) => updateBinding(idx, b)}
            onRemove={() => removeBinding(idx)}
          />
        );
      })}
    </div>
  );
}

function BindingRow({
  classDetail,
  binding,
  columnCandidates,
  onChange,
  onRemove,
}: {
  classDetail: OntologyClassDetail;
  binding: SourceBinding;
  columnCandidates: string[];
  onChange: (b: SourceBinding) => void;
  onRemove: () => void;
}) {
  return (
    <div style={{ borderTop: "1px dashed var(--border)", paddingTop: 8, marginTop: 8 }}>
      <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
        <code style={{ fontSize: 11 }}>{binding.data_source}</code>
        {binding.confidence !== null && (
          <span
            style={{
              fontSize: 10,
              padding: "2px 6px",
              borderRadius: 3,
              background:
                binding.confidence >= 0.85
                  ? "rgba(47,125,95,0.15)"
                  : binding.confidence >= 0.6
                    ? "rgba(214,158,46,0.15)"
                    : "rgba(179,58,58,0.10)",
              color:
                binding.confidence >= 0.85
                  ? "var(--emerald)"
                  : binding.confidence >= 0.6
                    ? "var(--amber)"
                    : "var(--crimson)",
            }}
          >
            confidence {(binding.confidence * 100).toFixed(0)}%
          </span>
        )}
        {binding.suggested_by && (
          <span style={{ fontSize: 10, color: "var(--ink-soft)" }}>
            via {binding.suggested_by}
          </span>
        )}
        <div style={{ flex: 1 }} />
        <button onClick={onRemove} style={{ fontSize: 11 }} className="ds-danger">
          Remove
        </button>
      </div>
      {binding.notes && (
        <div style={{ fontSize: 11, color: "var(--ink-soft)", margin: "4px 0", fontStyle: "italic" }}>
          {binding.notes}
        </div>
      )}
      <table style={{ width: "100%", fontSize: 11, marginTop: 6, borderCollapse: "collapse" }}>
        <thead>
          <tr>
            <th style={th}>Ontology attribute</th>
            <th style={th}>Source column</th>
          </tr>
        </thead>
        <tbody>
          <tr>
            <td style={td}>
              <em>{"<identifier>"}</em>
            </td>
            <td style={td}>
              <ColumnPicker
                value={binding.identifier_column}
                candidates={columnCandidates}
                onChange={(v) => onChange({ ...binding, identifier_column: v })}
              />
            </td>
          </tr>
          {classDetail.attributes.map((attr) => (
            <tr key={attr.name}>
              <td style={td}>
                <code>{attr.name}</code>
                <span style={{ color: "var(--ink-soft)" }}>:{attr.type}</span>
              </td>
              <td style={td}>
                <ColumnPicker
                  value={binding.attribute_map[attr.name] || ""}
                  candidates={columnCandidates}
                  onChange={(v) => {
                    const next = { ...binding.attribute_map };
                    if (v) next[attr.name] = v;
                    else delete next[attr.name];
                    onChange({ ...binding, attribute_map: next });
                  }}
                />
              </td>
            </tr>
          ))}
        </tbody>
      </table>

      {/* Phase 3.C: kind-specific binding hints. Optional — leaving them blank
          falls back to source-spec config (CSV) or auto-`SELECT *` (SQL). */}
      <details style={{ marginTop: 8, fontSize: 11 }}>
        <summary style={{ cursor: "pointer", color: "var(--ink-soft)" }}>
          Advanced: kind-specific binding (table / SQL / HTTP path)
        </summary>
        <div style={{ display: "flex", flexDirection: "column", gap: 6, padding: "6px 0" }}>
          <label style={{ display: "flex", alignItems: "center", gap: 6 }}>
            <span style={{ width: 110, color: "var(--ink-soft)" }}>table (SQL):</span>
            <input
              value={binding.table || ""}
              placeholder="prior_cases"
              onChange={(e) => onChange({ ...binding, table: e.target.value || null })}
              style={{ flex: 1, fontSize: 11 }}
            />
          </label>
          <label style={{ display: "flex", flexDirection: "column", gap: 4 }}>
            <span style={{ color: "var(--ink-soft)" }}>
              query_template (SQL — overrides <code>table</code>; uses <code>:named</code> params):
            </span>
            <textarea
              value={binding.query_template || ""}
              placeholder={"SELECT … FROM prior_cases WHERE scenario_id = :scenario_id LIMIT :max_results"}
              onChange={(e) => onChange({ ...binding, query_template: e.target.value || null })}
              rows={2}
              style={{ fontSize: 11, fontFamily: "monospace", boxSizing: "border-box" }}
            />
          </label>
          <label style={{ display: "flex", alignItems: "center", gap: 6 }}>
            <span style={{ width: 110, color: "var(--ink-soft)" }}>http path:</span>
            <input
              value={binding.http_path_template || ""}
              placeholder="/items/{id}"
              onChange={(e) => onChange({ ...binding, http_path_template: e.target.value || null })}
              style={{ flex: 1, fontSize: 11 }}
            />
          </label>
        </div>
      </details>
    </div>
  );
}

const th: React.CSSProperties = {
  textAlign: "left",
  padding: "4px 6px",
  borderBottom: "1px solid var(--border)",
  color: "var(--ink-soft)",
  fontWeight: 600,
};
const td: React.CSSProperties = { padding: "4px 6px", verticalAlign: "middle" };

function ColumnPicker({
  value,
  candidates,
  onChange,
}: {
  value: string;
  candidates: string[];
  onChange: (v: string) => void;
}) {
  // Always allow free-text entry too — schemas may not always be available
  const inList = !value || candidates.includes(value);
  return (
    <div style={{ display: "flex", gap: 4 }}>
      {candidates.length > 0 ? (
        <select
          value={inList ? value : ""}
          onChange={(e) => onChange(e.target.value)}
          style={{ flex: 1, fontSize: 11 }}
        >
          <option value="">(none)</option>
          {candidates.map((c) => (
            <option key={c} value={c}>
              {c}
            </option>
          ))}
        </select>
      ) : (
        <input
          value={value}
          onChange={(e) => onChange(e.target.value)}
          placeholder="(column name)"
          style={{ flex: 1, fontSize: 11 }}
        />
      )}
    </div>
  );
}

// =============================================================================
// QueryView — NL + structured ontology query playground
// =============================================================================
type QueryMode = "nl" | "structured";

function QueryView({
  ontologyId,
  classes,
  hasMapping,
}: {
  ontologyId: string;
  classes: OntologyClassDetail[];
  hasMapping: boolean;
}) {
  const [mode, setMode] = useState<QueryMode>("nl");
  const [prompt, setPrompt] = useState("");
  const [structClass, setStructClass] = useState<string>(classes[0]?.name || "");
  const [whereJson, setWhereJson] = useState<string>("{}");
  const [maxResults, setMaxResults] = useState<number>(20);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [result, setResult] = useState<OntologyQueryResult | null>(null);

  const exampleNLPrompts = buildExamplePrompts(classes);

  const onRun = async () => {
    setError(null);
    setResult(null);
    setBusy(true);
    try {
      let r: OntologyQueryResult;
      if (mode === "nl") {
        r = await api.runNLOntologyQuery({
          ontology: ontologyId,
          prompt,
          max_results: maxResults,
        });
      } else {
        let where: Record<string, unknown> = {};
        try {
          where = whereJson.trim() ? JSON.parse(whereJson) : {};
        } catch (e) {
          throw new Error(`where clause is not valid JSON: ${(e as Error).message}`);
        }
        r = await api.runStructuredOntologyQuery({
          ontology: ontologyId,
          class: structClass,
          where,
          max_results: maxResults,
        });
      }
      setResult(r);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  };

  return (
    <div style={{ paddingTop: 12 }}>
      <div style={{ fontSize: 12, color: "var(--ink-soft)", marginBottom: 10, lineHeight: 1.5 }}>
        Run an ad-hoc query against this ontology. Results are merged from
        every source the mapping covers — each fact carries{" "}
        <code>via_source_binding</code> so you can see which source
        answered. The same OntologyResolver runs here and inside scenario
        binders.
      </div>

      {!hasMapping && (
        <div
          style={{
            padding: 10,
            marginBottom: 10,
            border: "1px solid var(--amber)",
            background: "rgba(214,158,46,0.08)",
            borderRadius: 4,
            fontSize: 12,
          }}
        >
          ⚠ This ontology has no mapping yet. Queries will fail with
          "no source bindings" until you save one in the Mappings tab.
        </div>
      )}

      <div style={{ display: "flex", gap: 4, marginBottom: 10 }}>
        <ModeButton active={mode === "nl"} onClick={() => setMode("nl")}>
          Natural language
        </ModeButton>
        <ModeButton active={mode === "structured"} onClick={() => setMode("structured")}>
          Structured form
        </ModeButton>
      </div>

      {mode === "nl" && (
        <div style={{ marginBottom: 10 }}>
          <textarea
            value={prompt}
            onChange={(e) => setPrompt(e.target.value)}
            placeholder={exampleNLPrompts[0] || "Ask a question about this ontology…"}
            rows={2}
            style={{
              width: "100%",
              fontSize: 13,
              padding: 8,
              fontFamily: "inherit",
              boxSizing: "border-box",
            }}
          />
          {exampleNLPrompts.length > 0 && (
            <div style={{ marginTop: 4, fontSize: 11, color: "var(--ink-soft)" }}>
              Try:{" "}
              {exampleNLPrompts.map((p, i) => (
                <span key={i}>
                  {i > 0 && " · "}
                  <button
                    onClick={() => setPrompt(p)}
                    style={{
                      background: "none",
                      border: "none",
                      padding: 0,
                      color: "var(--cyan)",
                      cursor: "pointer",
                      textDecoration: "underline",
                      fontSize: 11,
                    }}
                  >
                    {p}
                  </button>
                </span>
              ))}
            </div>
          )}
        </div>
      )}

      {mode === "structured" && (
        <div style={{ marginBottom: 10, display: "flex", flexDirection: "column", gap: 6 }}>
          <label style={{ fontSize: 12 }}>
            Class:{" "}
            <select
              value={structClass}
              onChange={(e) => setStructClass(e.target.value)}
              style={{ fontSize: 12 }}
            >
              {classes.map((c) => (
                <option key={c.name} value={c.name}>
                  {c.name}
                </option>
              ))}
            </select>
          </label>
          <label style={{ fontSize: 12 }}>
            Where (JSON):
            <textarea
              value={whereJson}
              onChange={(e) => setWhereJson(e.target.value)}
              placeholder='{"product_id": "P-EL-9001"}'
              rows={2}
              style={{
                width: "100%",
                fontSize: 12,
                padding: 6,
                fontFamily: "monospace",
                boxSizing: "border-box",
                marginTop: 4,
              }}
            />
          </label>
          <div style={{ fontSize: 11, color: "var(--ink-soft)" }}>
            Keys are ontology attribute names; the resolver translates them
            to source columns via the mapping. Empty <code>{"{}"}</code>{" "}
            returns all rows (up to max_results).
          </div>
        </div>
      )}

      <div style={{ display: "flex", gap: 8, alignItems: "center", marginBottom: 12 }}>
        <button onClick={onRun} disabled={busy || (mode === "nl" && !prompt.trim())}>
          {busy ? "Running…" : "Run query"}
        </button>
        <label style={{ fontSize: 11 }}>
          Max results:{" "}
          <input
            type="number"
            value={maxResults}
            min={1}
            max={200}
            onChange={(e) => setMaxResults(Math.max(1, Math.min(200, Number(e.target.value) || 1)))}
            style={{ width: 60, fontSize: 11 }}
          />
        </label>
      </div>

      {error && <div className="ds-error">{error}</div>}

      {result && <ResultsPanel result={result} />}
    </div>
  );
}

function ModeButton({ active, onClick, children }: { active: boolean; onClick: () => void; children: React.ReactNode }) {
  return (
    <button
      onClick={onClick}
      style={{
        background: active ? "var(--cyan)" : "transparent",
        color: active ? "white" : "var(--ink)",
        border: "1px solid var(--cyan)",
        padding: "4px 10px",
        fontSize: 12,
        cursor: "pointer",
        borderRadius: 3,
      }}
    >
      {children}
    </button>
  );
}

function buildExamplePrompts(classes: OntologyClassDetail[]): string[] {
  if (classes.length === 0) return [];
  const out: string[] = [];
  // Pick the first 2 classes; build a "show me <plural>" prompt for each.
  for (const c of classes.slice(0, 2)) {
    const plural = c.name.toLowerCase() + (c.name.toLowerCase().endsWith("s") ? "" : "s");
    out.push(`show me ${plural}`);
  }
  return out;
}

function ResultsPanel({ result }: { result: OntologyQueryResult }) {
  return (
    <div style={{ marginTop: 4 }}>
      <div
        style={{
          fontSize: 12,
          padding: 8,
          background: "rgba(0,201,183,0.05)",
          borderLeft: "3px solid var(--cyan)",
          marginBottom: 8,
        }}
      >
        <strong>{result.fact_count}</strong> fact
        {result.fact_count === 1 ? "" : "s"} returned for{" "}
        <code>
          {result.ontology}.{result.class}
        </code>
        {result.llm && (
          <span style={{ marginLeft: 8, color: "var(--ink-soft)" }}>
            (parsed by <code>{result.llm}</code>)
          </span>
        )}
        {Object.keys(result.where).length > 0 && (
          <div style={{ fontSize: 11, color: "var(--ink-soft)", marginTop: 4 }}>
            where = <code>{JSON.stringify(result.where)}</code>
          </div>
        )}
      </div>
      {result.fact_count === 0 ? (
        <div style={{ fontSize: 12, color: "var(--ink-soft)", padding: 12, textAlign: "center" }}>
          No matching rows. Try widening the filter or check that the mapping
          covers a source with this data.
        </div>
      ) : (
        <table style={{ width: "100%", fontSize: 11, borderCollapse: "collapse" }}>
          <thead>
            <tr>
              <th style={resTh}>id</th>
              <th style={resTh}>title</th>
              <th style={resTh}>summary</th>
              <th style={resTh}>source</th>
            </tr>
          </thead>
          <tbody>
            {result.facts.map((f, i) => (
              <tr key={i}>
                <td style={resTd}>
                  <code>{f.id}</code>
                </td>
                <td style={resTd}>{f.title || ""}</td>
                <td style={resTd} title={f.summary || ""}>
                  {(f.summary || "").length > 80
                    ? (f.summary || "").slice(0, 80) + "…"
                    : f.summary || ""}
                </td>
                <td style={resTd}>
                  <code style={{ fontSize: 10 }}>{f.source}</code>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  );
}

const resTh: React.CSSProperties = {
  textAlign: "left",
  padding: "6px 8px",
  borderBottom: "1px solid var(--border)",
  color: "var(--ink-soft)",
  fontWeight: 600,
};
const resTd: React.CSSProperties = {
  padding: "6px 8px",
  borderBottom: "1px solid var(--border)",
  verticalAlign: "top",
};

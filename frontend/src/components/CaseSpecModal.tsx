import { useEffect, useMemo, useState } from "react";
import * as api from "../api";
import { CaseFull } from "../types";

// Read-only "what spec drove this case?" viewer. Two humanised tabs:
//   - Scenario: title, mode, matched-because, stages with their ontology
//     queries + hand-authored facts, outcomes, rationale reasons,
//     closing-message previews.
//   - Ontology: only the classes this case actually used, each with
//     attributes / relations / mapping (data source + Cypher template
//     with light syntax highlighting).
//
// Opened from the status-bar "Case spec" button or contextually via the
// `open-case-spec` window event (dispatched by the side-legend ⓘ button
// or by clicking the Scenario node in the platform-flow modal).
export function CaseSpecModal({
  active,
  initialTab,
  initialAnchor,
  onClose,
}: {
  active: CaseFull;
  initialTab?: "scenario" | "ontology";
  initialAnchor?: string;
  onClose: () => void;
}) {
  const [tab, setTab] = useState<"scenario" | "ontology">(initialTab || "scenario");
  const [full, setFull] = useState<any | null>(null);
  const [error, setError] = useState<string | null>(null);

  // Load the full parsed scenario dict (stages, outcomes, closing_msgs).
  useEffect(() => {
    if (!active.scenario_id) return;
    let cancelled = false;
    // Pin to the case's recorded version when present, so a later edit
    // to the live scenario doesn't change what we render here. Falls
    // back to the live full spec for cases created before versioning.
    const opts = active.scenario_version != null
      ? { version: active.scenario_version }
      : {};
    api
      .getScenarioFull(active.scenario_id, opts)
      .then((d) => { if (!cancelled) setFull(d); })
      .catch((e) => { if (!cancelled) setError((e as Error).message); });
    return () => { cancelled = true; };
  }, [active.scenario_id, active.scenario_version]);

  // Esc closes the modal.
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => { if (e.key === "Escape") onClose(); };
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [onClose]);

  // When an anchor + ontology tab were requested (e.g. legend ⓘ click),
  // scroll the section into view + briefly highlight it after the full
  // spec has loaded.
  useEffect(() => {
    if (tab !== "ontology" || !initialAnchor || !full) return;
    const t = setTimeout(() => {
      const el = document.getElementById(initialAnchor);
      if (el) {
        el.scrollIntoView({ behavior: "smooth", block: "start" });
        el.classList.add("spec-anchor-flash");
        setTimeout(() => el.classList.remove("spec-anchor-flash"), 1600);
      }
    }, 80);
    return () => clearTimeout(t);
  }, [tab, initialAnchor, full]);

  const title = active.scenario?.title || active.scenario_id || "Case spec";

  return (
    <div
      className="modal-backdrop case-spec-backdrop"
      onClick={(e) => e.target === e.currentTarget && onClose()}
    >
      <div className="ds-modal case-spec-modal" style={{ maxWidth: 980, width: "92vw" }}>
        <div className="ds-header">
          <div>
            <div className="ds-eyebrow">
              Case spec · {active.scenario_id}
              {active.scenario_version != null && (
                <span className="case-spec-version-pill">
                  Ran against v{active.scenario_version}
                </span>
              )}
            </div>
            <div className="ds-title">{title}</div>
          </div>
          <button className="teams-close" onClick={onClose}>×</button>
        </div>

        <div className="case-spec-tabs">
          <button
            type="button"
            className={`case-spec-tab${tab === "scenario" ? " active" : ""}`}
            onClick={() => setTab("scenario")}
          >Scenario</button>
          <button
            type="button"
            className={`case-spec-tab${tab === "ontology" ? " active" : ""}`}
            onClick={() => setTab("ontology")}
          >Ontology</button>
        </div>

        {error && <div className="ds-error" style={{ margin: 16 }}>{error}</div>}
        {!full && !error && (
          <div className="case-spec-loading">Loading the scenario spec…</div>
        )}

        {full && tab === "scenario" && <ScenarioTab full={full} active={active} />}
        {full && tab === "ontology" && <OntologyTab full={full} active={active} />}
      </div>
    </div>
  );
}

// =============================================================================
// Scenario tab
// =============================================================================
function ScenarioTab({ full, active }: { full: any; active: CaseFull }) {
  const matchKeywords: string[] = full.match_keywords || [];
  const stages = full.stages || {};
  const outcomes = full.outcomes || {};
  const closing = full.closing_messages || {};
  const rationale = full.rationale_reasons || {};

  const mode = full.autonomous ? "Autonomous" : "Human-in-the-loop";
  const reviewer = full.reviewer_role?.label
    ? `${full.reviewer_role.label} · ${full.reviewer_role.name || ""}`
    : null;

  return (
    <div className="case-spec-body">
      {/* ---------- Overview prose ---------- */}
      <div className="spec-section">
        <p className="spec-intro">
          This is the recipe the platform followed for your case. It
          describes the kind of question the agent thinks you're asking,
          the steps it takes to assemble evidence, the choices the
          reviewer has, and the message the case closes with.
        </p>
        <div className="spec-summary-grid">
          <Field label="Mode" value={mode} />
          {full.domain && <Field label="Domain" value={full.domain} />}
          {reviewer && <Field label="Reviewer" value={reviewer} />}
          {full.action_type && <Field label="Action type" value={full.action_type} />}
          {full.teams_channel && <Field label="Teams channel" value={full.teams_channel} />}
        </div>
      </div>

      {/* ---------- Matched because ---------- */}
      {(matchKeywords.length > 0 || full.interpreted_as) && (
        <div className="spec-section">
          <div className="spec-section-label">Matched because</div>
          <p className="spec-intro">
            The agent picks a scenario by comparing your prompt to a
            list of keywords. These are the words and phrases that
            triggered this scenario. The "interpreted as" line is how
            the agent summarised your prompt before doing any work.
          </p>
          {matchKeywords.length > 0 && (
            <div className="spec-keyword-chips">
              {matchKeywords.map((k) => (
                <span className="spec-keyword-chip" key={k}>{k}</span>
              ))}
            </div>
          )}
          {full.interpreted_as && (
            <div className="spec-interpreted">
              <span className="spec-meta">Interpreted as:</span>{" "}
              "{full.interpreted_as}"
            </div>
          )}
        </div>
      )}

      {/* ---------- Stages ---------- */}
      <div className="spec-section">
        <div className="spec-section-label">Stages</div>
        <p className="spec-intro">
          Stages are the steps the agent walks before showing you a
          decision card. Each stage either pulls facts from the
          ontology (live data) or carries hand-authored facts (policy
          text, actor scope). Click any stage to see what runs there.
        </p>
        {Object.entries(stages).map(([name, body]: [string, any]) => (
          <StageBlock
            key={name}
            stageName={name}
            body={body}
            actionPayload={full.action_payload || {}}
          />
        ))}
      </div>

      {/* ---------- Outcomes ---------- */}
      {Object.keys(outcomes).length > 0 && (
        <div className="spec-section">
          <div className="spec-section-label">Outcomes</div>
          <p className="spec-intro">
            Once the reviewer decides, one of these three outcomes
            lands on the case. The headline is what the reviewer (and
            their manager) sees on the case card; the detail is the
            longer narrative captured for the audit trail.
          </p>
          <div className="spec-outcomes">
            {Object.entries(outcomes).map(([k, o]: [string, any]) => (
              <div className={`spec-outcome spec-outcome-${k}`} key={k}>
                <div className="spec-outcome-key">{humanDecision(k)}</div>
                <div className="spec-outcome-headline">{o.headline}</div>
                <div className="spec-outcome-detail">{o.detail}</div>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* ---------- Rationale reasons ---------- */}
      {(rationale.reject || rationale.request_more_info) && (
        <div className="spec-section">
          <div className="spec-section-label">Reviewer rationale options</div>
          <p className="spec-intro">
            When the reviewer chooses Reject or Request more info,
            these are the pre-set reasons in the dropdown — calibrated
            so reviewers can act fast without writing rationale from
            scratch. They can still type a free-form reason if none of
            these fits.
          </p>
          {rationale.reject && (
            <div className="spec-rationale-group">
              <div className="spec-rationale-key">Reject</div>
              <ul className="spec-rationale-list">
                {rationale.reject.map((r: string, i: number) => <li key={i}>{r}</li>)}
              </ul>
            </div>
          )}
          {rationale.request_more_info && (
            <div className="spec-rationale-group">
              <div className="spec-rationale-key">Request more info</div>
              <ul className="spec-rationale-list">
                {rationale.request_more_info.map((r: string, i: number) => <li key={i}>{r}</li>)}
              </ul>
            </div>
          )}
        </div>
      )}

      {/* ---------- Closing messages ---------- */}
      {Object.keys(closing).length > 0 && (
        <div className="spec-section">
          <div className="spec-section-label">Closing message templates</div>
          <p className="spec-intro">
            After the decision, one of these messages appears as the
            case's closing message. Anything in <code>{`{curly braces}`}</code>{" "}
            is a placeholder — the reviewer's typed rationale gets
            substituted into <code>{`{rationale}`}</code> at decision-
            time.
          </p>
          {Object.entries(closing).map(([k, msg]: [string, any]) => (
            <div className="spec-closing" key={k}>
              <div className="spec-closing-key">{humanDecision(k)}</div>
              <div
                className="spec-closing-body"
                dangerouslySetInnerHTML={{ __html: highlightTemplate(String(msg)) }}
              />
            </div>
          ))}
        </div>
      )}

      {/* ---------- Footer ---------- */}
      <div className="spec-footer">
        <span className="spec-meta">
          Source · {active.scenario_id}.yaml
          {full.is_builtin ? " (built-in scenario)" : " (custom scenario)"}
        </span>
      </div>
    </div>
  );
}

function StageBlock({
  stageName,
  body,
  actionPayload,
}: {
  stageName: string;
  body: any;
  actionPayload: Record<string, any>;
}) {
  const queries = (body?.ontology_queries || []) as Array<any>;
  const facts = (body?.facts || []) as Array<any>;
  return (
    <details className="spec-stage" open>
      <summary className="spec-stage-summary">
        <span className="spec-stage-name">{humanStage(stageName)}</span>
        <span className="spec-stage-meta">
          {queries.length > 0 && `${queries.length} ontology quer${queries.length === 1 ? "y" : "ies"}`}
          {queries.length > 0 && facts.length > 0 && " · "}
          {facts.length > 0 && `${facts.length} hand-authored fact${facts.length === 1 ? "" : "s"}`}
          {body?.binder && (
            <>
              {" "}<span className="spec-meta">· binder {String(body.binder)}</span>
            </>
          )}
        </span>
      </summary>
      {queries.length > 0 && (
        <div className="spec-stage-body">
          {queries.map((q, i) => (
            <div className="spec-query" key={i}>
              <div className="spec-query-head">
                <span className="spec-meta">{q.ontology}</span>
                <span className="spec-class-name">{q.class}</span>
                {q.max_results && (
                  <span className="spec-meta">· max {q.max_results}</span>
                )}
              </div>
              {q.purpose && <div className="spec-query-purpose">{q.purpose}</div>}
              <WhereTable where={q.where || {}} actionPayload={actionPayload} />
            </div>
          ))}
        </div>
      )}
      {facts.length > 0 && (
        <div className="spec-stage-body">
          <div className="spec-section-label small">Hand-authored facts (no query)</div>
          {facts.map((f, i) => (
            <div className="spec-fact" key={i}>
              <div className="spec-query-head">
                <span className="spec-meta">{f.source}</span>
                <span className="spec-class-name">{f.ontology_type}</span>
                <span className="spec-fact-id">{f.id}</span>
              </div>
              {f.title && <div className="spec-fact-title">{f.title}</div>}
              {f.payload && <div className="spec-fact-payload">{f.payload}</div>}
            </div>
          ))}
        </div>
      )}
    </details>
  );
}

function WhereTable({
  where,
  actionPayload,
}: {
  where: Record<string, any>;
  actionPayload: Record<string, any>;
}) {
  const rows = Object.entries(where);
  if (rows.length === 0) return null;
  return (
    <div className="spec-where">
      <div className="spec-where-label">where:</div>
      <table className="spec-where-table">
        <tbody>
          {rows.map(([key, val]) => {
            const resolved =
              typeof val === "string" && val.startsWith(":")
                ? actionPayload[val.slice(1)]
                : undefined;
            return (
              <tr key={key}>
                <td className="spec-where-key">{key}</td>
                <td className="spec-where-val">{JSON.stringify(val)}</td>
                {resolved !== undefined && (
                  <td className="spec-where-resolved">
                    → <code>{JSON.stringify(resolved)}</code>
                  </td>
                )}
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

// =============================================================================
// Ontology tab
// =============================================================================
function OntologyTab({ full, active: _active }: { full: any; active: CaseFull }) {
  // Walk the scenario stages → collect distinct (ontology, class) pairs.
  const usedClasses = useMemo(() => {
    const out: { ontology: string; class: string }[] = [];
    const seen = new Set<string>();
    for (const stage of Object.values(full.stages || {}) as any[]) {
      for (const q of stage?.ontology_queries || []) {
        const key = `${q.ontology}::${q.class}`;
        if (!seen.has(key)) {
          seen.add(key);
          out.push({ ontology: q.ontology, class: q.class });
        }
      }
    }
    return out;
  }, [full]);

  const ontologyIds = useMemo(
    () => Array.from(new Set(usedClasses.map((c) => c.ontology))),
    [usedClasses],
  );

  const [classDocs, setClassDocs] = useState<Record<string, any[]>>({});
  const [mappingDocs, setMappingDocs] = useState<Record<string, any>>({});
  const [loadErr, setLoadErr] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    Promise.all(
      ontologyIds.map(async (id) => {
        const [classes, mappings] = await Promise.all([
          api.getOntologyClasses(id).catch(() => []),
          api.getMappings(id).catch(() => ({ ontology_id: id, mappings: {} })),
        ]);
        return { id, classes, mappings };
      }),
    )
      .then((rows) => {
        if (cancelled) return;
        const c: Record<string, any[]> = {};
        const m: Record<string, any> = {};
        for (const r of rows) {
          c[r.id] = r.classes as any[];
          m[r.id] = r.mappings;
        }
        setClassDocs(c);
        setMappingDocs(m);
      })
      .catch((e) => { if (!cancelled) setLoadErr((e as Error).message); });
    return () => { cancelled = true; };
  }, [ontologyIds.join("|")]);

  return (
    <div className="case-spec-body">
      <div className="spec-section">
        <div className="spec-section-label">
          Classes used in this case ({usedClasses.length})
        </div>
        <p className="spec-intro">
          An "ontology class" is a concept the platform understands —
          a Supplier, a SanctionsProximity trail, a Carrier. Each class
          has a set of attributes (its data shape) and is backed by one
          or more data sources. The classes below are the ones this
          case actually used; they appear in the order the agent
          queried them.
        </p>
        {loadErr && <div className="ds-error">{loadErr}</div>}
        {usedClasses.map((cu, idx) => {
          const klass = (classDocs[cu.ontology] || []).find((c: any) => c.name === cu.class);
          const mapping = mappingDocs[cu.ontology]?.mappings?.[cu.class];
          return (
            <OntologyClassCard
              key={`${cu.ontology}-${cu.class}`}
              index={idx + 1}
              ontologyId={cu.ontology}
              className={cu.class}
              klass={klass}
              mapping={mapping}
            />
          );
        })}
      </div>
    </div>
  );
}

function OntologyClassCard({
  index,
  ontologyId,
  className,
  klass,
  mapping,
}: {
  index: number;
  ontologyId: string;
  className: string;
  klass: any | undefined;
  mapping: any | undefined;
}) {
  const attrs = (klass?.attributes || []) as Array<any>;
  const relations = (klass?.relations || []) as Array<any>;
  const sources = (mapping?.sources || []) as Array<any>;
  return (
    <details
      className="spec-ontology-class"
      id={`spec-class-${className}`}
      open
    >
      <summary className="spec-class-summary">
        <span className="spec-class-index">{index}.</span>
        <span className="spec-class-name">{className}</span>
        <span className="spec-meta">· {ontologyId}</span>
        {sources[0]?.data_source && (
          <span className="spec-meta">· {sources[0].data_source}</span>
        )}
      </summary>
      {(klass?.plain_description || klass?.description) ? (
        <div className="spec-class-description">
          {klass.plain_description || klass.description}
        </div>
      ) : (
        <div className="spec-class-description">
          {className} is one of the concepts this scenario asks the
          platform to gather facts about. The agent runs an ontology
          query for it during the case, and the results show up in the
          evidence map under this name.
        </div>
      )}
      {attrs.length > 0 && (
        <div className="spec-class-block">
          <div className="spec-section-label small">Attributes</div>
          <p className="spec-class-note">
            Each instance of {className} carries these fields. The one
            marked <em>id</em> is the unique identifier the platform
            uses to refer to that instance.
          </p>
          <table className="spec-attr-table">
            <tbody>
              {attrs.map((a, i) => (
                <tr key={i}>
                  <td className="spec-attr-name">
                    {a.name}
                    {a.identifier && <span className="spec-id-badge">id</span>}
                  </td>
                  <td className="spec-attr-type">{a.type}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      {relations.length > 0 && (
        <div className="spec-class-block">
          <div className="spec-section-label small">Relations</div>
          <p className="spec-class-note">
            Connections to other concepts in the ontology. Reading
            left-to-right: a {className} can have these relationships.
          </p>
          <ul className="spec-relation-list">
            {relations.map((r, i) => (
              <li key={i}>
                a {className} <strong>{r.name}</strong>{" "}
                {r.cardinality === "0..*" || r.cardinality === "1..*"
                  ? "many"
                  : "a"}{" "}
                <strong>{r.target}</strong>
                {r.cardinality ? <span className="spec-meta"> · {r.cardinality}</span> : null}
              </li>
            ))}
          </ul>
        </div>
      )}
      {sources.length > 0 && (
        <div className="spec-class-block">
          <div className="spec-section-label small">Where the data lives</div>
          <p className="spec-class-note">
            When the agent asks for {className} instances, it looks
            here{sources.length > 1 ? " (multiple sources combined):" : ":"}
          </p>
          {sources.map((s, i) => (
            <div className="spec-mapping" key={i}>
              <div className="spec-mapping-head">
                <span className="spec-meta">data source:</span>{" "}
                <strong>{s.data_source}</strong>
                {s.identifier_column && (
                  <>
                    {" "}· <span className="spec-meta">identifier column:</span>{" "}
                    <strong>{s.identifier_column}</strong>
                  </>
                )}
              </div>
              {s.attribute_map && Object.keys(s.attribute_map).length > 0 && (
                <>
                  <p className="spec-class-note">
                    Ontology attributes map to source columns like this:
                  </p>
                  <table className="spec-attr-map">
                    <thead>
                      <tr><th>Ontology</th><th>Source column</th></tr>
                    </thead>
                    <tbody>
                      {Object.entries(s.attribute_map).map(([k, v]) => (
                        <tr key={k}><td>{k}</td><td>{String(v)}</td></tr>
                      ))}
                    </tbody>
                  </table>
                </>
              )}
            </div>
          ))}
        </div>
      )}
    </details>
  );
}

// =============================================================================
// Tiny helpers
// =============================================================================
function Field({ label, value }: { label: string; value: string }) {
  return (
    <div className="spec-field">
      <div className="spec-field-label">{label}</div>
      <div className="spec-field-value">{value}</div>
    </div>
  );
}

function humanStage(stage: string): string {
  switch (stage) {
    case "intake": return "Stage 0 · Intake";
    case "agent_intake": return "Stage 1 · Policy & scope";
    case "proposal": return "Stage 2 · Agent gathered";
    case "review": return "Stage 3 · For your decision";
    case "complete": return "Stage 4 · Complete";
    case "binding": return "Binding";
    default: return stage;
  }
}

function humanDecision(k: string): string {
  switch (k) {
    case "approve": return "Approve";
    case "reject": return "Reject";
    case "request_more_info": return "Request more info";
    default: return k;
  }
}

// Light highlighter for closing-message templates. Currently highlights
// the {rationale} / {follow_up} placeholder spans so reviewers can see
// what gets interpolated at decision-time.
function highlightTemplate(html: string): string {
  return html.replace(
    /\{(rationale|follow_up|reason|rationale_text)\}/g,
    '<span class="spec-template-token">{$1}</span>',
  );
}

// (Cypher templates intentionally hidden from this view per spec —
// reviewers shouldn't have to read code to understand the case.
// They're still visible in the raw YAML files for engineers / auditors.)

import { useState } from "react";
import { CaseFull, StagePayload } from "../types";

// Plain-English labels for the operator. Raw stage names (agent_intake /
// proposal / review) survive in the tooltip via title= for engineers.
const STAGE_LABEL: Record<string, string> = {
  agent_intake: "Policy & scope",
  proposal: "Agent gathered",
  review: "For your decision",
};

export function Envelope({ active }: { active: CaseFull | null }) {
  const stages = active?.stages ?? [];
  const factCount = stages.reduce((acc, s) => acc + s.facts.length, 0);
  const [glossaryOpen, setGlossaryOpen] = useState(false);

  return (
    <div className="envelope-wrapper">
      <div className="envelope-eyebrow">
        <div className="envelope-title">
          What the agent gathered
          <button
            type="button"
            className="glossary-trigger"
            onClick={() => setGlossaryOpen(true)}
            aria-label="Open glossary — what do the badges, source pills, and stage labels mean?"
            title="What do these labels mean?"
          >
            ?
          </button>
        </div>
        <div className="envelope-counter">
          <strong>{stages.length}</strong> stages · <strong>{factCount}</strong> facts
        </div>
      </div>
      <div className="envelope">
        {stages.length === 0 && <div className="envelope-empty">Awaiting first binding…</div>}
        {stages.map((s, idx) => (
          <StageBlock key={s.stage} stage={s} index={idx} />
        ))}
      </div>
      {glossaryOpen && <GlossaryModal onClose={() => setGlossaryOpen(false)} />}
    </div>
  );
}

function StageBlock({ stage, index }: { stage: StagePayload; index: number }) {
  // Each stage starts expanded (the user wants to see the work). Click the
  // header to collapse. Inside, the facts grid is capped with internal scroll
  // so a 30-fact port-disruption stage doesn't push the page below the fold.
  const [open, setOpen] = useState(true);
  return (
    <div className={`stage-block${open ? " stage-open" : " stage-collapsed"}`}>
      <button
        type="button"
        className="stage-header"
        onClick={() => setOpen((v) => !v)}
        aria-expanded={open}
        title={`Raw stage id: ${stage.stage} · binder ${stage.binder}`}
      >
        <div className="stage-name">
          <span className="stage-chevron" aria-hidden="true">▸</span>
          Stage {index + 1} · {STAGE_LABEL[stage.stage] ?? stage.stage}
          <span className="stage-fact-count">({stage.facts.length})</span>
        </div>
        <div className="stage-binder">{stage.binder}</div>
      </button>
      {open && <FactsGrid facts={stage.facts} />}
    </div>
  );
}

// Cap large stages (e.g. port-disruption returns 30 shipments) at 12 visible
// facts with a "+ N more" expander. Keeps scroll cost predictable.
const FACT_PREVIEW_LIMIT = 12;

function FactsGrid({ facts }: { facts: StagePayload["facts"] }) {
  const [showAll, setShowAll] = useState(false);
  const overflow = facts.length > FACT_PREVIEW_LIMIT;
  const visible = showAll || !overflow ? facts : facts.slice(0, FACT_PREVIEW_LIMIT);
  return (
    <>
      <div className="facts-grid">
        {visible.map((f, i) => (
          <FactCard key={`${f.source}-${f.id}-${i}`} fact={f} index={i} />
        ))}
      </div>
      {overflow && (
        <button
          type="button"
          className="facts-show-more"
          onClick={() => setShowAll((v) => !v)}
        >
          {showAll
            ? `Show fewer (collapse to ${FACT_PREVIEW_LIMIT})`
            : `Show all ${facts.length} (${facts.length - FACT_PREVIEW_LIMIT} more)`}
        </button>
      )}
    </>
  );
}

// Marker words that signal a fact needs visual emphasis. Matched
// case-insensitively against title + summary. Keep this small — every keyword
// adds noise to facts that happen to mention the word.
const HIGH_RISK_MARKERS = ["delayed", "customs_hold", "damage", "vessel_change", "exception", "critical"];
const HIGH_CONGESTION_MARKERS = ["congestion HIGH", "HIGH (berth", "labor action true", "weather true"];
const PREMIUM_MARKERS = ["SLA premium", "premium ·"];

function factAccent(text: string): "" | "risk" | "warning" | "premium" {
  const t = text || "";
  if (HIGH_RISK_MARKERS.some((m) => t.toLowerCase().includes(m))) return "risk";
  if (HIGH_CONGESTION_MARKERS.some((m) => t.includes(m))) return "warning";
  if (PREMIUM_MARKERS.some((m) => t.includes(m))) return "premium";
  return "";
}

function FactCard({ fact, index }: { fact: StagePayload["facts"][number]; index: number }) {
  const accent = factAccent(`${fact.title} ${fact.summary}`);
  // Split the pipe-delimited summary into individual chips. Each segment
  // gets a small badge so the eye lands on the data, not a long sentence.
  const chips = (fact.summary || "")
    .split(/\s+·\s+/)
    .map((s) => s.trim())
    .filter(Boolean);
  return (
    <div
      className={`fact${accent ? ` fact-accent-${accent}` : ""}`}
      style={{ animationDelay: `${index * 80}ms` }}
    >
      <div className="fact-source">
        <SourcePill source={fact.source} />
        <span className="fact-ontology-type">{fact.ontology_type}</span>
        {accent === "risk" && (
          <span
            className="fact-accent-badge risk"
            title="EXCEPTION — shipment flagged: delayed, customs hold, damage, vessel change, or port congestion. From the exception_flag column on the shipments table."
          >
            EXCEPTION
          </span>
        )}
        {accent === "warning" && (
          <span
            className="fact-accent-badge warning"
            title="CONGESTED — port-level friction: long berth wait, active labor action, or weather disruption. From the port master (ports.csv)."
          >
            CONGESTED
          </span>
        )}
        {accent === "premium" && (
          <span
            className="fact-accent-badge premium"
            title="PREMIUM SLA — customer order on the highest tier (typically large penalty per day late). From customer_orders.csv."
          >
            PREMIUM SLA
          </span>
        )}
      </div>
      <div className="fact-id">{fact.title}</div>
      <div className="fact-chips">
        {chips.map((c, i) => (
          <span className="fact-chip" key={i}>{c}</span>
        ))}
      </div>
      {fact.uri && (
        <a className="fact-uri" href="#" onClick={(e) => e.preventDefault()}>
          → {fact.uri}
        </a>
      )}
    </div>
  );
}

// Source strings come back as "csv:shipments_csv", "sqlite:logistics_sqlite",
// "kf:graph", etc. Render as a small colored pill: kind on the left, a
// human-friendly source label on the right (we strip the trailing "_csv"
// or "_sqlite" so it reads as a normal name).
function SourcePill({ source }: { source: string }) {
  const [kindRaw, nameRaw] = source.includes(":")
    ? source.split(":", 2)
    : ["source", source];
  const kind = kindRaw.toLowerCase();
  const name = (nameRaw || source)
    .replace(/_csv$/, "")
    .replace(/_sqlite$/, "")
    .replace(/_/g, " ");
  const description = kindDescription(kind);
  return (
    <span
      className={`source-pill source-pill-${kind}`}
      title={`${kindLabel(kind)} · ${description}\nRaw source id: ${source}`}
    >
      <span className="source-pill-kind">{kindLabel(kind)}</span>
      <span className="source-pill-name">{name}</span>
    </span>
  );
}

function kindLabel(kind: string): string {
  switch (kind) {
    case "csv": return "CSV";
    case "sqlite": return "SQLite";
    case "postgres": return "Postgres";
    case "http": return "HTTP";
    case "vector_store": return "Vector";
    case "neo4j": return "Neo4j";
    case "kf": return "Graph";
    case "iam": return "IAM";
    case "tms": return "TMS";
    case "erp": return "ERP";
    case "finance": return "Finance";
    case "governance": return "Governance";
    default: return kind.toUpperCase();
  }
}

function kindDescription(kind: string): string {
  switch (kind) {
    case "csv": return "Flat-file table on disk";
    case "sqlite": return "Embedded relational DB (also a write target for actions)";
    case "postgres": return "Managed relational DB";
    case "http": return "External REST API";
    case "vector_store": return "Semantic-search store (policy / SOP corpus)";
    case "neo4j": return "Graph database";
    case "kf": return "Knowledge-Fabric inline graph fact (policies, baselines)";
    case "iam": return "Identity & Access Management (actor scope / role facts)";
    case "tms": return "Transportation Management System (shipments, lanes)";
    case "erp": return "ERP system (orders, customer master)";
    case "finance": return "Finance system (cost, accruals)";
    case "governance": return "Governance audit store (prior reviewer decisions)";
    default: return "Registered data source";
  }
}

// =============================================================================
// GlossaryModal — one place to look up every label that appears in the
// envelope: fact badges, source pills, stage names, and actor-scope vocabulary.
// Triggered from the "?" icon in the envelope eyebrow.
// =============================================================================
function GlossaryModal({ onClose }: { onClose: () => void }) {
  // Close on Escape.
  if (typeof document !== "undefined") {
    document.onkeydown = (e) => {
      if (e.key === "Escape") onClose();
    };
  }
  return (
    <div className="glossary-backdrop" onClick={onClose}>
      <div className="glossary-modal" onClick={(e) => e.stopPropagation()}>
        <div className="glossary-header">
          <div>
            <div className="glossary-eyebrow">Reference</div>
            <div className="glossary-title">What these labels mean</div>
          </div>
          <button className="glossary-close" onClick={onClose} aria-label="Close">×</button>
        </div>
        <div className="glossary-body">

          <section>
            <h3>Fact badges</h3>
            <p>Coloured accents that flag a fact needing attention.</p>
            <dl className="glossary-dl">
              <dt><span className="fact-accent-badge risk">EXCEPTION</span></dt>
              <dd>Shipment is flagged: <code>delayed</code>, <code>customs_hold</code>, <code>damage</code>, <code>vessel_change</code>, or <code>port_congestion</code>. Sourced from the <code>exception_flag</code> column of <code>shipments.csv</code>; ~15% of seeded rows carry one. Fact card gets a red left border.</dd>
              <dt><span className="fact-accent-badge warning">CONGESTED</span></dt>
              <dd>Port-level operational friction: high berth wait, active labor action, or weather disruption. Sourced from <code>ports.csv</code> (look for <code>congestion HIGH</code> or the labor/weather flags). Amber accent.</dd>
              <dt><span className="fact-accent-badge premium">PREMIUM SLA</span></dt>
              <dd>Customer order on the highest service tier (typically large penalty per day late). Sourced from the <code>sla_tier</code> column of <code>customer_orders.csv</code>. Gold accent. Often paired with the SLA-risk scenario.</dd>
            </dl>
          </section>

          <section>
            <h3>Source pills</h3>
            <p>Every fact carries a pill showing which data source it came from. The left segment is the connector kind, the right segment is the source's friendly name.</p>
            <dl className="glossary-dl">
              <dt><span className="source-pill source-pill-csv"><span className="source-pill-kind">CSV</span><span className="source-pill-name">shipments</span></span></dt>
              <dd>Flat-file table on disk. Read-only.</dd>
              <dt><span className="source-pill source-pill-sqlite"><span className="source-pill-kind">SQLite</span><span className="source-pill-name">logistics</span></span></dt>
              <dd>Embedded relational DB. Also a write target — <code>retender_booking</code> mutates <code>logistics.sqlite</code>.</dd>
              <dt><span className="source-pill source-pill-postgres"><span className="source-pill-kind">Postgres</span><span className="source-pill-name">governance</span></span></dt>
              <dd>Managed relational DB. Same connector pattern as SQLite; swap path is one mapping change.</dd>
              <dt><span className="source-pill source-pill-http"><span className="source-pill-kind">HTTP</span><span className="source-pill-name">jsonplaceholder</span></span></dt>
              <dd>External REST API. Write target for <code>update_eta_to_customer</code>.</dd>
              <dt><span className="source-pill source-pill-vector_store"><span className="source-pill-kind">Vector</span><span className="source-pill-name">policy corpus</span></span></dt>
              <dd>Semantic-search store over policy / SOP markdown excerpts.</dd>
              <dt><span className="source-pill source-pill-neo4j"><span className="source-pill-kind">Neo4j</span><span className="source-pill-name">supply graph</span></span></dt>
              <dd>Graph database for relationship-heavy lookups (Cypher with a read-only safety guard).</dd>
              <dt><span className="source-pill source-pill-kf"><span className="source-pill-kind">Graph</span><span className="source-pill-name">graph</span></span></dt>
              <dd>Knowledge-Fabric inline graph fact — policies, baselines, anything authored directly in a scenario rather than fetched.</dd>
              <dt><span className="source-pill source-pill-iam"><span className="source-pill-kind">IAM</span><span className="source-pill-name">scopes</span></span></dt>
              <dd>Identity & Access Management — the actor's identity and capabilities (see "Actor scopes" below).</dd>
            </dl>
          </section>

          <section>
            <h3>Stage labels</h3>
            <p>Every case moves through up to three stages. Each binds a different slice of context.</p>
            <dl className="glossary-dl">
              <dt><strong>Stage 1 · Policy &amp; scope</strong></dt>
              <dd>Raw name: <code>agent_intake</code>. Binds the active policy + the agent's IAM scopes. Answers: <em>"Is this kind of action permitted, and is this agent allowed to perform it?"</em></dd>
              <dt><strong>Stage 2 · Agent gathered</strong></dt>
              <dd>Raw name: <code>proposal</code>. Binds the operational data the agent needs to either act autonomously or draft a proposal for a reviewer. This is where ontology lookups (Shipment, Booking, Carrier, etc.) run.</dd>
              <dt><strong>Stage 3 · For your decision</strong></dt>
              <dd>Raw name: <code>review</code>. Only present on HITL scenarios. Adds the evidence package a human reviewer needs to judge (prior similar cases, customer SLA, alternate options). The reviewer never sees raw data without this stage's framing.</dd>
            </dl>
          </section>

          <section>
            <h3>Actor scopes</h3>
            <p>The agent acts under a named identity (e.g. <code>agent-logistics-31</code>) with explicit, named capabilities. Think OAuth scopes or AWS IAM policies. Every case records the scopes the agent claimed at execution time — compliance can replay <em>"what was the agent authorized to do when this booking was changed?"</em></p>
            <dl className="glossary-dl">
              <dt><code>logistics.read</code></dt>
              <dd>Look up shipments, carriers, lanes, ports. No side effects. Used by trace / scorecard / port-disruption scenarios.</dd>
              <dt><code>logistics.propose</code></dt>
              <dd>Draft an action (e.g. propose a re-tender) but not execute it. Required by any HITL scenario that ends in human approval.</dd>
              <dt><code>logistics.tender_after_review</code></dt>
              <dd>Execute a booking change ONLY after a human reviewer approves. The actual SQL write only fires when the human clicks Approve.</dd>
              <dt><code>logistics.write_customer_eta</code></dt>
              <dd>Push ETA updates directly to customer systems — the only autonomous-write scope in the current setup. Bounded by guardrail <code>GR-LN-AUTO-ETA-002</code> (variance ≤ 3 days).</dd>
              <dt><code>sc.read / sc.propose / sc.execute_after_review</code></dt>
              <dd>Trade-compliance equivalents. Same propose-then-execute pattern; different domain.</dd>
            </dl>
          </section>

          <section>
            <h3>Confidence labels</h3>
            <p>When the classifier isn't sure, the "Or did you mean…?" row appears with alternatives. Confidence is a 0-1 score from the LLM classifier, rendered as plain English:</p>
            <ul className="glossary-conf-list">
              <li><span className="did-you-mean-conf conf-strong">Strong match</span> — ≥85% confident</li>
              <li><span className="did-you-mean-conf conf-likely">Likely match</span> — 65–84%</li>
              <li><span className="did-you-mean-conf conf-possible">Possible match</span> — 40–64%</li>
              <li><span className="did-you-mean-conf conf-weak">Weak match</span> — &lt;40%</li>
            </ul>
          </section>

        </div>
      </div>
    </div>
  );
}

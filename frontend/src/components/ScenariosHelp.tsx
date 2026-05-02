/**
 * Scenarios Authoring help modal.
 *
 * Mirrors the content of `docs/scenarios.md`. Two sources of truth is fine for
 * the size of this content; the markdown file is canonical (and what you'd
 * link to from a README), this is the in-app reference contextual to the UI.
 */
import { useState } from "react";

type Section = "overview" | "anatomy" | "shapes" | "stages" | "fields" | "examples" | "tips" | "lifecycle";

export function ScenariosHelp({ onClose }: { onClose: () => void }) {
  const [section, setSection] = useState<Section>("overview");

  return (
    <div
      className="modal-backdrop"
      onClick={(e) => e.target === e.currentTarget && onClose()}
    >
      <div className="help-modal">
        <div className="help-header">
          <div>
            <div className="help-eyebrow">Authoring guide</div>
            <div className="help-title">Scenarios</div>
          </div>
          <button className="teams-close" onClick={onClose}>×</button>
        </div>

        <div className="help-layout">
          <nav className="help-nav">
            <button className={section === "overview" ? "active" : ""} onClick={() => setSection("overview")}>
              Overview
            </button>
            <button className={section === "anatomy" ? "active" : ""} onClick={() => setSection("anatomy")}>
              Anatomy
            </button>
            <button className={section === "shapes" ? "active" : ""} onClick={() => setSection("shapes")}>
              HITL vs autonomous
            </button>
            <button className={section === "stages" ? "active" : ""} onClick={() => setSection("stages")}>
              Stage knowledge
            </button>
            <button className={section === "fields" ? "active" : ""} onClick={() => setSection("fields")}>
              Field reference
            </button>
            <button className={section === "examples" ? "active" : ""} onClick={() => setSection("examples")}>
              Examples
            </button>
            <button className={section === "tips" ? "active" : ""} onClick={() => setSection("tips")}>
              Quality tips
            </button>
            <button className={section === "lifecycle" ? "active" : ""} onClick={() => setSection("lifecycle")}>
              Lifecycle
            </button>
            <div className="help-nav-footer">
              Full reference:<br />
              <code>docs/scenarios.md</code>
            </div>
          </nav>

          <div className="help-body">
            {section === "overview" && <Overview />}
            {section === "anatomy" && <Anatomy />}
            {section === "shapes" && <Shapes />}
            {section === "stages" && <StageKnowledge />}
            {section === "fields" && <FieldReference />}
            {section === "examples" && <Examples />}
            {section === "tips" && <QualityTips />}
            {section === "lifecycle" && <Lifecycle />}
          </div>
        </div>
      </div>
    </div>
  );
}

// =============================================================================
// Sections
// =============================================================================
function Overview() {
  return (
    <>
      <h3>What is a scenario?</h3>
      <p>
        A <strong>scenario</strong> is the framework's blueprint for{" "}
        <em>one type of action the agent can take</em>. Think of it as a recipe:
        the operator says something in plain language, the framework matches
        the request to a recipe, follows it step-by-step (binding the right
        knowledge at each stage), runs the action — and either executes
        autonomously or routes through a human reviewer first.
      </p>

      <p className="help-callout">
        <strong>Example.</strong> An operator types "Override the SC-TC-001 block
        on order ORD-44216." The framework matches that to the{" "}
        <code>SC-TC-007</code> scenario (sanctions override). It binds the active
        trade-compliance policy, the agent's IAM scope, the product master record,
        the contract, prior similar overrides, and an applicable SOP — then
        renders all of that as evidence for a compliance officer to review.
      </p>

      <h3>What scenarios do</h3>
      <ol>
        <li>
          <strong>Route prompts.</strong> When the operator types something, the
          classifier scans every scenario's <code>match_keywords</code> and{" "}
          <code>interpreted_as</code> phrasing and picks the best match.
        </li>
        <li>
          <strong>Tell the agent what to read.</strong> Each scenario specifies
          which knowledge gets bound at each stage (intake, proposal, review).
          That knowledge becomes the envelope the reviewer eventually sees.
        </li>
        <li>
          <strong>Decide whether a human needs to look.</strong> Autonomous
          scenarios skip review and execute directly. HITL scenarios stop at
          the review stage and wait for a decision.
        </li>
        <li>
          <strong>Render the right surfaces.</strong> Scenarios determine the
          Teams card title, the rationale-reason chips the reviewer sees, the
          outcome banner, and the closing message the agent says back.
        </li>
      </ol>

      <h3>What scenarios are <em>not</em></h3>
      <ul>
        <li>
          <strong>Not the binders themselves.</strong> Binders are Python code
          ({" "}<code>backend/binders.py</code>); scenarios are YAML data the
          binders read.
        </li>
        <li>
          <strong>Not the agent's reasoning.</strong> The LLM only consults
          scenarios for classification — picking which one the prompt fits.
          The actual action logic is hand-authored.
        </li>
        <li>
          <strong>Not persistent state.</strong> Each case run reads the YAML
          fresh; the data envelope is the case's state, not the YAML.
        </li>
      </ul>

      <h3>Three lifecycle types</h3>
      <ul>
        <li>
          <strong>Built-in</strong> (<code>SC-TC-*</code>, <code>SC-PP-*</code>,{" "}
          <code>SC-LN-*</code>) — committed to the repo, hand-authored, can't be
          deleted via the API.
        </li>
        <li>
          <strong>Auto-generated</strong> (<code>SC-AUTO-&lt;source&gt;</code>) —
          created automatically when an operator-registered data source is
          added; removed when the source is removed.
        </li>
        <li>
          <strong>Custom</strong> (<code>SC-CUSTOM-&lt;slug&gt;</code>) — created
          via the Save-as-scenario form in the Query playground. Persist until
          deleted.
        </li>
      </ul>

      <p className="help-callout">
        <strong>Where to start:</strong> if you want a quick read-only data
        lookup, use <em>Save as scenario</em> in the Query playground. If you
        need a human-review action, hand-author a YAML in{" "}
        <code>backend/scenarios/</code> using the patterns shown in the{" "}
        <strong>Examples</strong> tab.
      </p>
    </>
  );
}

function Anatomy() {
  return (
    <>
      <h3>What every scenario answers</h3>
      <p>A scenario is the blueprint for one type of action the agent can take. It answers eight questions:</p>
      <ol>
        <li><strong>Identity</strong> — <code>id</code>, <code>title</code>, <code>domain</code>, <code>actor_id</code>, role pills</li>
        <li><strong>Intent</strong> — <code>match_keywords</code>, <code>interpreted_as</code>, <code>clarifying_question</code></li>
        <li><strong>Action</strong> — <code>action_type</code>, <code>action_payload</code></li>
        <li><strong>Mode</strong> — <code>autonomous: true|false</code></li>
        <li><strong>Knowledge per stage</strong> — <code>stages.agent_intake</code>, <code>.proposal</code>, <code>.review</code> (HITL only)</li>
        <li><strong>Reviewer surface</strong> — <code>teams_headline</code>, <code>rationale_reasons</code> (HITL only)</li>
        <li><strong>Outcomes</strong> — per-decision banner text</li>
        <li><strong>Closing message</strong> — what the agent says at the end</li>
      </ol>
      <p className="help-callout">
        Two ways to add a scenario: <strong>Save-from-playground</strong> (read-only data lookups, in-app, autonomous) or <strong>hand-authored YAML</strong> in <code>backend/scenarios/</code> (HITL or anything more structured).
      </p>
    </>
  );
}

function Shapes() {
  return (
    <>
      <h3>HITL vs autonomous — what's the difference?</h3>
      <p>
        Every scenario picks one of two flow shapes. The choice governs whether
        a human gets to inspect and approve the action before it happens.
      </p>

      <h4>HITL (Human In The Loop) — <code>autonomous: false</code></h4>
      <p>
        The agent does the reasoning and proposes an action, <strong>but stops
        before executing</strong>. The framework binds an evidence package
        (everything from the proposal stage plus a review-only stage with prior
        cases / SOPs / sanctions checks), renders it as a Teams Adaptive Card,
        and waits for a named reviewer to decide.
      </p>
      <p>The reviewer sees three buttons:</p>
      <ul>
        <li><strong>Approve</strong> → outcome banner, agent executes</li>
        <li><strong>Reject</strong> → outcome banner, action aborted, agent reports the rationale back</li>
        <li><strong>Need more info</strong> → case loops back to review with the reviewer's questions appended</li>
      </ul>
      <p>
        The case spends measurable time in <code>review_ready</code> (could be
        seconds, could be hours, depending on the reviewer). The framework's
        async transport keeps the case envelope persisted while waiting.
      </p>
      <p><strong>Required HITL-only fields:</strong></p>
      <ul>
        <li><code>stages.review</code> — the third binder stage</li>
        <li><code>reviewer_role</code>, <code>teams_headline</code>, <code>teams_channel</code></li>
        <li><code>execute_message</code> — what the approve confirmation modal says</li>
        <li><code>rationale_reasons.{`{`}reject, request_more_info{`}`}</code> — quick-pick chips on the reject/info modals</li>
        <li><code>outcomes.{`{`}approve, reject, request_more_info{`}`}</code> — banner text per branch</li>
        <li><code>closing_messages.{`{`}approve, reject, request_more_info{`}`}</code> — agent's final message; <code>{`{rationale}`}</code> is interpolated from the reviewer's reason</li>
      </ul>

      <h4>Autonomous — <code>autonomous: true</code></h4>
      <p>
        The agent reasons, the framework verifies the action against a named
        guardrail, and <strong>executes immediately without human review</strong>.
        The reviewer sees an "auto-approved by guardrail" badge in the case
        history afterward — but isn't a gate in the flow.
      </p>
      <p>
        The case never enters <code>review_ready</code>. From the operator's
        perspective the agent appears to "just do it" — the envelope still
        binds and lineage still records every step, but execution doesn't pause.
      </p>
      <p><strong>Required autonomous-only fields:</strong></p>
      <ul>
        <li><code>auto_approval_guardrail</code> — guardrail id (e.g. <code>GR-LN-AUTO-001</code>)</li>
        <li><code>auto_approval_reason</code> — plain-text justification shown on the badge</li>
        <li><code>outcomes.auto_execute</code> — banner text after execution</li>
        <li><code>closing_message</code> — single closing message (no branching)</li>
      </ul>

      <h3>How to choose</h3>

      <h4>Choose autonomous when…</h4>
      <ul>
        <li>The action is <strong>read-only</strong> (data lookups, status checks, dashboards).</li>
        <li>The action is a <strong>parameter change within a pre-approved envelope</strong> — e.g. reorder-point adjustments within ±50%, mode switches under 25% cost uplift, automatic SLA recoveries.</li>
        <li>A guardrail engine can establish safety <strong>deterministically</strong> — clear yes/no rules, not judgement calls.</li>
        <li><strong>Reversibility is high</strong>: if it's wrong, you can undo it cheaply.</li>
      </ul>

      <h4>Choose HITL when…</h4>
      <ul>
        <li>The action is <strong>irreversible or expensive to undo</strong> — sanctions overrides, vendor onboarding commitments, payments above a threshold.</li>
        <li>The action requires <strong>judgement</strong> the agent can't capture in code — interpreting a customer's claimed license, weighing a strategic supplier relationship, deciding when a precedent has stretched too far.</li>
        <li>It involves <strong>regulatory or audit obligations</strong> — sanctions screening, anti-money-laundering, export controls, fiduciary decisions.</li>
        <li>Stakes are high enough that a "two-person rule" or named-officer signoff is required by policy.</li>
      </ul>

      <p className="help-callout">
        <strong>Rule of thumb.</strong> Autonomous = "the framework knows enough to be safe alone."
        HITL = "we want a human's name on this decision in the audit log."
        When in doubt, ship HITL first; you can promote a scenario to autonomous later by adding a guardrail and flipping the flag, but you can't easily un-execute an autonomous mistake.
      </p>
    </>
  );
}

function StageKnowledge() {
  return (
    <>
      <h3>Stage knowledge: <code>facts:</code> vs <code>queries:</code></h3>
      <p>Each stage can hold either or both blocks. The combined facts populate the <code>StageContext</code>.</p>

      <h4><code>facts:</code> — inline literal facts</h4>
      <p>Static, demo-stable data. Best for policies, actor scopes, anything that doesn't change between runs.</p>
      <pre>{`stages:
  agent_intake:
    binder: PolicyAndScopeAgentBinder/1.0
    facts:
      - source: kf:graph
        ontology_type: Policy
        id: POL-TC-OVERRIDE-2026-Q2
        uri: kf.tcs/policy/POL-TC-OVERRIDE-2026-Q2
        title: TC override policy
        payload: "Critical TC overrides require named compliance officer."`}</pre>

      <h4><code>queries:</code> — live data via registered sources</h4>
      <p>Resolved at bind time against the <code>DataSourceRegistry</code>. <code>filter:</code> is interpreted by the connector kind:</p>
      <ul>
        <li><strong>CSV</strong> — column-name match</li>
        <li><strong>SQLite/Postgres</strong> — named SQL params</li>
        <li><strong>HTTP</strong> — path-template substitution</li>
        <li><strong>Vector store</strong> — query string + top_k</li>
      </ul>
      <pre>{`stages:
  proposal:
    binder: TradeOverrideProposalBinder/2.0-live
    queries:
      - data_source: products_csv
        ontology_type: Product
        filter: { product_id: P-EL-9001 }
        purpose: "Bind product master record"`}</pre>

      <p className="help-callout">
        Mix freely. Agent intake almost always has inline facts (policy, scope). Proposal/review often combine inline facts with live queries.
      </p>
    </>
  );
}

function FieldReference() {
  const rows: [string, string, string][] = [
    ["id", "yes", "Unique. Convention: SC-<DOMAIN>-<NN>"],
    ["title", "yes", "Human label shown in chat header"],
    ["domain", "yes", "Trade Compliance, Procurement, Logistics, Custom"],
    ["actor_id", "yes", "Agent identity recorded in lineage"],
    ["operator_role", "yes", "{ label, name } — status bar pill"],
    ["reviewer_role", "HITL", "{ label, name } — pill in reviewer mode"],
    ["autonomous", "yes", "true skips review; false requires it"],
    ["match_keywords", "yes", "Lowercase tokens, 3–7 specific terms"],
    ["interpreted_as", "yes", "Paraphrase the agent reads back"],
    ["clarifying_question", "yes", "HTML allowed. Confirms before binding"],
    ["action_type", "yes", "trade_override, data_lookup, etc."],
    ["action_payload", "yes", "Dict; becomes AgentAction.payload"],
    ["auto_approval_guardrail", "auto", "Guardrail id on the auto-approve badge"],
    ["auto_approval_reason", "auto", "Plain text on the badge"],
    ["teams_headline", "HITL", "Reviewer card title"],
    ["teams_channel", "HITL", "#channel-name"],
    ["execute_message", "HITL", "Approve confirmation text. HTML allowed"],
    ["rationale_reasons", "HITL", "{ reject: [...], request_more_info: [...] }"],
    ["stages", "yes", "Binder stages; see Stage knowledge"],
    ["outcomes", "yes", "Per-decision { headline, detail }"],
    ["closing_messages", "HITL", "Per-decision; {rationale} interpolated"],
    ["closing_message", "auto", "Single closing message"],
  ];
  return (
    <>
      <h3>Field reference</h3>
      <table className="help-fields">
        <thead>
          <tr><th>Field</th><th>Required?</th><th>Notes</th></tr>
        </thead>
        <tbody>
          {rows.map(([f, req, note]) => (
            <tr key={f}>
              <td><code>{f}</code></td>
              <td>{req}</td>
              <td>{note}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </>
  );
}

function Examples() {
  return (
    <>
      <h3>Full examples</h3>
      <p>
        Two complete YAMLs you can use as templates. Drop a copy into{" "}
        <code>backend/scenarios/</code>, edit the domain content, and restart
        uvicorn to pick it up.
      </p>

      <h4>HITL example — sanctions override</h4>
      <p>
        Trade-compliance scenario. The agent proposes overriding a sanctions
        block; a compliance officer reviews evidence (policy, master data,
        prior cases, SOP) and decides approve / reject / need more info.
      </p>
      <pre>{HITL_EXAMPLE}</pre>

      <h4>Autonomous example — read-only data lookup</h4>
      <p>
        Logistics scenario. The agent fetches a shipment's live status. No
        human review; auto-cleared by a read-only guardrail.
      </p>
      <pre>{AUTONOMOUS_EXAMPLE}</pre>

      <p className="help-callout">
        Both shapes share <code>id</code>, <code>title</code>, <code>domain</code>,{" "}
        <code>actor_id</code>, <code>operator_role</code>, <code>match_keywords</code>,{" "}
        <code>interpreted_as</code>, <code>clarifying_question</code>,{" "}
        <code>action_type</code>, <code>action_payload</code>, and{" "}
        <code>stages.{`{`}agent_intake, proposal{`}`}</code>. The differences
        are entirely in the review-related fields.
      </p>
    </>
  );
}

const HITL_EXAMPLE = `id: SC-TC-007
title: "Trade override — sanctioned counterparty"
domain: "Trade Compliance"
teams_channel: "#trade-compliance"
actor_id: "agent-trade-01"
operator_role: { label: "Operator", name: "trade.analyst.dlin" }
reviewer_role: { label: "Reviewer", name: "compliance.officer.kchen" }
autonomous: false

action_type: "trade_override"
action_payload:
  originating_guardrail_id: "SC-TC-001"
  product_id: "P-EL-9001"
  counterparty_name: "Sanctioned Pharma Holdings"
  destination_country: "IR"
  contract_id: "K-2026-0182"

teams_headline: "Trade override — SC-TC-001 sanctions block"
execute_message: >-
  The agent will execute the override. The order to <strong>Sanctioned Pharma
  Holdings</strong> will proceed and the SC-TC-001 block will be cleared on this case only.

match_keywords: ["override", "sanction", "ofac", "block", "eccn", "ord-44216"]
interpreted_as: "override the SC-TC-001 sanctions block on order ORD-44216"
clarifying_question: >-
  Just to confirm — override the SC-TC-001 sanctions block on counterparty
  <strong>Sanctioned Pharma Holdings</strong> for product <code>P-EL-9001</code>?
  This is a critical override that requires named compliance officer approval.

closing_messages:
  approve: >-
    <strong>Compliance officer approved.</strong> Override granted; proceeding to execute.
  reject: >-
    <strong>Compliance officer rejected the override.</strong> Reason: <em>"{rationale}"</em>
  request_more_info: >-
    <strong>Compliance officer needs more information.</strong> Specifically: <em>"{rationale}"</em>

rationale_reasons:
  reject:
    - "OFAC license could not be verified — counterparty remains on SDN list."
    - "Customer documentation insufficient to clear sanctions match."
    - "Override pattern is unusual — escalating to legal."
  request_more_info:
    - "Need a copy of the OFAC license and its expiration date."
    - "Need end-user verification and intended-use documentation."
    - "Need customer compliance attestation signed by their export officer."

stages:
  agent_intake:
    binder: "PolicyAndScopeAgentBinder/1.0"
    facts:
      - source: "kf:graph"
        ontology_type: "Policy"
        id: "POL-TC-OVERRIDE-2026-Q2"
        uri: "kf.tcs/policy/POL-TC-OVERRIDE-2026-Q2"
        title: "TC override policy"
        payload: "Critical TC overrides require named compliance officer."
      - source: "iam:scopes"
        ontology_type: "ActorScope"
        id: "agent-trade-01"
        uri: "iam.tcs/actors/agent-trade-01"
        title: "Actor scope"
        payload: "Scopes: sc.read, sc.propose, sc.execute_after_review"

  proposal:
    binder: "TradeOverrideProposalBinder/1.0"
    facts:
      - source: "erp:material_master"
        ontology_type: "Product"
        id: "P-EL-9001"
        uri: "erp.tcs/products/P-EL-9001"
        title: "Encryption module"
        payload: "ECCN 5A002 · HTS 8517.62.00 · controlled"
    queries:
      - data_source: sanctions_csv
        ontology_type: SanctionedEntity
        filter: { name: "Sanctioned Pharma Holdings" }
        purpose: "Confirm OFAC SDN match"

  review:
    binder: "TradeOverrideReviewBinder/1.0"
    queries:
      - data_source: governance_sqlite
        ontology_type: PriorOverride
        filter: { scenario_id: SC-TC-007, max_results: 3 }
        purpose: "Surface prior similar overrides"
      - data_source: policy_corpus
        ontology_type: PolicyExcerpt
        filter: { query: "OFAC override license verification", top_k: 3 }
        purpose: "Retrieve relevant SOP excerpts"

outcomes:
  approve:
    headline: "Approved with conditions"
    detail: "Override granted pending verified license."
  reject:
    headline: "Rejected — sanctions hit confirmed"
    detail: "Override denied per SOP-TC-OVERRIDE-001. The OFAC SDN match cannot be cleared without an OFAC license."
  request_more_info:
    headline: "More information requested"
    detail: "Reviewer requested OFAC license documentation before deciding."
`;

const AUTONOMOUS_EXAMPLE = `id: SC-LN-STATUS-009
title: "Shipment status lookup"
domain: "Logistics & Network"
autonomous: true
actor_id: "agent-logistics-31"
operator_role: { label: "Operator", name: "planner.lvenkat" }

action_type: "shipment_status_lookup"
action_payload:
  shipment_id: "S-700499"
  query_type: "live_status"
  scope: "logistics.read"

match_keywords: ["eta", "status", "where is", "track", "shipment status", "s-700499"]
interpreted_as: "look up the current status and ETA on shipment S-700499"
clarifying_question: >-
  Just to confirm — pull the current status and ETA on shipment <code>S-700499</code>.
  Read-only query within my <code>logistics.read</code> scope; per policy
  <code>GR-LN-AUTO-001</code>, no human review is required. Proceed?

auto_approval_guardrail: "GR-LN-AUTO-001"
auto_approval_reason: "Read-only logistics query within agent scope. Policy GR-LN-AUTO-001 permits autonomous status checks."

closing_message: >-
  Done — the status query was auto-approved by <code>GR-LN-AUTO-001</code>.
  <strong>Shipment S-700499</strong>: ETA now <strong>Apr 30</strong>. No action required.

stages:
  agent_intake:
    binder: "PolicyAndScopeAgentBinder/1.0"
    facts:
      - source: "kf:graph"
        ontology_type: "Policy"
        id: "POL-LN-READONLY-2026"
        uri: "kf.tcs/policy/POL-LN-READONLY-2026"
        title: "Read-only logistics policy"
        payload: "Read-only queries are autonomous within logistics.read scope."
      - source: "iam:scopes"
        ontology_type: "ActorScope"
        id: "agent-logistics-31"
        uri: "iam.tcs/actors/agent-logistics-31"
        title: "Actor scope"
        payload: "Scopes: logistics.read · this query: logistics.read only"

  proposal:
    binder: "ShipmentLookupProposalBinder/1.0"
    facts:
      - source: "tms:shipments"
        ontology_type: "Shipment"
        id: "S-700499"
        uri: "tms.tcs/shipments/S-700499"
        title: "Shipment record"
        payload: "Origin Singapore · Dest Rotterdam · 8 pallets · ocean booking"
      - source: "tms:tracking"
        ontology_type: "LiveTrack"
        id: "TRK-S-700499"
        uri: "tms.tcs/tracking/TRK-S-700499"
        title: "Live tracking"
        payload: "Vessel MV NORDIC CRYSTAL · 12 nm off Rotterdam · ETA Apr 30 04:00 UTC"

outcomes:
  auto_execute:
    headline: "Auto-executed — status retrieved"
    detail: "ETA confirmed as Apr 30. Vessel 12 nm off Rotterdam · port congestion LOW. No action required."
`;

function QualityTips() {
  return (
    <>
      <h3>Quality guidelines</h3>
      <h4>Match keywords</h4>
      <ul>
        <li><strong>3–7 specific terms.</strong> More = more false matches.</li>
        <li>Avoid generic words: <code>data</code>, <code>lookup</code>, <code>query</code>, <code>report</code>.</li>
        <li>Include canonical entity ids (<code>S-700412</code>, <code>SC-TC-001</code>).</li>
        <li>Lowercase everything; the classifier lowercases the prompt first.</li>
      </ul>
      <h4>One scenario per discrete intent</h4>
      <p>Don't bundle "lookup X and onboard X" into one. Two scenarios that chain via the agent runtime is cleaner than a super-scenario with branching logic.</p>

      <h4>Anti-patterns</h4>
      <table className="help-fields">
        <thead><tr><th>Anti-pattern</th><th>The issue</th></tr></thead>
        <tbody>
          <tr><td>Vague keywords</td><td>Classifier hijacks every prompt</td></tr>
          <tr><td>Empty <code>facts:</code> AND <code>queries:</code> on a stage</td><td>Stage binds nothing, envelope is empty</td></tr>
          <tr><td>Clarifying question that repeats the prompt</td><td>Operator can't tell if the agent understood</td></tr>
          <tr><td>HITL scenario with <code>closing_messages</code> only for approve</td><td>Reject + more-info paths render blank</td></tr>
          <tr><td>Keyword overlap with another scenario</td><td>Top-K shows both — confusing for the operator</td></tr>
          <tr><td>Inline facts that should be live</td><td>Stale data goes through review</td></tr>
        </tbody>
      </table>
    </>
  );
}

function Lifecycle() {
  return (
    <>
      <h3>Three kinds of scenario</h3>
      <p>
        Three sources of scenarios coexist in the chip list. They differ in
        how they get there, who can edit them, and how they're removed.
      </p>

      <h4>Built-in — <code>SC-TC-*</code>, <code>SC-PP-*</code>, <code>SC-LN-*</code></h4>
      <p>
        Hand-authored YAMLs committed to the repo at{" "}
        <code>backend/scenarios/</code>. Loaded once at uvicorn startup.
      </p>
      <ul>
        <li><strong>Editable in the UI</strong> for title / keywords / clarifier (changes persist to YAML).</li>
        <li><strong>Cannot be removed via the UI</strong> — the Remove button is disabled. To delete one, remove its YAML file and restart uvicorn.</li>
        <li>Represents the canonical, version-controlled scenario catalogue.</li>
      </ul>

      <h4>Auto — <code>SC-AUTO-&lt;source_id&gt;</code></h4>
      <p>
        Created automatically when an operator-registered data source is added
        (CSV upload, Add SQLite/Postgres/HTTP/vector). Autonomous, bound to the
        source's <code>queries:</code> block, with derived match_keywords.
      </p>
      <p>Two ways to remove:</p>
      <ol>
        <li><strong>Delete the source.</strong> The chip is removed at the same time. Usual path.</li>
        <li><strong>Delete the chip only.</strong> Click the pencil on the chip → <strong>Remove this scenario</strong>. The source stays registered (still queryable in the playground), but the chip disappears.</li>
      </ol>

      <h4>Custom — <code>SC-CUSTOM-&lt;slug&gt;</code></h4>
      <p>
        Created via the <strong>Save as scenario</strong> form in the Query
        playground. Autonomous, runs your saved SQL against the source, persists
        in <code>backend/scenarios/</code> as YAML.
      </p>
      <ul>
        <li><strong>Removed via the edit modal:</strong> pencil → <strong>Remove this scenario</strong>.</li>
        <li><strong>Or via the API:</strong> <code>DELETE /api/scenarios/SC-CUSTOM-&lt;slug&gt;</code>.</li>
      </ul>

      <h3>Quick reference</h3>
      <table className="help-fields">
        <thead>
          <tr><th>Action</th><th>Built-in</th><th>Auto</th><th>Custom</th></tr>
        </thead>
        <tbody>
          <tr><td>Edit title / keywords / clarifier in UI</td><td>✅</td><td>✅</td><td>✅</td></tr>
          <tr><td>Edit structural fields in UI</td><td>❌ (edit YAML)</td><td>❌</td><td>❌</td></tr>
          <tr><td>Remove via Edit modal</td><td>❌</td><td>✅</td><td>✅</td></tr>
          <tr><td>Remove via API <code>DELETE</code></td><td>❌ (400)</td><td>✅</td><td>✅</td></tr>
          <tr><td>Removed automatically with its source</td><td>n/a</td><td>✅</td><td>❌</td></tr>
        </tbody>
      </table>

      <h3>Adding a custom YAML by hand</h3>
      <ol>
        <li>Drop a new <code>SC-XX-NNN.yaml</code> into <code>backend/scenarios/</code>.</li>
        <li>Restart uvicorn (the directory is loaded once at startup).</li>
        <li>Refresh the UI → new chip appears.</li>
      </ol>
    </>
  );
}

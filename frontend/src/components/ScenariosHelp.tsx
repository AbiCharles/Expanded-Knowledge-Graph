/**
 * Scenarios Authoring help modal.
 *
 * Mirrors the content of `docs/scenarios.md`. Two sources of truth is fine for
 * the size of this content; the markdown file is canonical (and what you'd
 * link to from a README), this is the in-app reference contextual to the UI.
 */
import { useState } from "react";

type Section = "overview" | "anatomy" | "shapes" | "stages" | "ontologies" | "fields" | "examples" | "tips" | "lifecycle";

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
            <button className={section === "ontologies" ? "active" : ""} onClick={() => setSection("ontologies")}>
              Ontologies
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
            {section === "ontologies" && <Ontologies />}
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
        <strong>Example.</strong> An operator types "Override the{" "}
        <code>SC-TC-001</code> block on order ORD-44216." The framework
        matches that to the <code>SC-TC-007</code> scenario (sanctions
        override). It binds the active trade-compliance policy, the agent's{" "}
        <abbr title="Identity and Access Management">IAM</abbr> scope, the
        product master record, the contract, prior similar overrides, and an
        applicable <abbr title="Standard Operating Procedure">SOP</abbr> —
        then renders all of that as evidence for a compliance officer to review.
      </p>

      <h3>What scenarios do</h3>
      <ol>
        <li>
          <strong>Route prompts.</strong> When the operator types something,
          the classifier (an <abbr title="Large Language Model">LLM</abbr>)
          scans every scenario's <code>match_keywords</code> and{" "}
          <code>interpreted_as</code> phrasing and picks the best match.
        </li>
        <li>
          <strong>Tell the agent what to read.</strong> Each scenario specifies
          which knowledge gets bound at each stage (intake, proposal, review).
          That knowledge becomes the envelope the reviewer eventually sees.
        </li>
        <li>
          <strong>Decide whether a human needs to look.</strong> Autonomous
          scenarios skip review and execute directly.{" "}
          <strong>HITL (human-in-the-loop)</strong> scenarios stop at the
          review stage and wait for a decision.
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
      <p>
        Scenario ids follow the convention{" "}
        <code>SC-&lt;domain-prefix&gt;-&lt;number&gt;</code>. The current
        prefixes are:
      </p>
      <ul>
        <li><code>SC-TC-*</code> — <strong>Trade Compliance</strong></li>
        <li><code>SC-PP-*</code> — <strong>Planning &amp; Procurement</strong></li>
        <li><code>SC-LN-*</code> — <strong>Logistics &amp; Network</strong></li>
        <li><code>SC-ONTO-*</code> — <strong>Ontology lookup</strong> (autonomous, generated from Mappings)</li>
      </ul>
      <p>They split into two lifecycle types:</p>
      <ul>
        <li>
          <strong>Built-in</strong> (<code>SC-TC-*</code>, <code>SC-PP-*</code>,{" "}
          <code>SC-LN-*</code>) — committed to the repo, hand-authored, can't
          be deleted via the API.
        </li>
        <li>
          <strong>Generated lookup chip</strong>{" "}
          (<code>SC-ONTO-&lt;ontology&gt;-&lt;Class&gt;</code>) — created from
          the <em>Knowledge → Ontologies → Mappings</em> tab by clicking
          "Generate lookup chip" next to a class. Autonomous, runs an
          ontology query, persists as YAML in <code>backend/scenarios/</code>.
        </li>
      </ul>
      <p>
        If the classifier can't match a prompt to one of these, the case is
        refused (no scenario is invented at request time) — operators see
        the chip catalogue and pick one explicitly.
      </p>

      <p className="help-callout">
        <strong>Where to start:</strong> for a quick read-only lookup against a
        connected source, register the source under <em>Knowledge → Data
        sources</em>, then go to <em>Ontologies → Mappings</em>, suggest
        mappings, and click <strong>Generate lookup chip</strong>. For a
        human-review action, hand-author a YAML in{" "}
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
        Two ways to add a scenario: <strong>"Generate lookup chip"</strong> from
        the Ontologies → Mappings tab (autonomous, ontology-driven, in-app), or{" "}
        <strong>hand-authored YAML</strong> in <code>backend/scenarios/</code>{" "}
        (HITL or anything more structured).
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

      <p className="help-callout">
        The classifier only ever picks from the closed set of authored
        scenarios (built-in + persisted <code>SC-ONTO-*</code>). There is no
        runtime "guess" path — if no scenario matches and the classifier
        can't suggest one, the case is refused.
      </p>
    </>
  );
}

function StageKnowledge() {
  return (
    <>
      <h3>Stage knowledge: <code>facts:</code> vs <code>ontology_queries:</code></h3>
      <p>
        Each stage can hold either or both blocks. The combined facts populate
        the <code>StageContext</code>. The legacy{" "}
        <code>queries:</code> block was removed in Phase 3 — scenarios that
        still use it fail at load with a migration pointer.
      </p>

      <h4><code>facts:</code> — inline literal facts</h4>
      <p>
        Static, demo-stable data. Best for policies, actor scopes, anything
        that doesn't change between runs.
      </p>
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

      <h4><code>ontology_queries:</code> — live data via the ontology</h4>
      <p>
        Scenarios name an <em>ontology class</em>, not a raw data source. At
        bind time the <code>OntologyResolver</code> looks up the class's
        mapping, dispatches the query to whichever connector(s) back it, and
        returns rows tagged with provenance (which class asked · which source
        answered).
      </p>
      <ul>
        <li><code>ontology</code> — ontology id (e.g. <code>tcs_core</code>, <code>supply_chain</code>)</li>
        <li><code>class</code> — class name within that ontology (e.g. <code>Product</code>, <code>SanctionedEntity</code>)</li>
        <li><code>where</code> — optional dict of filter keys. Keys are translated to source columns via the mapping's <code>attribute_map</code>. Supports <code>:param</code> substitution from <code>action_payload</code>.</li>
        <li><code>max_results</code> — optional integer cap (default 50)</li>
        <li><code>purpose</code> — short human label, shown in lineage</li>
      </ul>
      <pre>{`stages:
  proposal:
    binder: TradeOverrideProposalBinder/2.0
    ontology_queries:
      - ontology: tcs_core
        class: Product
        where: { product_id: :product_id }   # filled from action_payload
        purpose: "Bind product master record"
      - ontology: tcs_core
        class: SanctionedEntity
        where: { entity_name: :counterparty_name }
        purpose: "Confirm OFAC SDN match"`}</pre>

      <h4>Filter-aware chips: <code>_filter_from_prompt: true</code></h4>
      <p>
        Generated lookup chips (<code>SC-ONTO-…</code>) ship with an empty{" "}
        <code>where: {`{}`}</code>. Add <code>_filter_from_prompt: true</code>{" "}
        at the top level and the orchestrator pre-parses the operator's prompt
        into a partial <code>where</code> before the binder runs — so "show me
        Dutch suppliers" becomes <code>country: NL</code> automatically. An
        explicit <code>where</code> in the YAML always wins over an extracted
        one.
      </p>

      <p className="help-callout">
        Mix freely. Agent intake almost always has inline <code>facts:</code>{" "}
        for policy + actor scope. Proposal/review usually combine inline facts
        (reference data) with <code>ontology_queries</code> (live data).
      </p>
    </>
  );
}

function Ontologies() {
  return (
    <>
      <h3>What an ontology is</h3>
      <p>
        An <strong>ontology</strong> defines abstract domain classes —{" "}
        <code>Product</code>, <code>SanctionedEntity</code>, <code>PolicyExcerpt</code> —
        each with named, typed attributes. It knows nothing about CSV files, Postgres
        tables, or HTTP APIs. A separate <strong>mapping document</strong> bridges each
        class to the registered data sources that can answer it. Both live under{" "}
        <code>backend/ontologies/</code>.
      </p>

      <h3>How a scenario plugs into an ontology</h3>
      <p>
        A scenario only mentions an ontology in two places: the <code>ontology</code>{" "}
        and <code>class</code> fields inside an <code>ontology_queries:</code> block.
        Those two strings are the glue — they have to match real names in three other
        files, and the names line up like this:
      </p>

      <pre>{`scenario YAML          ontology YAML         mappings YAML         source registry
────────────────       ────────────────      ─────────────────     ────────────────
ontology: tcs_core ──▶ id: tcs_core
class: Product   ────▶ classes:
                         Product:    ──────▶ mappings:
                           attributes:         Product:
                             product_id          sources:
                             name                  - data_source: ──▶ id: products_csv
                             eccn                    products_csv
                                                  attribute_map:
                                                    product_id: product_id
                                                    name: name
                                                    eccn: eccn`}</pre>

      <p>Walked through file by file:</p>

      <ol>
        <li>
          <strong>Scenario</strong> — <code>backend/scenarios/SC-…-….yaml</code> —
          declares the query. The two strings have to resolve:
          <pre>{`stages:
  proposal:
    binder: OntologyProposalBinder/1.0
    ontology_queries:
      - ontology: tcs_core      # ← must match the ontology's "id" field
        class: Product          # ← must match a class key in that ontology
        where: { product_id: :product_id }
        purpose: "Bind product through ontology"`}</pre>
        </li>
        <li>
          <strong>Ontology</strong> —{" "}
          <code>backend/ontologies/tcs_core.yaml</code> — defines the class shape and
          its attributes. This is the schema the scenario's <code>class:</code> field
          points at:
          <pre>{`id: tcs_core                 # ← matches "ontology" in the scenario
classes:
  Product:                    # ← matches "class" in the scenario
    attributes:
      - {name: product_id, type: string, identifier: true}
      - {name: name, type: string}
      - {name: eccn, type: string}
      - ...`}</pre>
        </li>
        <li>
          <strong>Mapping</strong> —{" "}
          <code>backend/ontologies/tcs_core.mappings.yaml</code> — binds the class to
          one or more <em>registered data sources</em>. The <code>attribute_map</code>{" "}
          translates ontology attribute names to source-specific column / field names:
          <pre>{`ontology_id: tcs_core            # ← matches the ontology's "id"
mappings:
  Product:                       # ← matches the class key
    sources:
      - data_source: products_csv      # ← must match a registered source id
        identifier_column: product_id
        attribute_map:
          product_id: product_id       # left = ontology attribute, right = source column
          name: name
          eccn: eccn`}</pre>
        </li>
        <li>
          <strong>Source</strong> — the <code>products_csv</code> entry registered via
          the Knowledge tile (or seeded from <code>backend/data/sources.yaml</code>)
          points at the actual CSV / table / endpoint. The resolver runs the query,
          applies the <code>attribute_map</code> in reverse to rename source columns
          back to ontology attributes, and returns the rows as typed facts in the
          case envelope.
        </li>
      </ol>

      <p className="help-callout">
        Break any link in the chain (typo in <code>class</code>, missing mapping
        entry, deleted data source) and the scenario fails to bind at runtime — the
        case lands in the error stage with a "no mapping for{" "}
        <code>&lt;ontology&gt;.&lt;class&gt;</code>" or "unknown data source{" "}
        <code>&lt;id&gt;</code>" message. There is no silent fallback.
      </p>

      <h3>The two hook points inside a scenario</h3>

      <h4>1. <code>facts[].ontology_type</code> — passive type label</h4>
      <p>
        Every inline fact in a stage's <code>facts:</code> list carries an{" "}
        <code>ontology_type</code> tag so the envelope stays typed for the UI and
        audit log. It does <em>not</em> trigger a query — it's metadata on a
        pre-resolved fact (e.g. the policy text you embed inline in{" "}
        <code>agent_intake</code>).
      </p>

      <h4>2. <code>ontology_queries:</code> — active binding via the resolver</h4>
      <p>
        The block walked through above. Each entry produces a typed batch of facts at
        bind time, fanning out across every source the mapping covers. See{" "}
        <strong>Stage knowledge</strong> for the YAML reference (<code>where</code>,{" "}
        <code>max_results</code>, <code>purpose</code>, <code>:param</code>{" "}
        substitution from <code>action_payload</code>).
      </p>

      <h3>Why this layer exists</h3>
      <ul>
        <li>
          <strong>One scenario, many sources.</strong> Register a new connector, add a
          mapping entry for an existing class — every scenario that queries that
          class picks it up. No scenario rewrites.
        </li>
        <li>
          <strong>Auto-scaffolded lookup chips.</strong> The "Generate lookup chip"
          button in the Knowledge tile produces an{" "}
          <code>SC-ONTO-&lt;ontology&gt;-&lt;class&gt;.yaml</code> scenario per class —
          instant operator UI for any class without writing YAML.
        </li>
        <li>
          <strong>Cross-source provenance.</strong> The mapping doc declares
          identifier columns and per-source confidence, so the system knows what's
          bindable versus what needs human resolution. Each returned fact carries
          which class asked · which source answered.
        </li>
      </ul>
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
    ontology_queries:
      - ontology: tcs_core
        class: SanctionedEntity
        where: { entity_name: :counterparty_name }
        purpose: "Confirm OFAC SDN match"

  review:
    binder: "TradeOverrideReviewBinder/1.0"
    ontology_queries:
      - ontology: tcs_core
        class: PriorOverride
        where: { scenario_id: SC-TC-007 }
        max_results: 3
        purpose: "Surface prior similar overrides"
      - ontology: tcs_core
        class: PolicyExcerpt
        where: { query: "OFAC override license verification" }
        max_results: 3
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
          <tr><td>Empty <code>facts:</code> AND <code>ontology_queries:</code> on a stage</td><td>Stage binds nothing, envelope is empty</td></tr>
          <tr><td>Legacy <code>queries:</code> block</td><td>Loader rejects the YAML — migrate to <code>ontology_queries:</code></td></tr>
          <tr><td><code>ontology_queries</code> referencing a class with no mapping</td><td>Resolver returns zero facts; check Knowledge → Ontologies → Mappings</td></tr>
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
      <h3>Kinds of scenario in the chip list</h3>
      <p>
        Three durable sources of scenarios coexist on the operator console,
        plus two ephemeral kinds that are materialised at request time. They
        differ in how they get there, who can edit them, and how they're removed.
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

      <h4>Generated lookup chip — <code>SC-ONTO-&lt;ontology&gt;-&lt;Class&gt;</code></h4>
      <p>
        Created by clicking <strong>Generate lookup chip</strong> next to a
        class in <em>Knowledge → Ontologies → Mappings</em>. Autonomous,
        read-only; the proposal stage runs a single{" "}
        <code>ontology_queries</code> entry against the class. The id is
        stable, so regenerating overwrites rather than duplicating.
      </p>
      <ul>
        <li><strong>Filter-aware by default</strong> — ships with{" "}
          <code>_filter_from_prompt: true</code>, so the operator can type
          natural filters like "Dutch suppliers" and the orchestrator
          extracts <code>country: NL</code> before bind.
        </li>
        <li><strong>Removable</strong> via the edit modal's Remove button or{" "}
          <code>DELETE /api/scenarios/SC-ONTO-…</code>. Re-clicking{" "}
          "Generate lookup chip" recreates it.
        </li>
      </ul>

      <h3>Quick reference</h3>
      <table className="help-fields">
        <thead>
          <tr>
            <th>Action</th>
            <th>Built-in</th>
            <th>SC-ONTO</th>
          </tr>
        </thead>
        <tbody>
          <tr><td>Persisted as YAML on disk</td><td>✅</td><td>✅</td></tr>
          <tr><td>Edit title / keywords / clarifier in UI</td><td>✅</td><td>✅</td></tr>
          <tr><td>Edit structural fields in UI</td><td>❌ (edit YAML)</td><td>❌</td></tr>
          <tr><td>Remove via Edit modal</td><td>❌</td><td>✅</td></tr>
          <tr><td>Remove via API <code>DELETE</code></td><td>❌ (400)</td><td>✅</td></tr>
        </tbody>
      </table>

      <h3>Adding a hand-authored YAML</h3>
      <ol>
        <li>Drop a new <code>SC-XX-NNN.yaml</code> into <code>backend/scenarios/</code>.</li>
        <li>Restart uvicorn (the directory is loaded once at startup).</li>
        <li>Refresh the UI → new chip appears at the top of the list (chips are sorted newest-first by file mtime).</li>
      </ol>

      <h3>Glossary</h3>
      <h4>Scenario / framework terms</h4>
      <table className="help-fields">
        <thead><tr><th>Acronym</th><th>Meaning</th></tr></thead>
        <tbody>
          <tr><td><strong>HITL</strong></td><td>Human In The Loop — a scenario that pauses for a named reviewer before executing.</td></tr>
          <tr><td><strong>LLM</strong></td><td>Large Language Model — used here only for classification and argument extraction, never for the action itself.</td></tr>
          <tr><td><strong>NL</strong></td><td>Natural Language — operator's plain-English input.</td></tr>
          <tr><td><strong>SC-TC</strong></td><td>Scenario, Trade Compliance domain.</td></tr>
          <tr><td><strong>SC-PP</strong></td><td>Scenario, Planning &amp; Procurement domain.</td></tr>
          <tr><td><strong>SC-LN</strong></td><td>Scenario, Logistics &amp; Network domain.</td></tr>
          <tr><td><strong>SC-ONTO</strong></td><td>Scenario generated from an Ontology class (autonomous lookup).</td></tr>
        </tbody>
      </table>

      <h4>Acronyms in the example YAMLs</h4>
      <p>
        The bundled examples reference real industry terms so the demo
        feels concrete. They aren't part of the framework — your own
        scenarios will use whatever vocabulary your domain uses.
      </p>
      <table className="help-fields">
        <thead><tr><th>Acronym</th><th>Meaning</th></tr></thead>
        <tbody>
          <tr><td><strong>OFAC</strong></td><td>U.S. Office of Foreign Assets Control — administers sanctions programmes.</td></tr>
          <tr><td><strong>SDN</strong></td><td>Specially Designated Nationals — OFAC's sanctions list.</td></tr>
          <tr><td><strong>ECCN</strong></td><td>Export Control Classification Number — U.S. dual-use export classification.</td></tr>
          <tr><td><strong>HTS</strong></td><td>Harmonized Tariff Schedule — international trade classification.</td></tr>
          <tr><td><strong>SOP</strong></td><td>Standard Operating Procedure.</td></tr>
          <tr><td><strong>IAM</strong></td><td>Identity and Access Management — who the agent is allowed to act as.</td></tr>
          <tr><td><strong>ETA</strong></td><td>Estimated Time of Arrival.</td></tr>
          <tr><td><strong>SLA</strong></td><td>Service Level Agreement.</td></tr>
          <tr><td><strong>ERP</strong></td><td>Enterprise Resource Planning system (e.g. SAP) — source of material/contract master data.</td></tr>
          <tr><td><strong>TMS</strong></td><td>Transportation Management System — source of shipment/tracking data.</td></tr>
          <tr><td><strong>KF</strong></td><td>Knowledge Fabric / Framework — the policy + ontology graph the agent reads from.</td></tr>
        </tbody>
      </table>
    </>
  );
}

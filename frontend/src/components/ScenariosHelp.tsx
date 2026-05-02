/**
 * Scenarios Authoring help modal.
 *
 * Mirrors the content of `docs/scenarios.md`. Two sources of truth is fine for
 * the size of this content; the markdown file is canonical (and what you'd
 * link to from a README), this is the in-app reference contextual to the UI.
 */
import { useState } from "react";

type Section = "anatomy" | "shapes" | "stages" | "fields" | "tips" | "lifecycle";

export function ScenariosHelp({ onClose }: { onClose: () => void }) {
  const [section, setSection] = useState<Section>("anatomy");

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
            {section === "anatomy" && <Anatomy />}
            {section === "shapes" && <Shapes />}
            {section === "stages" && <StageKnowledge />}
            {section === "fields" && <FieldReference />}
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
      <h3>Two flow shapes</h3>

      <h4>HITL — <code>autonomous: false</code></h4>
      <p>Three binder stages (intake, proposal, review). The case enters <code>review_ready</code>, a Teams card is rendered, the reviewer decides.</p>
      <p><strong>Required HITL-only fields:</strong></p>
      <ul>
        <li><code>reviewer_role</code>, <code>teams_headline</code>, <code>teams_channel</code>, <code>execute_message</code></li>
        <li><code>stages.review</code></li>
        <li><code>rationale_reasons.{`{`}reject, request_more_info{`}`}</code> — the quick-pick chips</li>
        <li><code>outcomes.{`{`}approve, reject, request_more_info{`}`}</code></li>
        <li><code>closing_messages.{`{`}approve, reject, request_more_info{`}`}</code> with <code>{`{rationale}`}</code> interpolation</li>
      </ul>

      <h4>Autonomous — <code>autonomous: true</code></h4>
      <p>Two binder stages. Framework auto-approves and executes.</p>
      <p><strong>Required autonomous-only fields:</strong></p>
      <ul>
        <li><code>auto_approval_guardrail</code>, <code>auto_approval_reason</code></li>
        <li><code>outcomes.auto_execute</code></li>
        <li><code>closing_message</code> (single, no decision branching)</li>
      </ul>

      <p className="help-callout">
        <strong>When to choose autonomous:</strong> read-only lookups, parameter changes within a pre-approved envelope, anything where the guardrail engine can establish safety deterministically.<br />
        <strong>When to choose HITL:</strong> irreversible commitments, policy overrides, anything where judgement matters more than process.
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
        <thead><tr><th>Anti-pattern</th><th>Why it bites</th></tr></thead>
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
      <table className="help-fields">
        <thead><tr><th>Type</th><th>id pattern</th><th>Lifecycle</th></tr></thead>
        <tbody>
          <tr>
            <td><strong>Built-in</strong></td>
            <td><code>SC-TC-*</code>, <code>SC-PP-*</code>, <code>SC-LN-*</code></td>
            <td>Committed to the repo. Cannot be deleted via the API.</td>
          </tr>
          <tr>
            <td><strong>Auto</strong></td>
            <td><code>SC-AUTO-&lt;source_id&gt;</code></td>
            <td>Created automatically when an operator-registered source is added. Removed when the source is removed.</td>
          </tr>
          <tr>
            <td><strong>Custom</strong></td>
            <td><code>SC-CUSTOM-&lt;slug&gt;</code></td>
            <td>Created via "Save as scenario" in the Query playground. Persist in <code>backend/scenarios/</code> until deleted.</td>
          </tr>
        </tbody>
      </table>
      <p>All three appear in the operator console's chip list and can be invoked the same way.</p>

      <h3>Adding a custom YAML by hand</h3>
      <ol>
        <li>Drop a new <code>SC-XX-NNN.yaml</code> into <code>backend/scenarios/</code>.</li>
        <li>Restart uvicorn (the directory is loaded once at startup).</li>
        <li>Refresh the UI → new chip appears.</li>
      </ol>
    </>
  );
}

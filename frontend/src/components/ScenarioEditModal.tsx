/**
 * Edit-scenario modal. Loads current values, lets the operator change the
 * editable fields (title, prompt, keywords, clarifier), saves via PATCH.
 *
 * Built-in scenarios CAN be edited (the structural bits like stages and
 * action_type are intentionally left out of the form since changing them
 * mid-flight risks breaking running cases). Edits persist to disk.
 */
import { useEffect, useState } from "react";
import * as api from "../api";

interface ScenarioDetail {
  id: string;
  title: string;
  domain: string;
  autonomous: boolean;
  match_keywords: string[];
  interpreted_as: string;
  clarifying_question: string;
  suggested_prompt: string;
  description?: string;
  action_type: string;
  is_builtin: boolean;
}

export function ScenarioEditModal({
  scenarioId,
  onClose,
  onSaved,
}: {
  scenarioId: string;
  onClose: () => void;
  onSaved: () => void;
}) {
  const [detail, setDetail] = useState<ScenarioDetail | null>(null);
  const [title, setTitle] = useState("");
  const [keywords, setKeywords] = useState("");
  const [clarifier, setClarifier] = useState("");
  const [interpreted, setInterpreted] = useState("");
  const [prompt, setPrompt] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    api.getScenario(scenarioId)
      .then((d: ScenarioDetail) => {
        setDetail(d);
        setTitle(d.title || "");
        setKeywords((d.match_keywords || []).join(", "));
        setClarifier(d.clarifying_question || "");
        setInterpreted(d.interpreted_as || "");
        setPrompt(d.suggested_prompt || "");
      })
      .catch((e) => setError((e as Error).message));
  }, [scenarioId]);

  const save = async () => {
    setBusy(true);
    setError(null);
    try {
      await api.editScenario(scenarioId, {
        title: title.trim(),
        match_keywords: keywords.split(",").map((k) => k.trim()).filter(Boolean),
        clarifying_question: clarifier,
        interpreted_as: interpreted,
        suggested_prompt: prompt.trim(),
      });
      onSaved();
      onClose();
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  };

  return (
    <div
      className="modal-backdrop"
      onClick={(e) => e.target === e.currentTarget && onClose()}
    >
      <div className="scenario-edit-card">
        <div className="ds-header">
          <div>
            <div className="ds-eyebrow">Edit scenario</div>
            <div className="ds-title">{detail?.title || scenarioId}</div>
          </div>
          <button className="teams-close" onClick={onClose}>×</button>
        </div>

        {!detail && !error && <div className="scenario-edit-loading">Loading…</div>}
        {error && <div className="ds-error">{error}</div>}

        {detail && (
          <div className="scenario-edit-body">
            <div className="scenario-edit-meta">
              <span><strong>{detail.id}</strong></span>
              <span>· {detail.domain}</span>
              <span>· {detail.autonomous ? "autonomous" : "HITL"}</span>
              <span>· action_type: <code>{detail.action_type}</code></span>
              {detail.is_builtin && (
                <span className="scenario-edit-builtin-flag" title="Built-in scenarios can be edited but YAML changes will persist on disk.">
                  built-in
                </span>
              )}
            </div>

            <label>Title
              <input value={title} onChange={(e) => setTitle(e.target.value)} />
            </label>
            <label>Suggested prompt (chip text)
              <input value={prompt} onChange={(e) => setPrompt(e.target.value)} />
            </label>
            <label>Match keywords (comma-separated)
              <input value={keywords} onChange={(e) => setKeywords(e.target.value)} />
            </label>
            <label>Interpreted-as (paraphrase the agent reads back)
              <input value={interpreted} onChange={(e) => setInterpreted(e.target.value)} />
            </label>
            <label>Clarifying question (HTML allowed)
              <textarea value={clarifier} onChange={(e) => setClarifier(e.target.value)} rows={3} />
            </label>

            <div className="scenario-edit-help">
              Structural fields (stages, action_type, autonomous) aren't editable here —
              changing them mid-flight risks breaking running cases. Hand-edit the YAML
              and restart uvicorn for those.
            </div>

            <div className="scenario-edit-actions">
              <button onClick={onClose}>Cancel</button>
              <button className="primary" onClick={save} disabled={busy || !title.trim()}>
                {busy ? "Saving…" : "Save changes"}
              </button>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}

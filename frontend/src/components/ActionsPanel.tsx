import { useEffect, useState } from "react";
import * as api from "../api";
import { ActionSummary, NLActionPreview } from "../api";

// Inline panel mounted inside the Knowledge modal's Actions tab.
// Lists registered write actions, lets the operator upload a new one
// (raw JSON document for now — YAML editor is a follow-up), preview a
// natural-language pick, and delete non-default actions.

export function ActionsPanel() {
  const [actions, setActions] = useState<ActionSummary[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [preview, setPreview] = useState<NLActionPreview | null>(null);
  const [previewPrompt, setPreviewPrompt] = useState("");

  const refresh = async () => {
    try {
      setActions(await api.listActions());
    } catch (e) {
      setError((e as Error).message);
    }
  };
  useEffect(() => {
    refresh();
  }, []);

  const onPreview = async () => {
    setError(null);
    setBusy(true);
    setPreview(null);
    try {
      const p = await api.previewNLAction(previewPrompt);
      setPreview(p);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  };

  const onDelete = async (id: string) => {
    if (!confirm(`Remove action "${id}"?`)) return;
    try {
      await api.deleteAction(id);
      await refresh();
    } catch (e) {
      setError((e as Error).message);
    }
  };

  return (
    <div style={{ padding: 16, overflowY: "auto" }}>
      <div style={{ fontSize: 12, color: "var(--ink-soft)", marginBottom: 12, lineHeight: 1.5 }}>
        Write actions are structured operations the agent can take when an
        operator's prompt doesn't match a scenario. They're picked from
        natural language by the LLM, sent for human review by default,
        and only executed once the reviewer approves. Toggle{" "}
        <strong>Try write action…</strong> on the operator console
        composer to enable the fallback.
      </div>

      {error && <div className="ds-error">{error}</div>}

      <div style={{ fontSize: 12, fontWeight: 600, marginBottom: 6 }}>
        Registered actions ({actions.length})
      </div>
      {actions.length === 0 && (
        <div style={{ fontSize: 12, color: "var(--ink-soft)", padding: 12, border: "1px dashed var(--border)", borderRadius: 4 }}>
          No actions registered yet. Drop YAML files into{" "}
          <code>backend/data/actions/</code> on disk, or POST one via
          <code> /api/actions/raw</code>.
        </div>
      )}
      <div style={{ display: "flex", flexDirection: "column", gap: 6, marginBottom: 16 }}>
        {actions.map((a) => (
          <div key={a.id} className="ds-row" style={{ padding: 10 }}>
            <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
              <div>
                <div style={{ fontWeight: 600, fontSize: 13 }}>
                  {a.title}{" "}
                  <span
                    style={{
                      fontSize: 10,
                      padding: "1px 5px",
                      borderRadius: 3,
                      background: a.hitl ? "rgba(214,158,46,0.15)" : "rgba(47,125,95,0.15)",
                      color: a.hitl ? "var(--amber)" : "var(--emerald)",
                      marginLeft: 6,
                    }}
                  >
                    {a.hitl ? "HITL" : "auto"}
                  </span>
                  {a.default && (
                    <span style={{ fontSize: 10, color: "var(--ink-soft)", marginLeft: 6 }}>
                      default
                    </span>
                  )}
                </div>
                <div style={{ fontSize: 11, color: "var(--ink-soft)", marginTop: 2 }}>
                  <code>{a.id}</code> · executor=<code>{a.executor_kind}</code>
                  {a.target_source && (
                    <> · target=<code>{a.target_source}</code></>
                  )}{" "}
                  · {a.argument_count} arg{a.argument_count === 1 ? "" : "s"}
                </div>
                {a.description && (
                  <div style={{ fontSize: 11, color: "var(--ink-soft)", marginTop: 4 }}>
                    {a.description}
                  </div>
                )}
              </div>
              {!a.default && (
                <button onClick={() => onDelete(a.id)} className="ds-danger" style={{ fontSize: 11 }}>
                  Remove
                </button>
              )}
            </div>
          </div>
        ))}
      </div>

      <div style={{ fontSize: 12, fontWeight: 600, marginBottom: 6 }}>
        Preview an NL pick
      </div>
      <div style={{ fontSize: 11, color: "var(--ink-soft)", marginBottom: 6 }}>
        Type a prompt to see which action the picker would propose plus
        the extracted arguments. Nothing runs — this is a sanity check
        before enabling the composer fallback.
      </div>
      <div style={{ display: "flex", gap: 6, marginBottom: 8 }}>
        <input
          value={previewPrompt}
          onChange={(e) => setPreviewPrompt(e.target.value)}
          placeholder="e.g. reattribute case PR-2026-Q1-088 to compliance.officer.kchen"
          disabled={busy}
          style={{ flex: 1, fontSize: 12, padding: "4px 6px" }}
        />
        <button onClick={onPreview} disabled={busy || !previewPrompt.trim() || actions.length === 0}>
          {busy ? "…" : "Preview"}
        </button>
      </div>
      {preview && (
        <div
          style={{
            padding: 10,
            border: "1px solid var(--cyan)",
            background: "rgba(0,201,183,0.05)",
            borderRadius: 4,
            fontSize: 12,
          }}
        >
          <div style={{ fontWeight: 600, marginBottom: 4 }}>
            Picked: <code>{preview.action_id}</code> ({preview.title})
          </div>
          <div style={{ fontSize: 11, color: "var(--ink-soft)", marginBottom: 4 }}>
            executor=<code>{preview.executor_kind}</code>
            {preview.target_source && (
              <> · target=<code>{preview.target_source}</code></>
            )}{" "}
            · confidence={(preview.confidence * 100).toFixed(0)}%
            {preview.hitl ? " · HITL" : " · auto-execute"}
          </div>
          <div style={{ fontSize: 11, color: "var(--ink-soft)", marginBottom: 4 }}>
            <em>{preview.rationale}</em>
          </div>
          <pre
            style={{
              fontSize: 11,
              padding: 6,
              background: "white",
              border: "1px solid var(--border)",
              borderRadius: 3,
              margin: 0,
              whiteSpace: "pre-wrap",
            }}
          >
            {JSON.stringify(preview.arguments, null, 2)}
          </pre>
        </div>
      )}
    </div>
  );
}

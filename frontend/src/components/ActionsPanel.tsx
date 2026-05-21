import { useEffect, useState } from "react";
import * as api from "../api";
import { ActionSummary } from "../api";

// Inline panel mounted inside the Knowledge modal's Actions tab.
// Lists registered write actions and lets the operator remove non-default
// ones. Write actions are referenced by hand-authored scenarios via an
// `_executor` block; the orchestrator runs them on autonomous or
// post-approval paths.

export function ActionsPanel() {
  const [actions, setActions] = useState<ActionSummary[]>([]);
  const [error, setError] = useState<string | null>(null);

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
        Registered write actions used by hand-authored scenarios. A
        scenario opts in by adding an <code>_executor</code> block naming
        an action id and its arguments; the orchestrator runs the named
        executor on autonomous or post-approval paths.
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
    </div>
  );
}

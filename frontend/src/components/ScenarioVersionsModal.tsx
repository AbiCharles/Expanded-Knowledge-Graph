/**
 * Read-only version-history viewer for a scenario.
 *
 * Lists every saved version (newest-first) with timestamp + title.
 * Clicking a row reveals the full content of that version by fetching
 * `/api/scenarios/{id}?version=N` and rendering the same humanised
 * sections the Case-spec modal uses — but stripped down: we just dump
 * the YAML-shaped dict into a `<pre>` here, since this is for engineers
 * verifying that the right state was preserved.
 */
import { useEffect, useState } from "react";
import * as api from "../api";

export function ScenarioVersionsModal({
  scenarioId,
  onClose,
}: {
  scenarioId: string;
  onClose: () => void;
}) {
  const [versions, setVersions] = useState<api.ScenarioVersionRow[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [selected, setSelected] = useState<number | null>(null);
  const [selectedContent, setSelectedContent] = useState<any | null>(null);

  useEffect(() => {
    let cancelled = false;
    api
      .listScenarioVersions(scenarioId)
      .then((rows) => { if (!cancelled) setVersions(rows); })
      .catch((e) => { if (!cancelled) setError((e as Error).message); });
    return () => { cancelled = true; };
  }, [scenarioId]);

  useEffect(() => {
    if (selected == null) {
      setSelectedContent(null);
      return;
    }
    let cancelled = false;
    api
      .getScenarioFull(scenarioId, { version: selected })
      .then((d) => { if (!cancelled) setSelectedContent(d); })
      .catch((e) => { if (!cancelled) setError((e as Error).message); });
    return () => { cancelled = true; };
  }, [scenarioId, selected]);

  return (
    <div
      className="modal-backdrop scenario-versions-backdrop"
      onClick={(e) => e.target === e.currentTarget && onClose()}
    >
      <div className="ds-modal scenario-versions-modal" style={{ maxWidth: 880, width: "92vw" }}>
        <div className="ds-header">
          <div>
            <div className="ds-eyebrow">Version history · {scenarioId}</div>
            <div className="ds-title">
              {versions ? `${versions.length} saved version${versions.length === 1 ? "" : "s"}` : "Loading…"}
            </div>
          </div>
          <button className="teams-close" onClick={onClose}>×</button>
        </div>

        {error && <div className="ds-error" style={{ margin: 16 }}>{error}</div>}

        {versions && versions.length > 0 && (
          <div className="scenario-versions-body">
            <div className="scenario-versions-list">
              {versions.map((row) => (
                <button
                  key={row.version}
                  type="button"
                  className={`scenario-versions-row${selected === row.version ? " active" : ""}`}
                  onClick={() => setSelected(row.version)}
                >
                  <span className="scenario-versions-num">v{row.version}</span>
                  <span className="scenario-versions-title">{row.title || "(untitled)"}</span>
                  <span className="scenario-versions-when">
                    {row.saved_at ? new Date(row.saved_at * 1000).toLocaleString() : "—"}
                  </span>
                </button>
              ))}
            </div>
            <div className="scenario-versions-detail">
              {selected == null && (
                <div className="scenario-versions-hint">
                  Click a version on the left to read its full content.
                </div>
              )}
              {selected != null && !selectedContent && (
                <div className="scenario-versions-hint">Loading v{selected}…</div>
              )}
              {selectedContent && (
                <pre className="scenario-versions-yaml">
                  {JSON.stringify(selectedContent, null, 2)}
                </pre>
              )}
            </div>
          </div>
        )}

        {versions && versions.length === 0 && (
          <div className="scenario-versions-hint" style={{ padding: 24 }}>
            No saved versions yet — this scenario was created in memory and
            hasn't been persisted to disk.
          </div>
        )}
      </div>
    </div>
  );
}

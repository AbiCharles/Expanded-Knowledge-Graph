import { useState } from "react";
import { ActionsPanel } from "./ActionsPanel";
import { DataSourcesModal } from "./DataSourcesModal";
import { OntologyModal } from "./OntologyModal";

// One modal containing the three knowledge-plane panels (Data sources,
// Ontologies, Actions) as tabs. Each child component is mounted in
// `embedded` mode where applicable — they suppress their own backdrop +
// header so we can supply them at this level.

export type KnowledgeTab = "sources" | "ontologies" | "actions";

export function KnowledgeModal({
  initialTab = "sources",
  onClose,
  onScenariosChanged,
}: {
  initialTab?: KnowledgeTab;
  onClose: () => void;
  onScenariosChanged?: () => void;
}) {
  const [tab, setTab] = useState<KnowledgeTab>(initialTab);

  return (
    <div
      className="modal-backdrop"
      onClick={(e) => e.target === e.currentTarget && onClose()}
    >
      <div className="ds-modal" style={{ maxWidth: 1100, width: "92vw" }}>
        <div className="ds-header">
          <div>
            <div className="ds-eyebrow">Knowledge</div>
            <div className="ds-title">
              {tab === "sources"
                ? "Connections & uploads"
                : tab === "ontologies"
                  ? "Schema + source mappings"
                  : "Write actions"}
            </div>
          </div>
          <button className="teams-close" onClick={onClose}>
            ×
          </button>
        </div>

        <div
          style={{
            display: "flex",
            gap: 4,
            padding: "0 16px",
            borderBottom: "1px solid var(--border)",
          }}
        >
          <KnowledgeTabButton active={tab === "sources"} onClick={() => setTab("sources")}>
            Data sources
          </KnowledgeTabButton>
          <KnowledgeTabButton active={tab === "ontologies"} onClick={() => setTab("ontologies")}>
            Ontologies
          </KnowledgeTabButton>
          <KnowledgeTabButton active={tab === "actions"} onClick={() => setTab("actions")}>
            Actions
          </KnowledgeTabButton>
        </div>

        {tab === "sources" && (
          <DataSourcesModal
            embedded
            onClose={onClose}
            onScenariosChanged={onScenariosChanged}
          />
        )}
        {tab === "ontologies" && (
          <OntologyModal
            embedded
            onClose={onClose}
            onScenariosChanged={onScenariosChanged}
          />
        )}
        {tab === "actions" && <ActionsPanel />}
      </div>
    </div>
  );
}

function KnowledgeTabButton({
  active,
  onClick,
  children,
}: {
  active: boolean;
  onClick: () => void;
  children: React.ReactNode;
}) {
  return (
    <button
      onClick={onClick}
      style={{
        background: "none",
        border: "none",
        borderBottom: active ? "2px solid var(--cyan)" : "2px solid transparent",
        padding: "10px 14px",
        fontSize: 13,
        fontWeight: active ? 600 : 400,
        cursor: "pointer",
      }}
    >
      {children}
    </button>
  );
}

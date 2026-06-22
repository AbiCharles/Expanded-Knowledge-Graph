// Type shims for graph libraries that don't ship their own .d.ts.
// Kept loose — we only need React + Cytoscape + dagre to compile; the
// frontend's strict-mode checks live in our own components.

// Vite injects import.meta.env at build time; declare the shape so
// TypeScript stops complaining about VITE_* references.
interface ImportMetaEnv {
  readonly VITE_AGENT_ORCHESTRATOR_URL?: string;
}
interface ImportMeta {
  readonly env: ImportMetaEnv;
}

declare module "cytoscape-dagre";
declare module "react-cytoscapejs" {
  import { ComponentType, CSSProperties } from "react";
  import cytoscape from "cytoscape";
  interface CytoscapeComponentProps {
    elements: cytoscape.ElementDefinition[];
    stylesheet?: any;
    style?: CSSProperties;
    layout?: any;
    cy?: (cy: cytoscape.Core) => void;
    minZoom?: number;
    maxZoom?: number;
    zoom?: number;
    pan?: { x?: number; y?: number };
    wheelSensitivity?: number;
  }
  const CytoscapeComponent: ComponentType<CytoscapeComponentProps>;
  export default CytoscapeComponent;
}

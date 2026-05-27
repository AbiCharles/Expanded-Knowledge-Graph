// Type shims for graph libraries that don't ship their own .d.ts.
// Kept loose — we only need React + Cytoscape + dagre to compile; the
// frontend's strict-mode checks live in our own components.

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

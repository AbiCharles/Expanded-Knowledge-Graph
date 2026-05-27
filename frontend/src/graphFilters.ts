// Persistent per-node-type visibility filter for the knowledge graph. Read by
// both the inline GraphPanel/EvidenceMap and the full-page modal; written by
// the LineagePanel's Filters tab AND the modal's collapsible left rail. Two
// entry points, one source of truth.

export type GraphFilterType =
  | "anchor"
  | "Supplier"
  | "Carrier"
  | "Alliance"
  | "HoldingCompany"
  | "SanctionedNetworkEntity";

export interface GraphFilterDef {
  id: GraphFilterType;
  label: string;
  swatch: string;
}

export const GRAPH_FILTER_TYPES: GraphFilterDef[] = [
  { id: "anchor", label: "Anchor (case subject)", swatch: "anchor" },
  { id: "SanctionedNetworkEntity", label: "Sanctioned network entity", swatch: "sanctioned" },
  { id: "Supplier", label: "Supplier", swatch: "supplier" },
  { id: "HoldingCompany", label: "Holding company", swatch: "holding" },
  { id: "Carrier", label: "Carrier", swatch: "carrier" },
  { id: "Alliance", label: "Alliance", swatch: "alliance" },
];

const STORAGE_KEY = "kf-graph-hidden-types";

// Module-local subscribers — keep the strip and modal in sync without going
// through React context (the modal is mounted lazily and not all consumers
// share an ancestor).
const listeners = new Set<(next: Set<GraphFilterType>) => void>();

export function getHiddenGraphTypes(): Set<GraphFilterType> {
  if (typeof window === "undefined") return new Set();
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    if (!raw) return new Set();
    const parsed = JSON.parse(raw);
    if (!Array.isArray(parsed)) return new Set();
    return new Set(parsed.filter((s): s is GraphFilterType =>
      typeof s === "string" && GRAPH_FILTER_TYPES.some((t) => t.id === s)
    ));
  } catch {
    return new Set();
  }
}

export function setHiddenGraphTypes(next: Set<GraphFilterType>): void {
  try {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(Array.from(next)));
  } catch { /* private mode */ }
  listeners.forEach((fn) => fn(new Set(next)));
}

export function subscribeHiddenGraphTypes(fn: (next: Set<GraphFilterType>) => void): () => void {
  listeners.add(fn);
  return () => listeners.delete(fn);
}

// Decide whether a Cytoscape node should be hidden given the current filter
// set. The "anchor" filter targets nodes flagged accent=anchor regardless of
// their ontology type, so we accept the runtime node data directly.
export function nodeHiddenBy(
  hidden: Set<GraphFilterType>,
  nodeType: string | undefined,
  accent: string | undefined,
): boolean {
  if (hidden.size === 0) return false;
  // Anchor nodes are governed ONLY by the "anchor" toggle — hiding them with
  // the broader Supplier filter would zero out the case subject. So if a node
  // is the anchor, the anchor flag is the only switch that hides it.
  if (accent === "anchor") return hidden.has("anchor");
  if (nodeType && GRAPH_FILTER_TYPES.some((t) => t.id === nodeType)) {
    return hidden.has(nodeType as GraphFilterType);
  }
  return false;
}

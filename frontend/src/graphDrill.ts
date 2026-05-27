// Per-data-source drill-down registry for the evidence map + platform-flow
// modals. When a node in those views is double-clicked, we look up its
// `data.drill_kind` here, ask the matching handler what to navigate to,
// and the surrounding component opens the corresponding drill modal.
//
// Today only `neo4j` has a handler (opens the knowledge-graph view).
// CSV / Vector / SQL / HTTP can plug in later without changing the click
// detection or the stylesheet.

import { CaseFull } from "./types";

export interface GraphAnchor {
  supplier_id: string;
  supplierName: string;
}

export type DrillTarget =
  | { kind: "knowledge-graph"; anchor: GraphAnchor };

export interface DrillHandler {
  // Used to decide whether to render the corner glyph on a node and
  // whether to hide the side-legend hint line.
  available: (active: CaseFull) => boolean;
  // What drill target should we navigate to? Null = no-op even if the
  // node was tagged (e.g. case lost its anchor between renders).
  target: (active: CaseFull) => DrillTarget | null;
  // One-line side-legend hint surfaced when the handler is available.
  hint: string;
}

export const DRILL_HANDLERS: Record<string, DrillHandler> = {
  neo4j: {
    available: (active) => findGraphAnchor(active) !== null,
    target: (active) => {
      const a = findGraphAnchor(active);
      return a ? { kind: "knowledge-graph", anchor: a } : null;
    },
    hint: "Double-click any Neo4j-backed node ⤢ to open the knowledge graph.",
  },
};

// Walk the case's facts looking for the first Supplier whose source
// starts with `neo4j:`. That's the implicit "anchor" the knowledge graph
// modal traverses outward from. Used by GraphPanel (its standalone
// Knowledge-graph card) AND by the Neo4j drill handler.
export function findGraphAnchor(active: CaseFull): GraphAnchor | null {
  for (const stage of active.stages || []) {
    for (const f of stage.facts) {
      if (f.ontology_type === "Supplier" && (f.source || "").startsWith("neo4j:")) {
        return {
          supplier_id: f.id,
          supplierName: f.title || f.id,
        };
      }
    }
  }
  return null;
}

// SVG data URI for the corner glyph drawn on drillable nodes. Indigo
// "expand" arrow (⤢) inside a 16×16 box. Cytoscape's `background-image`
// with `background-position: 100% 0%` + a small negative offset puts it
// just inside the node's top-right corner.
//
// Memoised — Cytoscape compares data URIs as strings; generating once
// keeps `data.drill_glyph_uri` stable across re-renders.
const _GLYPH_CACHE: Record<string, string> = {};

export function drillGlyphSvgUri(color = "#4f46e5"): string {
  if (_GLYPH_CACHE[color]) return _GLYPH_CACHE[color];
  const svg =
    `<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 16 16'>` +
    `<text x='8' y='12' text-anchor='middle' fill='${color}' ` +
    `font-family='-apple-system,BlinkMacSystemFont,Inter,sans-serif' ` +
    `font-size='13' font-weight='700'>⤢</text>` +
    `</svg>`;
  const uri = `data:image/svg+xml;utf8,${encodeURIComponent(svg)}`;
  _GLYPH_CACHE[color] = uri;
  return uri;
}

// Helper consumed by buildEvidenceElements / buildPlatformFlowElements
// to decide whether a class/source node should be tagged drillable.
// Returns the matching kind (e.g. "neo4j") or null.
export function drillKindFor(sourceKinds: Iterable<string>, active: CaseFull): string | null {
  for (const k of sourceKinds) {
    const handler = DRILL_HANDLERS[k];
    if (handler && handler.available(active)) return k;
  }
  return null;
}

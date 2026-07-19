"""Graph-visualization endpoints.

Exposes the data the frontend's GraphPanel needs to render a focused
Cytoscape view: the supplier's neighborhood, sanctioned-network reach
(shortest paths), and carrier-alliance peers. Pure read-side; doesn't
mutate Neo4j.

Used by SC-PP-008 (supplier onboarding) to render a visual "how the
agent reached this risk picture" alongside the fact cards.
"""
from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from ..auth import CurrentUser, current_user
from ..datasources.neo4j_source import Neo4jResolver

log = logging.getLogger(__name__)

router = APIRouter(prefix="/graph", tags=["graph"])


# =============================================================================
# Models
# =============================================================================
class SubgraphRequest(BaseModel):
    supplier_id: str = Field(..., description="Anchor supplier id, e.g. 'SUP-001'")
    depth: int = Field(4, ge=1, le=6, description="Max hops for sanctions traversal")
    data_source: str = Field("neo4j_default", description="Registered Neo4j source")


class GraphNode(BaseModel):
    id: str
    label: str
    type: str
    accent: str = ""   # "anchor" | "risk" | "risk_path" | "alt"
    # Ontology binding (populated by the evidence subgraph so the UI can open
    # the class spec when a node is clicked). Empty for the supplier subgraph.
    ontology: str = ""
    ontology_class: str = ""


class GraphEdge(BaseModel):
    source: str
    target: str
    type: str
    accent: str = ""   # "risk_path" | ""


class SubgraphResponse(BaseModel):
    nodes: list[GraphNode] = Field(default_factory=list)
    edges: list[GraphEdge] = Field(default_factory=list)
    stats: dict[str, int] = Field(default_factory=dict)


# =============================================================================
# Cypher queries — each returns flat tabular rows the existing
# run_cypher() can serialize without losing data.
# =============================================================================
# 1) Anchor + its 1-hop corporate / sourcing network (Supplier + HoldingCompany
#    + immediate buyers/sellers), PLUS sibling-via-shared-holding suppliers
#    (so AlternativeSupplier candidates from the case render in the graph),
#    PLUS the program-impact path (anchor ← SOURCES_FROM ← tier-1 → PO →
#    Product → Program) so AT-RISK PROGRAM nodes show too.
#
# The three UNION branches all RETURN the same 8-column shape, which the
# caller unwinds into nodes/edges via _row_cell. Cypher UNION requires
# identical column names in each branch.
_NETWORK_CYPHER = """
MATCH (s:Supplier {supplier_id: $supplier_id})
OPTIONAL MATCH (s)-[r:PARENT_OF|JOINT_VENTURE_WITH|CONTROLLED_BY|SOURCES_FROM]-(neighbor)
RETURN coalesce(s.supplier_id, '?') AS src_id,
       s.name AS src_name,
       labels(s)[0] AS src_type,
       type(r) AS rel,
       startNode(r) = s AS rel_outgoing,
       coalesce(neighbor.supplier_id, neighbor.holding_id, '?') AS dst_id,
       neighbor.name AS dst_name,
       labels(neighbor)[0] AS dst_type

UNION

// Siblings via a shared HoldingCompany — surfaces AlternativeSupplier
// candidates (the holding sits between the anchor and the sibling).
MATCH (s:Supplier {supplier_id: $supplier_id})-[:CONTROLLED_BY]->(h:HoldingCompany)
MATCH (h)<-[r:CONTROLLED_BY]-(sibling:Supplier)
WHERE sibling <> s
RETURN h.holding_id AS src_id,
       h.name AS src_name,
       'HoldingCompany' AS src_type,
       type(r) AS rel,
       false AS rel_outgoing,
       sibling.supplier_id AS dst_id,
       sibling.name AS dst_name,
       labels(sibling)[0] AS dst_type

UNION

// Program-impact path edges — unwound to one row per edge, same shape as
// the corporate network. Lets the graph render Mirage/Viper/Comet (and the
// SKUs they consume) next to the tier-1 buyers that channel the exposure.
MATCH (s:Supplier {supplier_id: $supplier_id})
MATCH path = (s)<-[:SOURCES_FROM]-(buyer:Supplier)-[:PLACED]->(po:PurchaseOrder)-[:CONTAINS]->(prod:Product)-[:INCLUDED_IN]->(prg:Program)
WITH path, nodes(path) AS ns, relationships(path) AS rs
UNWIND range(0, size(rs) - 1) AS i
WITH ns[i] AS src, rs[i] AS r, ns[i+1] AS dst
RETURN coalesce(src.supplier_id, src.po_id, src.product_id, src.program_id, '?') AS src_id,
       coalesce(src.name, '') AS src_name,
       labels(src)[0] AS src_type,
       type(r) AS rel,
       startNode(r) = src AS rel_outgoing,
       coalesce(dst.supplier_id, dst.po_id, dst.product_id, dst.program_id, '?') AS dst_id,
       coalesce(dst.name, '') AS dst_name,
       labels(dst)[0] AS dst_type
"""

# 2) All shortest paths from the supplier to a SanctionedNetworkEntity, up to
#    `depth` hops, unwound one row per edge so we don't have to parse a Path.
_SANCTIONS_CYPHER = """
MATCH p = shortestPath((s:Supplier {supplier_id: $supplier_id})-[*1..$depth]-(sdn:SanctionedNetworkEntity))
WITH p, nodes(p) AS ns, relationships(p) AS rs
UNWIND range(0, size(rs) - 1) AS i
WITH ns[i] AS src, rs[i] AS r, ns[i+1] AS dst
RETURN coalesce(src.supplier_id, src.holding_id, src.entity_id, '?') AS src_id,
       coalesce(src.name, '') AS src_name,
       labels(src)[0] AS src_type,
       type(r) AS rel,
       startNode(r) = src AS rel_outgoing,
       coalesce(dst.supplier_id, dst.holding_id, dst.entity_id, '?') AS dst_id,
       coalesce(dst.name, '') AS dst_name,
       labels(dst)[0] AS dst_type
"""

# 3) Carrier + alliance + peer-carrier reach.
_ALLIANCE_CYPHER = """
MATCH (s:Supplier {supplier_id: $supplier_id})-[:SHIPS_VIA]->(c:Carrier)-[:MEMBER_OF]->(a:Alliance)<-[:MEMBER_OF]-(peer:Carrier)
WHERE peer <> c
WITH s, c, a, peer
RETURN s.supplier_id AS s_id, s.name AS s_name,
       c.carrier_id  AS c_id, c.name AS c_name,
       a.alliance_id AS a_id, a.name AS a_name,
       peer.carrier_id AS p_id, peer.name AS p_name
"""


# =============================================================================
# Endpoint
# =============================================================================
@router.post("/subgraph", response_model=SubgraphResponse)
def supplier_subgraph(
    payload: SubgraphRequest,
    request: Request,
    _user: CurrentUser = Depends(current_user),
) -> SubgraphResponse:
    state = request.app.state.app_state
    source = state.data_sources.get(payload.data_source)
    if source is None:
        raise HTTPException(404, f"data_source {payload.data_source!r} not registered")
    if not isinstance(source, Neo4jResolver):
        raise HTTPException(400, f"data_source {payload.data_source!r} is not Neo4j")

    nodes: dict[str, GraphNode] = {}
    edges: list[GraphEdge] = []

    def _upsert_node(nid: str, name: str, typ: str, accent: str = "") -> str:
        nid = (nid or "").strip()
        if not nid:
            return ""
        if nid in nodes:
            if accent and not nodes[nid].accent:
                nodes[nid].accent = accent
            return nid
        nodes[nid] = GraphNode(
            id=nid,
            label=name or nid,
            type=typ or "Node",
            accent=accent,
        )
        return nid

    def _row_cell(cols: list[str], row: list, key: str) -> Any:
        return row[cols.index(key)] if key in cols else None

    # 1) Corporate network. Only the case subject gets accent="anchor" —
    # every other node coming back from this cypher (HoldingCompany on
    # branch 2, buyer/PO/Product/Program on branch 3) shows up as `src`
    # in some row but is NOT the failing supplier. Previously they all
    # inherited the anchor accent, which made the whole graph render as
    # deep teal "failing-supplier" nodes. The frontend per-type styles
    # will colour them by ontology type when accent is empty.
    net = source.run_cypher(_NETWORK_CYPHER, {"supplier_id": payload.supplier_id})
    cols = net.get("columns") or []
    for row in (net.get("rows") or []):
        src_id  = _row_cell(cols, row, "src_id")
        src_accent = "anchor" if src_id == payload.supplier_id else ""
        _upsert_node(src_id, _row_cell(cols, row, "src_name"),
                     _row_cell(cols, row, "src_type"), accent=src_accent)
        dst_id = _row_cell(cols, row, "dst_id")
        if dst_id and dst_id != "?":
            dst_accent = "anchor" if dst_id == payload.supplier_id else ""
            _upsert_node(dst_id, _row_cell(cols, row, "dst_name"),
                         _row_cell(cols, row, "dst_type"), accent=dst_accent)
            rel = _row_cell(cols, row, "rel")
            outgoing = _row_cell(cols, row, "rel_outgoing")
            if rel:
                a, b = (src_id, dst_id) if outgoing else (dst_id, src_id)
                edges.append(GraphEdge(source=a, target=b, type=rel))

    # 2) Sanctions paths — paint nodes + edges along the risk path
    sanc = source.run_cypher(
        _SANCTIONS_CYPHER.replace("$depth", str(payload.depth)),
        {"supplier_id": payload.supplier_id},
    )
    sanc_paths = 0
    cols = sanc.get("columns") or []
    for row in (sanc.get("rows") or []):
        sanc_paths += 1
        src_id  = _row_cell(cols, row, "src_id")
        dst_id  = _row_cell(cols, row, "dst_id")
        rel     = _row_cell(cols, row, "rel")
        outgoing = _row_cell(cols, row, "rel_outgoing")
        src_typ = _row_cell(cols, row, "src_type") or ""
        dst_typ = _row_cell(cols, row, "dst_type") or ""
        # SanctionedNetworkEntity gets the "risk" accent so the frontend
        # can colour it red. Other intermediate nodes on the path get
        # "risk_path" (lighter accent).
        src_accent = "risk" if src_typ == "SanctionedNetworkEntity" else "risk_path"
        dst_accent = "risk" if dst_typ == "SanctionedNetworkEntity" else "risk_path"
        # Don't override the anchor's "anchor" accent
        if src_id == payload.supplier_id: src_accent = "anchor"
        if dst_id == payload.supplier_id: dst_accent = "anchor"
        _upsert_node(src_id, _row_cell(cols, row, "src_name"), src_typ, src_accent)
        _upsert_node(dst_id, _row_cell(cols, row, "dst_name"), dst_typ, dst_accent)
        a, b = (src_id, dst_id) if outgoing else (dst_id, src_id)
        edges.append(GraphEdge(source=a, target=b, type=rel or "REL", accent="risk_path"))

    # 3) Alliance reach
    alli = source.run_cypher(_ALLIANCE_CYPHER, {"supplier_id": payload.supplier_id})
    cols = alli.get("columns") or []
    alliance_peer_count = 0
    for row in (alli.get("rows") or []):
        alliance_peer_count += 1
        s_id = _row_cell(cols, row, "s_id")
        c_id = _row_cell(cols, row, "c_id"); c_name = _row_cell(cols, row, "c_name")
        a_id = _row_cell(cols, row, "a_id"); a_name = _row_cell(cols, row, "a_name")
        p_id = _row_cell(cols, row, "p_id"); p_name = _row_cell(cols, row, "p_name")
        _upsert_node(c_id, c_name, "Carrier", accent="alt")
        _upsert_node(a_id, a_name, "Alliance", accent="alt")
        _upsert_node(p_id, p_name, "Carrier", accent="alt")
        edges.append(GraphEdge(source=s_id, target=c_id, type="SHIPS_VIA"))
        edges.append(GraphEdge(source=c_id, target=a_id, type="MEMBER_OF"))
        edges.append(GraphEdge(source=p_id, target=a_id, type="MEMBER_OF"))

    # De-dupe edges (the queries can produce the same (src, target, type) triple
    # more than once because shortest paths share edges with the network query).
    seen: set[tuple[str, str, str]] = set()
    deduped: list[GraphEdge] = []
    for e in edges:
        key = (e.source, e.target, e.type)
        if key in seen:
            continue
        seen.add(key)
        deduped.append(e)

    return SubgraphResponse(
        nodes=list(nodes.values()),
        edges=deduped,
        stats={
            "nodes": len(nodes),
            "edges": len(deduped),
            "sanctions_paths_segments": sanc_paths,
            "alliance_peers": alliance_peer_count,
        },
    )


# =============================================================================
# Evidence subgraph — the manufacturing_rca evidence chain for a defect.
# Renders Part → Defect → EvidenceNode(visual/log/inference/root_cause) plus the
# SUPPORTS / INDICATES causal edges, reusing the same {nodes, edges} contract
# the GraphModal already knows how to draw. Node accents are mapped so the
# existing knowledge stylesheet colours the chain without new CSS.
# =============================================================================
class EvidenceRequest(BaseModel):
    case_id: str = Field("", description="Case to resolve part_id from (optional if part_id given)")
    part_id: str = Field("", description="Anchor part id, e.g. 'P-1234'. Overrides case lookup.")
    data_source: str = Field("neo4j_default", description="Registered Neo4j source")


# One row per edge in the evidence subgraph, 9 identical columns across the
# three UNION branches so run_cypher() can serialise them flat.
_EVIDENCE_CYPHER = """
MATCH (p:Part {part_id: $part_id})-[:HAS_DEFECT]->(d:Defect {part_id: $part_id})
RETURN p.part_id AS src_id, p.name AS src_name, 'Part' AS src_type, '' AS src_kind,
       'HAS_DEFECT' AS rel,
       d.defect_id AS dst_id, coalesce(d.defect_type, 'defect') AS dst_name,
       'Defect' AS dst_type, '' AS dst_kind

UNION

MATCH (d:Defect {part_id: $part_id})-[:EVIDENCED_BY]->(e:EvidenceNode)
RETURN d.defect_id AS src_id, coalesce(d.defect_type, 'defect') AS src_name,
       'Defect' AS src_type, '' AS src_kind,
       'EVIDENCED_BY' AS rel,
       e.node_id AS dst_id, e.description AS dst_name,
       'EvidenceNode' AS dst_type, coalesce(e.node_type, '') AS dst_kind

UNION

MATCH (e1:EvidenceNode {part_id: $part_id})-[r:SUPPORTS|INDICATES]->(e2:EvidenceNode)
RETURN e1.node_id AS src_id, e1.description AS src_name,
       'EvidenceNode' AS src_type, coalesce(e1.node_type, '') AS src_kind,
       type(r) AS rel,
       e2.node_id AS dst_id, e2.description AS dst_name,
       'EvidenceNode' AS dst_type, coalesce(e2.node_type, '') AS dst_kind
"""

# Map (neo4j label, EvidenceNode.node_type) → (legend display type, accent).
# Accents reuse the knowledge stylesheet's existing palette so no CSS is added:
#   anchor=teal · risk=red · risk_path=amber · alt=purple · default=grey.
_EVIDENCE_STYLE = {
    "visual": ("Visual finding", "alt"),
    "log": ("Log finding", "default"),
    "inference": ("Inference", "risk_path"),
    "root_cause": ("Root cause", "risk"),
}


def _evidence_style(typ: str, kind: str) -> tuple[str, str]:
    if typ == "Defect":
        return ("Defect", "anchor")
    if typ == "Part":
        return ("Part", "default")
    return _EVIDENCE_STYLE.get((kind or "").strip().lower(), ("Evidence", "default"))


def _evidence_class(typ: str) -> str:
    """The manufacturing_rca ontology class a graph node maps to."""
    if typ in ("Part", "Defect"):
        return typ
    return "EvidenceNode"


@router.post("/evidence", response_model=SubgraphResponse)
def evidence_subgraph(
    payload: EvidenceRequest,
    request: Request,
    _user: CurrentUser = Depends(current_user),
) -> SubgraphResponse:
    state = request.app.state.app_state

    # Resolve the part_id: explicit arg wins; otherwise pull it off the case's
    # scenario action_payload (the manufacturing_rca scenarios carry part_id).
    part_id = (payload.part_id or "").strip()
    if not part_id and payload.case_id:
        case = state.cases.get(payload.case_id)
        if case is not None and case.scenario_id:
            sc = state.scenarios.get(case.scenario_id)
            if sc:
                part_id = str((sc.get("action_payload") or {}).get("part_id") or "")
    if not part_id:
        raise HTTPException(400, "no part_id (pass part_id, or a case_id whose scenario carries one)")

    source = state.data_sources.get(payload.data_source)
    if source is None:
        raise HTTPException(404, f"data_source {payload.data_source!r} not registered")
    if not isinstance(source, Neo4jResolver):
        raise HTTPException(400, f"data_source {payload.data_source!r} is not Neo4j")

    nodes: dict[str, GraphNode] = {}
    edges: list[GraphEdge] = []

    def _row_cell(cols: list[str], row: list, key: str) -> Any:
        return row[cols.index(key)] if key in cols else None

    def _upsert(nid: str, name: str, typ: str, kind: str) -> str:
        nid = (nid or "").strip()
        if not nid or nid == "?":
            return ""
        display_type, accent = _evidence_style(typ, kind)
        if nid not in nodes:
            nodes[nid] = GraphNode(
                id=nid, label=name or nid, type=display_type, accent=accent,
                ontology="manufacturing_rca", ontology_class=_evidence_class(typ),
            )
        return nid

    res = source.run_cypher(_EVIDENCE_CYPHER, {"part_id": part_id})
    cols = res.get("columns") or []
    for row in (res.get("rows") or []):
        s = _upsert(
            _row_cell(cols, row, "src_id"), _row_cell(cols, row, "src_name"),
            _row_cell(cols, row, "src_type"), _row_cell(cols, row, "src_kind"),
        )
        t = _upsert(
            _row_cell(cols, row, "dst_id"), _row_cell(cols, row, "dst_name"),
            _row_cell(cols, row, "dst_type"), _row_cell(cols, row, "dst_kind"),
        )
        rel = _row_cell(cols, row, "rel")
        if s and t and rel:
            # Highlight the causal spine (…→ root cause) so it reads as a path.
            accent = "risk_path" if rel in ("SUPPORTS", "INDICATES") else ""
            edges.append(GraphEdge(source=s, target=t, type=rel, accent=accent))

    seen: set[tuple[str, str, str]] = set()
    deduped: list[GraphEdge] = []
    for e in edges:
        key = (e.source, e.target, e.type)
        if key not in seen:
            seen.add(key)
            deduped.append(e)

    return SubgraphResponse(
        nodes=list(nodes.values()),
        edges=deduped,
        stats={"nodes": len(nodes), "edges": len(deduped)},
    )

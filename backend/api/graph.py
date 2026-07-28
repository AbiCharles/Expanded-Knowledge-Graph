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
from ..case_history import decision_history_provider
from ..datasources.neo4j_source import Neo4jResolver
from ..outcome_plan import OutcomePlan
from ..scenario_composer import compose

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
# Outcome tree — stitch multiple scenarios into a probability-weighted DAG
# =============================================================================
class OutcomeTreeRequest(BaseModel):
    question: str = Field(..., min_length=1, description="The complex user question")
    scenario_ids: list[str] = Field(
        ...,
        min_length=1,
        max_length=8,
        description="Scenarios to stitch together, in pipeline (compose) order",
    )
    # Optional signals the hybrid probability model can fold in, e.g.
    # {"reliability_score": 0.82} or
    # {"reliability_by_scenario": {"SC-PP-AERONOVA-026": 0.82}}.
    context: dict[str, Any] = Field(default_factory=dict)


@router.post("/outcome-tree", response_model=OutcomePlan)
def outcome_tree(
    payload: OutcomeTreeRequest,
    request: Request,
    _user: CurrentUser = Depends(current_user),
) -> OutcomePlan:
    """Compose several scenarios into one probability-weighted Outcome DAG.

    The scenarios chain into a pipeline; each decision fans out into
    branches whose weights come from author overrides, then historical
    case frequencies, then defaults (see backend/probability.py). Returns
    the nodes/edges the frontend renders plus a ranked ``outcomes`` list.
    """
    state = request.app.state.app_state
    provider = decision_history_provider(state.database)
    try:
        return compose(
            payload.question,
            payload.scenario_ids,
            scenarios=state.scenarios,
            history_provider=provider,
            context=payload.context or {},
        )
    except KeyError as exc:
        raise HTTPException(404, f"unknown scenario_id: {exc}")

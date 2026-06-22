"""HTTP client for calling the Knowledge Fabric.

Auths against the fabric using the admin-password JWT flow (same
HITL_ADMIN_PASSWORD secret the fabric already has). The JWT is cached
on the client instance and reused for the rest of the process
lifetime; it'll auto-renew if a 401 ever comes back.

One call to POST /api/graph/subgraph returns enough nodes+edges to
answer the orchestrator's three investigation questions. This module
also carries the parsers that extract:
  - tier-1 buyers (suppliers that SOURCES_FROM the failing anchor)
  - at-risk programs (Program terminals on INCLUDED_IN chains)
  - alternate suppliers (JV partners + shared-HoldingCompany siblings)
"""
from __future__ import annotations

import logging
import os
from typing import Any, Optional
from urllib.parse import quote, urlencode

import httpx

log = logging.getLogger(__name__)


class FabricClient:
    """Thin httpx wrapper around the Knowledge Fabric HTTP API."""

    def __init__(
        self,
        *,
        base_url: Optional[str] = None,
        admin_password: Optional[str] = None,
        admin_username: str = "admin",
        timeout: float = 20.0,
    ):
        self.base_url = (
            base_url
            or os.environ.get("FABRIC_BASE_URL")
            or "https://tcs-knowledge-fabric.fly.dev"
        ).rstrip("/")
        self.admin_password = admin_password or os.environ.get("HITL_ADMIN_PASSWORD", "")
        self.admin_username = admin_username
        self._jwt: Optional[str] = None
        self._http = httpx.AsyncClient(timeout=timeout, follow_redirects=True)

    async def aclose(self) -> None:
        await self._http.aclose()

    # ------------------------------------------------------------------
    # Auth
    # ------------------------------------------------------------------
    async def _login(self) -> str:
        """POST /api/auth/login (OAuth2 password form), cache the JWT."""
        if not self.admin_password:
            raise RuntimeError(
                "HITL_ADMIN_PASSWORD not set — fabric client cannot authenticate"
            )
        url = f"{self.base_url}/api/auth/login"
        data = {"username": self.admin_username, "password": self.admin_password}
        resp = await self._http.post(
            url,
            data=data,
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )
        if resp.status_code != 200:
            raise RuntimeError(
                f"fabric login failed: {resp.status_code} {resp.text[:200]}"
            )
        token = resp.json().get("access_token")
        if not token:
            raise RuntimeError(f"fabric login returned no access_token: {resp.text[:200]}")
        self._jwt = token
        return token

    async def _auth_headers(self) -> dict[str, str]:
        if not self._jwt:
            await self._login()
        return {"Authorization": f"Bearer {self._jwt}"}

    async def _post_json(self, path: str, json: dict[str, Any]) -> dict[str, Any]:
        url = f"{self.base_url}{path}"
        for attempt in range(2):
            headers = await self._auth_headers()
            resp = await self._http.post(url, json=json, headers=headers)
            if resp.status_code == 401 and attempt == 0:
                # Expired token — re-login once.
                self._jwt = None
                continue
            if resp.status_code != 200:
                raise RuntimeError(
                    f"fabric {path} returned {resp.status_code}: {resp.text[:300]}"
                )
            return resp.json()
        raise RuntimeError(f"fabric {path}: auth retry exhausted")

    # ------------------------------------------------------------------
    # Supply-chain subgraph
    # ------------------------------------------------------------------
    async def fetch_subgraph(
        self, supplier_id: str, *, depth: int = 4
    ) -> dict[str, Any]:
        """One call answers the three investigation questions.

        Returns the raw {nodes, edges, stats} payload from the fabric.
        Use the `extract_*` helpers below to slice it.
        """
        return await self._post_json(
            "/api/graph/subgraph",
            {"supplier_id": supplier_id, "depth": depth, "data_source": "neo4j_default"},
        )

    # ------------------------------------------------------------------
    # Deep-link helpers (for Naresh's handoff)
    # ------------------------------------------------------------------
    def graph_url_for_supplier(self, supplier_id: str) -> str:
        """Public URL into the fabric's knowledge-graph view for this supplier.

        The fabric's existing UX doesn't have a deep-link route, so today
        we link at the app root + a query param the frontend reads to
        auto-open the knowledge graph modal on this anchor. Wired in a
        follow-up to AgentRun.tsx; for now operators paste the URL and
        navigate manually.
        """
        return f"{self.base_url}/?graph={quote(supplier_id)}"

    def aeronova_case_url(self) -> str:
        """Suggestion-pill URL — opens the Aeronova case launch flow."""
        return f"{self.base_url}/?{urlencode({'prompt': 'Northwind Forge just filed Chapter 11 — assess Aeronova supply assurance'})}"


# ----------------------------------------------------------------------
# Subgraph parsers
# ----------------------------------------------------------------------
def extract_tier1_buyers(
    subgraph: dict[str, Any], failing_supplier_id: str
) -> list[dict[str, Any]]:
    """Tier-1 buyers = suppliers with a SOURCES_FROM edge into the anchor.

    The subgraph cypher unwinds one row per edge; for each SOURCES_FROM
    relationship pointing AT the failing supplier, the source endpoint
    is a tier-1 buyer.
    """
    nodes_by_id = {n["id"]: n for n in (subgraph.get("nodes") or [])}
    out: list[dict[str, Any]] = []
    seen: set[str] = set()
    for edge in subgraph.get("edges") or []:
        if edge.get("type") != "SOURCES_FROM":
            continue
        if edge.get("target") != failing_supplier_id:
            continue
        src = edge.get("source")
        if not src or src in seen:
            continue
        seen.add(src)
        n = nodes_by_id.get(src) or {}
        out.append(
            {
                "supplier_id": src,
                "name": n.get("label", src),
                "type": n.get("type", "Supplier"),
            }
        )
    return out


def extract_programs_at_risk(subgraph: dict[str, Any]) -> list[dict[str, Any]]:
    """Programs at risk = every Program node in the subgraph.

    The subgraph cypher walks the impact chain (failing supplier ← tier-1
    buyer → PO → Product → Program) and surfaces the Program terminals.
    Their `label` field carries the human name; the per-program $ stake
    is read from the side-data in the orchestrator (hard-coded to match
    the Aeronova seed; the fabric subgraph doesn't return $ figures).
    """
    out: list[dict[str, Any]] = []
    for node in subgraph.get("nodes") or []:
        if node.get("type") != "Program":
            continue
        out.append(
            {
                "program_id": node.get("id"),
                "name": node.get("label", node.get("id", "")),
            }
        )
    return out


def extract_alternates(
    subgraph: dict[str, Any], failing_supplier_id: str
) -> list[dict[str, Any]]:
    """Alternates = JV partners of the failing supplier + suppliers that
    share its HoldingCompany.

    Walks the edges twice:
      1. JOINT_VENTURE_WITH partners — direct alternate candidates.
      2. CONTROLLED_BY siblings via the same HoldingCompany — the
         "trap" alternates (Stillwater-style).
    The orchestrator decides which to recommend based on per-supplier
    metadata (qualification status etc.) that comes from elsewhere.
    """
    nodes_by_id = {n["id"]: n for n in (subgraph.get("nodes") or [])}
    out: list[dict[str, Any]] = []
    seen: set[str] = set()

    # 1) JV partners
    for edge in subgraph.get("edges") or []:
        if edge.get("type") != "JOINT_VENTURE_WITH":
            continue
        other = (
            edge.get("target")
            if edge.get("source") == failing_supplier_id
            else edge.get("source")
            if edge.get("target") == failing_supplier_id
            else None
        )
        if not other or other in seen:
            continue
        seen.add(other)
        n = nodes_by_id.get(other) or {}
        out.append(
            {
                "supplier_id": other,
                "name": n.get("label", other),
                "via": "joint-venture partner",
            }
        )

    # 2) Shared-HoldingCompany siblings — anchor → CONTROLLED_BY → holding
    #    ← CONTROLLED_BY ← sibling supplier.
    anchor_holdings: list[str] = []
    for edge in subgraph.get("edges") or []:
        if edge.get("type") != "CONTROLLED_BY":
            continue
        if edge.get("source") == failing_supplier_id:
            anchor_holdings.append(edge.get("target") or "")
    for edge in subgraph.get("edges") or []:
        if edge.get("type") != "CONTROLLED_BY":
            continue
        if edge.get("target") not in anchor_holdings:
            continue
        sib = edge.get("source")
        if not sib or sib == failing_supplier_id or sib in seen:
            continue
        seen.add(sib)
        n = nodes_by_id.get(sib) or {}
        out.append(
            {
                "supplier_id": sib,
                "name": n.get("label", sib),
                "via": f"sibling via parent {nodes_by_id.get(edge.get('target') or '', {}).get('label', '?')}",
            }
        )
    return out

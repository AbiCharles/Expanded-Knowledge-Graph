"""HTTP REST KnowledgeResolver.

Each source declares a base URL and one or more named paths keyed by
ontology_type. Path templates use `{...}` fields filled from the query's
`filters` dict.

Example source spec:

    id: public_jsonplaceholder
    kind: http
    base_url: https://jsonplaceholder.typicode.com
    paths:
      DemoPost: /posts/{id}
    headers:                        # optional
      Authorization: "Bearer ..."
"""
from __future__ import annotations

import logging
from typing import Any, Optional

import httpx
from tcs_hitl_context import KnowledgeFact, KnowledgeQuery, KnowledgeRef

log = logging.getLogger(__name__)


class HttpResolver:
    def __init__(
        self,
        *,
        source_id: str,
        base_url: str,
        paths: dict[str, str],
        headers: Optional[dict[str, str]] = None,
        timeout: float = 8.0,
    ):
        self.name = source_id
        self._base_url = base_url.rstrip("/")
        self._paths = paths
        self._headers = headers or {}
        self._timeout = timeout

    def resolve(self, query: KnowledgeQuery) -> list[KnowledgeFact]:
        path_template = self._paths.get(query.ontology_type)
        if path_template is None:
            raise ValueError(
                f"HttpResolver {self.name!r} has no path for ontology_type "
                f"{query.ontology_type!r}; available: {list(self._paths)}"
            )
        try:
            path = path_template.format(**query.filters)
        except KeyError as e:
            raise ValueError(
                f"HttpResolver {self.name!r}: missing filter {e.args[0]!r} for path {path_template!r}"
            )
        url = self._base_url + path
        try:
            resp = httpx.get(url, headers=self._headers, timeout=self._timeout)
            resp.raise_for_status()
        except httpx.HTTPError as exc:
            log.warning("HttpResolver %s failed for %s: %s", self.name, url, exc)
            return []
        return self._payload_to_facts(resp.json(), query.ontology_type)

    def _payload_to_facts(self, payload: Any, ontology_type: str) -> list[KnowledgeFact]:
        rows = payload if isinstance(payload, list) else [payload]
        facts: list[KnowledgeFact] = []
        for row in rows:
            if not isinstance(row, dict):
                continue
            entity_id = str(row.get("id", row.get("ID", "?")))
            title = str(
                row.get("title")
                or row.get("name")
                or row.get("subject")
                or "(no title)"
            )
            summary_parts = []
            for k in ("body", "description", "summary", "userId"):
                if row.get(k):
                    summary_parts.append(f"{k}={row[k]}")
            summary = " · ".join(str(s)[:120] for s in summary_parts) or str(row)[:200]
            facts.append(
                KnowledgeFact(
                    ref=KnowledgeRef(
                        source=f"http:{self.name}",
                        ontology_type=ontology_type,
                        id=entity_id,
                    ),
                    payload={"title": title, "summary": summary},
                    fetched_by=self.name,
                )
            )
        return facts

    def sample(self, n: int = 3) -> list[KnowledgeFact]:
        if not self._paths:
            return []
        ontology_type, path_template = next(iter(self._paths.items()))
        # Try id=1 as a sentinel
        path = path_template.replace("{id}", "1")
        url = self._base_url + path
        try:
            resp = httpx.get(url, headers=self._headers, timeout=self._timeout)
            resp.raise_for_status()
        except httpx.HTTPError as exc:
            log.warning("HttpResolver %s sample failed: %s", self.name, exc)
            return []
        return self._payload_to_facts(resp.json(), ontology_type)[:n]

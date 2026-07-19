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
from urllib.parse import quote

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
        # Binding-driven (Phase 3.C) takes precedence: the OntologyResolver
        # injects __binding__ with `http_path_template` ("/items/{id}").
        binding = query.filters.get("__binding__") or {}
        path_template = binding.get("http_path_template") or self._paths.get(
            query.ontology_type
        )
        if path_template is None:
            raise ValueError(
                f"HttpResolver {self.name!r} has no path for ontology_type "
                f"{query.ontology_type!r}; available: {list(self._paths)} "
                "and no binding.http_path_template provided"
            )
        # Strip framework-private keys before substituting into the template.
        substitution = {
            k: v
            for k, v in query.filters.items()
            if k not in ("__binding__", "__ontology__", "max_results")
        }
        # URL-encode each value so a query-string binding (e.g. a RAG
        # `?q={query}` template whose value carries spaces / punctuation)
        # produces a valid request. Numeric ids encode to themselves, so
        # existing path-segment bindings are unaffected.
        try:
            path = path_template.format(
                **{k: quote(str(v), safe="") for k, v in substitution.items()}
            )
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
        return self._payload_to_facts(
            resp.json(), query.ontology_type, binding.get("attribute_map")
        )

    def _payload_to_facts(
        self,
        payload: Any,
        ontology_type: str,
        attribute_map: Optional[dict[str, str]] = None,
    ) -> list[KnowledgeFact]:
        rows = payload if isinstance(payload, list) else [payload]
        # `attribute_map` is ontology-attribute -> source-column. Invert it so
        # response columns are renamed back to ontology attribute names, letting
        # a bound query surface typed attributes (defect_type, severity, …) on
        # the fact payload alongside the title/summary the console renders.
        inv = {src: onto for onto, src in (attribute_map or {}).items()}
        facts: list[KnowledgeFact] = []
        for row in rows:
            if not isinstance(row, dict):
                continue
            mapped = {inv.get(k, k): v for k, v in row.items()} if inv else dict(row)
            entity_id = str(mapped.get("id") or row.get("id") or row.get("ID") or "?")
            title = str(
                mapped.get("title")
                or mapped.get("name")
                or row.get("title")
                or row.get("name")
                or row.get("subject")
                or "(no title)"
            )
            summary_parts = []
            for k in ("body", "description", "summary", "userId"):
                val = mapped.get(k) if mapped.get(k) is not None else row.get(k)
                if val:
                    summary_parts.append(f"{k}={val}")
            summary = " · ".join(str(s)[:120] for s in summary_parts) or str(row)[:200]
            fact_payload: dict[str, Any] = {"title": title, "summary": summary}
            # Additive: expose the mapped ontology attributes without
            # clobbering the rendered title/summary.
            for k, v in mapped.items():
                if k not in ("title", "summary"):
                    fact_payload.setdefault(k, v)
            facts.append(
                KnowledgeFact(
                    ref=KnowledgeRef(
                        source=f"http:{self.name}",
                        ontology_type=ontology_type,
                        id=entity_id,
                    ),
                    payload=fact_payload,
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

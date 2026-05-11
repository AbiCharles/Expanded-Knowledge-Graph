"""CSV-backed KnowledgeResolver.

The resolver reads a CSV file once on first query, caches rows in memory, and
filters them on each `resolve()` call. Each matching row becomes one
KnowledgeFact whose payload is built from a Python `str.format`-style template.

Example source spec:

    id: products_csv
    kind: csv
    path: backend/data/products.csv
    ontology_type: Product       # default ontology_type for all rows
    id_field: product_id         # column to use as KnowledgeRef.id
    title_field: name            # column to use as fact title
    summary_template: "ECCN {eccn} · HTS {hts}"
"""
from __future__ import annotations

import csv
from pathlib import Path
from typing import Any, Optional

from tcs_hitl_context import KnowledgeFact, KnowledgeQuery, KnowledgeRef


class CsvResolver:
    """KnowledgeResolver backed by a CSV file."""

    def __init__(
        self,
        *,
        source_id: str,
        path: Path,
        ontology_type: str,
        id_field: str,
        title_field: str,
        summary_template: str,
    ):
        self.name = source_id
        self._path = path
        self._ontology_type = ontology_type
        self._id_field = id_field
        self._title_field = title_field
        self._summary_template = summary_template
        self._rows: Optional[list[dict[str, str]]] = None

    def _load(self) -> list[dict[str, str]]:
        if self._rows is None:
            with self._path.open() as fh:
                self._rows = list(csv.DictReader(fh))
        return self._rows

    def resolve(self, query: KnowledgeQuery) -> list[KnowledgeFact]:
        rows = self._load()
        # Pull off framework-private filter keys so they don't get matched
        # against CSV columns. `__binding__` lets the OntologyResolver
        # override which column holds the identifier for this query.
        binding = query.filters.get("__binding__") or {}
        filters = {
            k: v
            for k, v in query.filters.items()
            if k not in ("max_results", "__binding__", "__ontology__")
        }
        matched = [
            r for r in rows
            if all(str(r.get(k, "")).lower() == str(v).lower() for k, v in filters.items())
        ]
        max_results = int(query.filters.get("max_results", query.max_results))
        # Binding-driven id column wins; falls back to the source-spec id_field.
        id_field = binding.get("identifier_column") or self._id_field
        out: list[KnowledgeFact] = []
        for r in matched[:max_results]:
            ref = KnowledgeRef(
                source=f"csv:{self.name}",
                ontology_type=query.ontology_type or self._ontology_type,
                id=r.get(id_field, "?"),
            )
            try:
                summary = self._summary_template.format(**r)
            except KeyError:
                summary = ", ".join(f"{k}={v}" for k, v in r.items())
            out.append(
                KnowledgeFact(
                    ref=ref,
                    payload={"title": r.get(self._title_field, ""), "summary": summary},
                    fetched_by=self.name,
                )
            )
        return out

    def sample(self, n: int = 3) -> list[KnowledgeFact]:
        """Used by the `/test` endpoint."""
        rows = self._load()
        out: list[KnowledgeFact] = []
        for r in rows[:n]:
            ref = KnowledgeRef(
                source=f"csv:{self.name}",
                ontology_type=self._ontology_type,
                id=r.get(self._id_field, "?"),
            )
            try:
                summary = self._summary_template.format(**r)
            except KeyError:
                summary = ", ".join(f"{k}={v}" for k, v in r.items())
            out.append(
                KnowledgeFact(
                    ref=ref,
                    payload={"title": r.get(self._title_field, ""), "summary": summary},
                    fetched_by=self.name,
                )
            )
        return out

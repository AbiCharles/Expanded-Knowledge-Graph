"""OntologyResolver: dispatch to underlying KnowledgeResolvers via mapping."""
from __future__ import annotations

import csv
from pathlib import Path
from typing import Any

import pytest
import yaml
from fastapi.testclient import TestClient
from tcs_hitl_context import KnowledgeFact, KnowledgeQuery, KnowledgeRef

from backend.datasources import DataSourceRegistry, DataSourceSpec
from backend.ontology import (
    Mapping,
    OntologyRegistry,
    OntologyResolveError,
    OntologyResolver,
    parse_mapping,
    parse_ontology,
    substitute_payload_refs,
)


# =============================================================================
# Direct OntologyResolver tests with stub source registry
# =============================================================================
class _StubResolver:
    """KnowledgeResolver Protocol stub returning canned facts."""

    def __init__(self, name: str, facts: list[KnowledgeFact]):
        self.name = name
        self._facts = facts
        self.calls: list[KnowledgeQuery] = []

    def resolve(self, query: KnowledgeQuery) -> list[KnowledgeFact]:
        self.calls.append(query)
        return list(self._facts)


class _StubSources:
    def __init__(self, resolvers: dict[str, _StubResolver]):
        self._resolvers = resolvers

    def require(self, source_id: str):
        if source_id not in self._resolvers:
            raise KeyError(source_id)
        return self._resolvers[source_id]


def _make_ontology() -> Any:
    return parse_ontology(
        {
            "id": "supply_chain_v1",
            "title": "Supply Chain",
            "classes": {
                "Supplier": {
                    "attributes": [
                        {"name": "supplier_id", "type": "string", "identifier": True},
                        {"name": "name", "type": "string"},
                    ],
                },
            },
        }
    )


def _make_mapping(sources: list[dict[str, Any]]) -> Mapping:
    return parse_mapping(
        {
            "ontology_id": "supply_chain_v1",
            "mappings": {
                "Supplier": {
                    "sources": sources,
                },
            },
        }
    )


def _fact(source: str, ident: str, title: str) -> KnowledgeFact:
    return KnowledgeFact(
        ref=KnowledgeRef(source=source, ontology_type="Supplier", id=ident),
        payload={"title": title, "summary": ""},
        fetched_by=source,
    )


def test_resolves_via_single_source(tmp_path: Path) -> None:
    reg = OntologyRegistry.from_directory(tmp_path)
    reg.register(_make_ontology())
    reg.save_mapping(
        _make_mapping(
            [
                {
                    "data_source": "suppliers_csv",
                    "identifier_column": "supplier_id",
                    "attribute_map": {"supplier_id": "supplier_id"},
                }
            ]
        )
    )
    stub = _StubResolver("suppliers_csv", [_fact("csv:suppliers_csv", "S-001", "Acme")])
    resolver = OntologyResolver(reg, _StubSources({"suppliers_csv": stub}))

    from backend.ontology import OntologyQuery

    facts = resolver.resolve_query(
        OntologyQuery(ontology="supply_chain_v1", **{"class": "Supplier"})
    )
    assert len(facts) == 1
    assert facts[0].payload["via_ontology"] == "supply_chain_v1.Supplier"
    assert facts[0].payload["via_source_binding"] == "suppliers_csv"
    assert stub.calls[0].ontology_type == "Supplier"


def test_translates_filters_via_attribute_map(tmp_path: Path) -> None:
    reg = OntologyRegistry.from_directory(tmp_path)
    reg.register(_make_ontology())
    reg.save_mapping(
        _make_mapping(
            [
                {
                    "data_source": "vendors_pg",
                    "identifier_column": "vendor_id",
                    "attribute_map": {"supplier_id": "vendor_id", "name": "legal_name"},
                }
            ]
        )
    )
    stub = _StubResolver("vendors_pg", [])
    resolver = OntologyResolver(reg, _StubSources({"vendors_pg": stub}))

    from backend.ontology import OntologyQuery

    resolver.resolve_query(
        OntologyQuery(
            ontology="supply_chain_v1",
            **{"class": "Supplier"},
            where={"supplier_id": "S-001"},
        )
    )
    # The OntologyResolver renames filter keys via attribute_map AND attaches
    # the active binding under `__binding__` so connectors can read kind-
    # specific config (table / query_template / http_path_template). The
    # core assertion is the renamed filter key; we just assert it appears.
    actual = stub.calls[0].filters
    assert actual["vendor_id"] == "S-001"
    assert actual["__binding__"]["data_source"] == "vendors_pg"


def test_concatenates_facts_from_multiple_sources_no_dedupe(tmp_path: Path) -> None:
    reg = OntologyRegistry.from_directory(tmp_path)
    reg.register(_make_ontology())
    reg.save_mapping(
        _make_mapping(
            [
                {
                    "data_source": "csv_master",
                    "identifier_column": "supplier_id",
                    "attribute_map": {},
                },
                {
                    "data_source": "pg_governance",
                    "identifier_column": "supplier_id",
                    "attribute_map": {},
                },
            ]
        )
    )
    csv_stub = _StubResolver("csv_master", [_fact("csv:csv_master", "S-001", "from CSV")])
    pg_stub = _StubResolver("pg_governance", [_fact("postgres:pg_governance", "S-001", "from PG")])
    resolver = OntologyResolver(reg, _StubSources({"csv_master": csv_stub, "pg_governance": pg_stub}))

    from backend.ontology import OntologyQuery

    facts = resolver.resolve_query(
        OntologyQuery(ontology="supply_chain_v1", **{"class": "Supplier"})
    )
    # Both rows are kept — Phase 1 has no cross-source dedupe.
    assert len(facts) == 2
    sources = {f.ref.source for f in facts}
    assert sources == {"csv:csv_master", "postgres:pg_governance"}


def test_unknown_class_raises(tmp_path: Path) -> None:
    reg = OntologyRegistry.from_directory(tmp_path)
    reg.register(_make_ontology())
    reg.save_mapping(_make_mapping([]))
    resolver = OntologyResolver(reg, _StubSources({}))

    from backend.ontology import OntologyQuery

    with pytest.raises(OntologyResolveError):
        resolver.resolve_query(
            OntologyQuery(ontology="supply_chain_v1", **{"class": "Nonexistent"})
        )


def test_no_mapping_raises(tmp_path: Path) -> None:
    reg = OntologyRegistry.from_directory(tmp_path)
    reg.register(_make_ontology())
    # No mapping registered.
    resolver = OntologyResolver(reg, _StubSources({}))

    from backend.ontology import OntologyQuery

    with pytest.raises(OntologyResolveError):
        resolver.resolve_query(
            OntologyQuery(ontology="supply_chain_v1", **{"class": "Supplier"})
        )


def test_unregistered_source_is_skipped_not_raised(tmp_path: Path) -> None:
    reg = OntologyRegistry.from_directory(tmp_path)
    reg.register(_make_ontology())
    reg.save_mapping(
        _make_mapping(
            [
                {
                    "data_source": "missing_source",
                    "identifier_column": "supplier_id",
                    "attribute_map": {},
                },
                {
                    "data_source": "good_source",
                    "identifier_column": "supplier_id",
                    "attribute_map": {},
                },
            ]
        )
    )
    good = _StubResolver("good_source", [_fact("csv:good_source", "S-001", "ok")])
    resolver = OntologyResolver(reg, _StubSources({"good_source": good}))

    from backend.ontology import OntologyQuery

    facts = resolver.resolve_query(
        OntologyQuery(ontology="supply_chain_v1", **{"class": "Supplier"})
    )
    assert len(facts) == 1


# =============================================================================
# Payload reference substitution
# =============================================================================
def test_substitute_payload_refs_basic() -> None:
    out = substitute_payload_refs(
        {"supplier_id": ":sid", "country": "NL"}, {"sid": "S-001"}
    )
    assert out == {"supplier_id": "S-001", "country": "NL"}


def test_substitute_payload_refs_missing_key_raises() -> None:
    with pytest.raises(OntologyResolveError):
        substitute_payload_refs({"x": ":absent"}, {})


def test_substitute_payload_refs_passes_non_strings_through() -> None:
    assert substitute_payload_refs({"k": 42, "j": True}, {}) == {"k": 42, "j": True}


# =============================================================================
# End-to-end via the real CSV resolver and the public REST API
# =============================================================================
@pytest.fixture()
def csv_with_ontology(client: TestClient, admin_headers: dict) -> dict:
    """Wire the seeded products_csv source up as a Product class in an
    uploaded ontology, with a mapping. Returns ids for downstream tests.

    We use products_csv (already seeded by the test fixture into the tmp
    data dir) rather than uploading a fresh CSV — the upload endpoint
    writes to the *real* repo's `backend/data/uploads/` because it
    derives project_root from `__file__`, which the test isolation
    can't intercept. That's a wider issue for another day.
    """
    # 1. Upload the ontology via the raw endpoint.
    onto_doc = {
        "id": "products_v1",
        "title": "Products",
        "classes": {
            "Product": {
                "attributes": [
                    {"name": "product_id", "type": "string", "identifier": True},
                    {"name": "name", "type": "string"},
                    {"name": "category", "type": "string"},
                ],
            },
        },
    }
    resp = client.post(
        "/api/ontologies/raw", json={"document": onto_doc}, headers=admin_headers
    )
    assert resp.status_code == 200, resp.text

    # 2. PUT a mapping that points Product at the seeded products_csv source.
    mapping_doc = {
        "ontology_id": "products_v1",
        "mappings": {
            "Product": {
                "sources": [
                    {
                        "data_source": "products_csv",
                        "identifier_column": "product_id",
                        "attribute_map": {
                            "product_id": "product_id",
                            "name": "name",
                            "category": "category",
                        },
                    }
                ]
            }
        },
    }
    resp = client.put(
        "/api/ontologies/products_v1/mappings",
        json={"document": mapping_doc},
        headers=admin_headers,
    )
    assert resp.status_code == 200, resp.text
    return {"source_id": "products_csv", "ontology_id": "products_v1"}


def test_e2e_structured_query_returns_csv_rows(
    client: TestClient, admin_headers: dict, csv_with_ontology: dict
) -> None:
    # Filter for the seeded P-EL-9001 product. CSV resolver does column-equals
    # match (case-insensitive) so a single specific id reliably returns one row.
    resp = client.post(
        "/api/ontology-query/structured",
        json={
            "ontology": "products_v1",
            "class": "Product",
            "where": {"product_id": "P-EL-9001"},
        },
        headers=admin_headers,
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["fact_count"] == 1, body
    fact = body["facts"][0]
    assert fact["id"] == "P-EL-9001"
    assert fact["via_ontology"] == "products_v1.Product"
    assert fact["via_source_binding"] == "products_csv"


def test_list_ontologies_endpoint(
    client: TestClient, admin_headers: dict, csv_with_ontology: dict
) -> None:
    resp = client.get("/api/ontologies", headers=admin_headers)
    assert resp.status_code == 200
    rows = resp.json()
    assert any(
        r["id"] == "products_v1" and r["has_mapping"] and r["class_count"] == 1
        for r in rows
    )


def test_get_ontology_yaml_format(
    client: TestClient, admin_headers: dict, csv_with_ontology: dict
) -> None:
    resp = client.get(
        "/api/ontologies/products_v1?format=yaml", headers=admin_headers
    )
    assert resp.status_code == 200
    assert "id: products_v1" in resp.text


def test_put_mapping_rejects_unknown_class(
    client: TestClient, admin_headers: dict, csv_with_ontology: dict
) -> None:
    resp = client.put(
        "/api/ontologies/products_v1/mappings",
        json={
            "document": {
                "ontology_id": "products_v1",
                "mappings": {
                    "GhostClass": {"sources": []},
                },
            }
        },
        headers=admin_headers,
    )
    assert resp.status_code == 400
    assert "GhostClass" in resp.json()["detail"]


def test_upload_yaml_via_multipart(
    client: TestClient, admin_headers: dict
) -> None:
    yaml_body = yaml.safe_dump(
        {
            "id": "test_yaml_upload",
            "title": "Yaml Upload Test",
            "classes": {
                "Foo": {"attributes": [{"name": "id", "identifier": True}]},
            },
        }
    )
    resp = client.post(
        "/api/ontologies",
        files={"file": ("ontology.yaml", yaml_body.encode(), "application/yaml")},
        headers=admin_headers,
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["id"] == "test_yaml_upload"

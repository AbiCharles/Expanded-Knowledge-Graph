"""LLM mapper + schema introspection + suggest endpoint."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from backend.ontology import (
    Ontology,
    SourceSchema,
    inspect_source,
    parse_ontology,
    suggest_mappings,
)
from backend.ontology.mapper import _fallback_propose
from backend.ontology.schema_introspect import ColumnInfo, TableInfo


# =============================================================================
# Fallback (name-match) proposer
# =============================================================================
def test_fallback_matches_obvious_columns() -> None:
    onto = parse_ontology(
        {
            "id": "x",
            "title": "X",
            "classes": {
                "Supplier": {
                    "attributes": [
                        {"name": "supplier_id", "identifier": True},
                        {"name": "name"},
                        {"name": "country"},
                    ]
                }
            },
        }
    )
    table = TableInfo(
        name="suppliers",
        columns=[
            ColumnInfo(name="supplier_id", type="string"),
            ColumnInfo(name="name", type="string"),
            ColumnInfo(name="country", type="string"),
        ],
    )
    out = _fallback_propose(onto.class_("Supplier"), table)
    assert out["applicable"] is True
    assert out["identifier_column"] == "supplier_id"
    assert out["attribute_map"] == {
        "supplier_id": "supplier_id",
        "name": "name",
        "country": "country",
    }
    assert out["confidence"] == 1.0


def test_fallback_normalises_case_and_underscores() -> None:
    onto = parse_ontology(
        {
            "id": "x",
            "title": "X",
            "classes": {
                "Vendor": {
                    "attributes": [
                        {"name": "vendor_id", "identifier": True},
                        {"name": "legalName"},
                    ]
                }
            },
        }
    )
    table = TableInfo(
        name="vendors",
        columns=[
            ColumnInfo(name="VendorID", type="string"),
            ColumnInfo(name="legal_name", type="string"),
        ],
    )
    out = _fallback_propose(onto.class_("Vendor"), table)
    assert out["applicable"] is True
    assert out["identifier_column"] == "VendorID"
    assert out["attribute_map"] == {"vendor_id": "VendorID", "legalName": "legal_name"}


def test_fallback_rejects_when_no_identifier_column() -> None:
    onto = parse_ontology(
        {
            "id": "x",
            "title": "X",
            "classes": {
                "Thing": {
                    "attributes": [
                        {"name": "id", "identifier": True},
                        {"name": "label"},
                    ]
                }
            },
        }
    )
    table = TableInfo(
        name="t",
        columns=[ColumnInfo(name="some_other_col", type="string")],
    )
    out = _fallback_propose(onto.class_("Thing"), table)
    assert out["applicable"] is False


# =============================================================================
# suggest_mappings() with FakeLLMClient (drives the fallback path)
# =============================================================================
class _FakeLLM:
    name = "fake"

    async def complete(self, **_kwargs):
        raise AssertionError("FakeLLM.complete should not be called when name == 'fake'")


@pytest.mark.asyncio
async def test_suggest_mappings_uses_fallback_when_llm_fake() -> None:
    onto = parse_ontology(
        {
            "id": "supply_chain_v1",
            "title": "x",
            "classes": {
                "Supplier": {
                    "attributes": [
                        {"name": "supplier_id", "identifier": True},
                        {"name": "name"},
                    ]
                }
            },
        }
    )
    schema = SourceSchema(
        source_id="suppliers_csv",
        kind="csv",
        tables=[
            TableInfo(
                name="suppliers",
                columns=[
                    ColumnInfo(name="supplier_id", type="string"),
                    ColumnInfo(name="name", type="string"),
                ],
            )
        ],
    )
    mapping = await suggest_mappings(ontology=onto, schemas=[schema], llm=_FakeLLM())
    assert mapping.ontology_id == "supply_chain_v1"
    bindings = mapping.for_class("Supplier").sources
    assert len(bindings) == 1
    assert bindings[0].data_source == "suppliers_csv"
    assert bindings[0].suggested_by == "fallback"
    assert bindings[0].confidence == 1.0


# =============================================================================
# suggest_mappings() with a stub real LLM
# =============================================================================
class _StubLLM:
    name = "openai"

    def __init__(self, response: dict):
        self._response = response

    async def complete(self, **kwargs):
        # Respond with the canned dict, JSON-encoded.
        return json.dumps(self._response)


@pytest.mark.asyncio
async def test_suggest_mappings_uses_llm_response() -> None:
    onto = parse_ontology(
        {
            "id": "x",
            "title": "x",
            "classes": {
                "Vendor": {
                    "attributes": [
                        {"name": "vendor_id", "identifier": True},
                        {"name": "legal_name"},
                    ]
                }
            },
        }
    )
    schema = SourceSchema(
        source_id="vendors",
        kind="postgres",
        tables=[
            TableInfo(
                name="suppliers",
                columns=[
                    ColumnInfo(name="sup_id", type="text"),
                    ColumnInfo(name="company_name", type="text"),
                ],
            )
        ],
    )
    llm = _StubLLM(
        {
            "applicable": True,
            "identifier_column": "sup_id",
            "attribute_map": {"vendor_id": "sup_id", "legal_name": "company_name"},
            "confidence": 0.78,
            "rationale": "Names match semantically though not syntactically.",
        }
    )
    mapping = await suggest_mappings(ontology=onto, schemas=[schema], llm=llm)
    binding = mapping.for_class("Vendor").sources[0]
    assert binding.data_source == "vendors"
    assert binding.identifier_column == "sup_id"
    assert binding.attribute_map == {"vendor_id": "sup_id", "legal_name": "company_name"}
    assert binding.confidence == 0.78
    assert binding.suggested_by == "llm"


@pytest.mark.asyncio
async def test_suggest_mappings_drops_inapplicable_proposals() -> None:
    onto = parse_ontology(
        {
            "id": "x",
            "title": "x",
            "classes": {"Foo": {"attributes": [{"name": "id", "identifier": True}]}},
        }
    )
    schema = SourceSchema(
        source_id="src",
        kind="csv",
        tables=[TableInfo(name="t", columns=[ColumnInfo(name="totally_unrelated")])],
    )
    llm = _StubLLM({"applicable": False, "confidence": 0.1})
    mapping = await suggest_mappings(ontology=onto, schemas=[schema], llm=llm)
    assert mapping.for_class("Foo").sources == []


# =============================================================================
# Schema introspection (CSV + SQLite via the seeded fixtures)
# =============================================================================
def test_inspect_csv_via_data_source_registry(client: TestClient, admin_headers: dict) -> None:
    """Use the public schema endpoint — exercises inspect_source through the
    real DataSourceRegistry that the test fixture wires up."""
    resp = client.get("/api/data-sources/products_csv/schema", headers=admin_headers)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["kind"] == "csv"
    assert len(body["tables"]) == 1
    cols = {c["name"] for c in body["tables"][0]["columns"]}
    assert {"product_id", "name", "eccn", "hts"} <= cols


def test_inspect_sqlite_via_data_source_registry(
    client: TestClient, admin_headers: dict
) -> None:
    resp = client.get(
        "/api/data-sources/governance_sqlite/schema", headers=admin_headers
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["kind"] == "sqlite"
    table_names = {t["name"] for t in body["tables"]}
    assert "prior_cases" in table_names


def test_inspect_unknown_source_404(client: TestClient, admin_headers: dict) -> None:
    resp = client.get("/api/data-sources/nope/schema", headers=admin_headers)
    assert resp.status_code == 404


# =============================================================================
# /mappings/suggest endpoint
# =============================================================================
def test_suggest_mappings_endpoint_e2e(
    client: TestClient, admin_headers: dict
) -> None:
    """Upload an ontology, ask for suggestions against products_csv,
    confirm we get a Mapping draft we can PUT back."""
    onto_doc = {
        "id": "products_v2",
        "title": "Products",
        "classes": {
            "Product": {
                "attributes": [
                    {"name": "product_id", "identifier": True},
                    {"name": "name"},
                    {"name": "category"},
                ]
            }
        },
    }
    client.post(
        "/api/ontologies/raw", json={"document": onto_doc}, headers=admin_headers
    )

    resp = client.post(
        "/api/ontologies/products_v2/mappings/suggest",
        json={"data_source_ids": ["products_csv"]},
        headers=admin_headers,
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["ontology_id"] == "products_v2"
    assert len(body["schemas"]) == 1
    assert body["schemas"][0]["source_id"] == "products_csv"
    assert body["mapping"]["ontology_id"] == "products_v2"
    bindings = body["mapping"]["mappings"]["Product"]["sources"]
    # Test runs with LLM_PROVIDER=fake, so we expect the deterministic
    # fallback to bind all three matchable attributes.
    assert len(bindings) == 1
    assert bindings[0]["data_source"] == "products_csv"
    assert bindings[0]["identifier_column"] == "product_id"
    assert bindings[0]["attribute_map"] == {
        "product_id": "product_id",
        "name": "name",
        "category": "category",
    }

    # The returned mapping is committable as-is via PUT.
    resp = client.put(
        "/api/ontologies/products_v2/mappings",
        json={"document": body["mapping"]},
        headers=admin_headers,
    )
    assert resp.status_code == 200, resp.text

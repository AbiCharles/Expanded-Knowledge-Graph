"""NL→OntologyQuery parser + /api/ontology-query endpoint."""
from __future__ import annotations

import json
from typing import Any

import pytest
from fastapi.testclient import TestClient

from backend.ontology import (
    NLParseError,
    parse_nl_query,
    parse_ontology,
)


SAMPLE_ONTOLOGY = parse_ontology(
    {
        "id": "supply_chain_demo",
        "title": "Supply chain demo",
        "classes": {
            "Supplier": {
                "attributes": [
                    {"name": "supplier_id", "identifier": True},
                    {"name": "name"},
                    {"name": "country"},
                    {"name": "reliability_score"},
                ]
            },
            "Product": {
                "attributes": [
                    {"name": "product_id", "identifier": True},
                    {"name": "name"},
                ]
            },
        },
    }
)


# =============================================================================
# Fallback parser (LLM_PROVIDER=fake)
# =============================================================================
class _FakeLLM:
    name = "fake"

    async def complete(self, **_kwargs):
        raise AssertionError("fallback should not call complete")


@pytest.mark.asyncio
async def test_fallback_matches_class_by_name() -> None:
    out = await parse_nl_query("show me the suppliers", SAMPLE_ONTOLOGY, _FakeLLM())
    assert out.class_ == "Supplier"
    assert out.where == {}
    assert out.ontology == "supply_chain_demo"


@pytest.mark.asyncio
async def test_fallback_prefers_longest_match() -> None:
    # If two class names are present, the longer one wins.
    onto = parse_ontology(
        {
            "id": "x",
            "title": "x",
            "classes": {
                "Order": {"attributes": [{"name": "id", "identifier": True}]},
                "PurchaseOrder": {"attributes": [{"name": "id", "identifier": True}]},
            },
        }
    )
    out = await parse_nl_query("show purchase orders", onto, _FakeLLM())
    assert out.class_ == "PurchaseOrder"


@pytest.mark.asyncio
async def test_fallback_raises_when_no_class_in_prompt() -> None:
    with pytest.raises(NLParseError) as exc:
        await parse_nl_query("how is the weather", SAMPLE_ONTOLOGY, _FakeLLM())
    assert "no ontology class" in str(exc.value).lower()


@pytest.mark.asyncio
async def test_fallback_rejects_empty_prompt() -> None:
    with pytest.raises(NLParseError):
        await parse_nl_query("", SAMPLE_ONTOLOGY, _FakeLLM())


# =============================================================================
# LLM path
# =============================================================================
class _StubLLM:
    name = "openai"

    def __init__(self, response: dict):
        self._response = response
        self.last_prompt: str | None = None

    async def complete(self, *, system: str, user: str, **_kw):
        self.last_prompt = user
        return json.dumps(self._response)


@pytest.mark.asyncio
async def test_llm_response_is_used() -> None:
    llm = _StubLLM(
        {
            "class": "Supplier",
            "where": {"country": "NL"},
            "max_results": 25,
            "purpose": "List Dutch suppliers",
        }
    )
    out = await parse_nl_query(
        "Dutch suppliers please", SAMPLE_ONTOLOGY, llm
    )
    assert out.class_ == "Supplier"
    assert out.where == {"country": "NL"}
    assert out.max_results == 25
    assert "Dutch" in (llm.last_prompt or "")


@pytest.mark.asyncio
async def test_attribute_samples_appear_in_llm_prompt() -> None:
    """When the caller passes per-attribute sample values (collected from
    the bound source's schema), they should be rendered into the LLM
    prompt so the model can normalise human-readable filter forms to
    the data shape — e.g. 'Dutch' → 'NL' when the samples include 'NL'."""
    llm = _StubLLM(
        {
            "class": "Supplier",
            "where": {"country": "NL"},
            "max_results": 50,
            "purpose": "ok",
        }
    )
    await parse_nl_query(
        "Dutch suppliers",
        SAMPLE_ONTOLOGY,
        llm,
        attribute_samples={
            "Supplier": {"country": ["NL", "DE", "FR"]},
        },
    )
    prompt = llm.last_prompt or ""
    # The attribute description in the catalog now annotates with samples
    assert "country:string" in prompt
    assert "data sample values" in prompt
    assert "'NL'" in prompt
    # And the prompt instructs the model to use the data shape
    assert "human form" in prompt or "data actually uses" in prompt


@pytest.mark.asyncio
async def test_llm_unknown_class_raises() -> None:
    llm = _StubLLM({"class": "Ghost", "where": {}})
    with pytest.raises(NLParseError) as exc:
        await parse_nl_query("anything", SAMPLE_ONTOLOGY, llm)
    assert "unknown class" in str(exc.value).lower()


@pytest.mark.asyncio
async def test_llm_null_class_raises() -> None:
    llm = _StubLLM(
        {"class": None, "where": {}, "purpose": "could not figure out"}
    )
    with pytest.raises(NLParseError) as exc:
        await parse_nl_query("anything", SAMPLE_ONTOLOGY, llm)
    assert "could not figure out" in str(exc.value)


@pytest.mark.asyncio
async def test_llm_failure_falls_back_gracefully() -> None:
    """If the LLM raises, we should fall back to the deterministic parser."""

    class _BrokenLLM:
        name = "openai"

        async def complete(self, **_kw):
            raise RuntimeError("upstream timeout")

    out = await parse_nl_query("show me suppliers", SAMPLE_ONTOLOGY, _BrokenLLM())
    assert out.class_ == "Supplier"


# =============================================================================
# /api/ontology-query endpoint (NL form)
# =============================================================================
@pytest.fixture()
def ontology_with_mapping(client: TestClient, admin_headers: dict) -> dict:
    """Upload Product ontology + mapping → products_csv (mirrors the
    Phase 1/2 e2e fixture). Returns ids."""
    onto_doc = {
        "id": "products_v3",
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
    mapping_doc = {
        "ontology_id": "products_v3",
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
    client.put(
        "/api/ontologies/products_v3/mappings",
        json={"document": mapping_doc},
        headers=admin_headers,
    )
    return {"ontology_id": "products_v3"}


def test_nl_query_endpoint_with_class_name_match(
    client: TestClient, admin_headers: dict, ontology_with_mapping: dict
) -> None:
    """The fallback parser (test conftest forces LLM_PROVIDER=fake) matches
    'product' in the prompt to the Product class. No filters extracted."""
    resp = client.post(
        "/api/ontology-query",
        json={"ontology": "products_v3", "prompt": "show me products"},
        headers=admin_headers,
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["class"] == "Product"
    assert body["where"] == {}
    # products.csv has 3 rows seeded
    assert body["fact_count"] >= 1
    assert body["llm"] == "fake"


def test_nl_query_endpoint_unknown_ontology_404(
    client: TestClient, admin_headers: dict
) -> None:
    resp = client.post(
        "/api/ontology-query",
        json={"ontology": "missing_v999", "prompt": "show suppliers"},
        headers=admin_headers,
    )
    assert resp.status_code == 404


def test_nl_query_endpoint_no_class_in_prompt_400(
    client: TestClient, admin_headers: dict, ontology_with_mapping: dict
) -> None:
    resp = client.post(
        "/api/ontology-query",
        json={"ontology": "products_v3", "prompt": "what is the weather"},
        headers=admin_headers,
    )
    assert resp.status_code == 400
    detail = resp.json()["detail"]
    assert "no ontology class" in detail.lower()

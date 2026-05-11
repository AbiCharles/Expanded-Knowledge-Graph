"""Ontology loader: format parsing, registry persistence, validation."""
from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml

from backend.ontology import (
    Mapping,
    Ontology,
    OntologyError,
    OntologyRegistry,
    parse_mapping,
    parse_ontology,
)


SAMPLE_ONTOLOGY = {
    "id": "supply_chain_v1",
    "title": "Supply Chain",
    "namespace": "sc",
    "classes": {
        "Supplier": {
            "description": "A vendor",
            "attributes": [
                {"name": "supplier_id", "type": "string", "identifier": True},
                {"name": "name", "type": "string", "required": True},
                {"name": "country", "type": "string"},
            ],
            "relations": [
                {"name": "places", "target": "PurchaseOrder", "cardinality": "0..*"},
            ],
        },
        "PurchaseOrder": {
            "attributes": [
                {"name": "po_id", "type": "string", "identifier": True},
            ],
        },
    },
}


def test_parse_yaml_string() -> None:
    text = yaml.safe_dump(SAMPLE_ONTOLOGY)
    onto = parse_ontology(text)
    assert onto.id == "supply_chain_v1"
    assert "Supplier" in onto.classes
    assert onto.class_("Supplier").identifier_attribute().name == "supplier_id"


def test_parse_json_string() -> None:
    text = json.dumps(SAMPLE_ONTOLOGY)
    onto = parse_ontology(text)
    assert onto.id == "supply_chain_v1"
    assert len(onto.classes) == 2


def test_parse_dict() -> None:
    onto = parse_ontology(SAMPLE_ONTOLOGY)
    assert onto.title == "Supply Chain"


def test_parse_bytes() -> None:
    onto = parse_ontology(json.dumps(SAMPLE_ONTOLOGY).encode())
    assert onto.id == "supply_chain_v1"


def test_parse_rejects_empty() -> None:
    with pytest.raises(OntologyError):
        parse_ontology("")


def test_parse_rejects_non_mapping() -> None:
    with pytest.raises(OntologyError):
        parse_ontology("[1,2,3]")


def test_parse_rejects_garbage() -> None:
    # Not valid JSON or YAML — strikes both parsers.
    with pytest.raises(OntologyError):
        parse_ontology("{[unbalanced: ]}")


def test_parse_rejects_missing_required_fields() -> None:
    with pytest.raises(OntologyError):
        parse_ontology({"title": "missing id"})  # no `id`


def test_parse_rejects_unknown_class_field() -> None:
    bad = {
        "id": "x",
        "title": "x",
        "classes": {"Foo": {"attributes": [], "extra_field": True}},
    }
    with pytest.raises(OntologyError):
        parse_ontology(bad)


def test_registry_roundtrip(tmp_path: Path) -> None:
    reg = OntologyRegistry.from_directory(tmp_path)
    assert reg.all() == []

    onto = parse_ontology(SAMPLE_ONTOLOGY)
    reg.register(onto)

    # Persisted to disk in YAML form
    on_disk = tmp_path / "supply_chain_v1.yaml"
    assert on_disk.exists()
    reloaded = yaml.safe_load(on_disk.read_text())
    assert reloaded["id"] == "supply_chain_v1"
    assert reloaded["classes"]["Supplier"]["attributes"][0]["identifier"] is True

    # Re-loading from disk picks it up
    reg2 = OntologyRegistry.from_directory(tmp_path)
    assert reg2.get("supply_chain_v1") is not None


def test_registry_unregister(tmp_path: Path) -> None:
    reg = OntologyRegistry.from_directory(tmp_path)
    reg.register(parse_ontology(SAMPLE_ONTOLOGY))
    reg.unregister("supply_chain_v1")
    assert reg.get("supply_chain_v1") is None
    assert not (tmp_path / "supply_chain_v1.yaml").exists()


def test_registry_refuses_to_unregister_default(tmp_path: Path) -> None:
    """Default ontologies are seeded with the app and protected against
    accidental deletion via the API. The registry-level guard backs the
    HTTP-level guard in backend/api/ontologies.py."""
    reg = OntologyRegistry.from_directory(tmp_path)
    reg.register(parse_ontology({**SAMPLE_ONTOLOGY, "default": True}))
    with pytest.raises(OntologyError) as exc:
        reg.unregister("supply_chain_v1")
    assert "default" in str(exc.value).lower()
    # Still loaded, file still on disk.
    assert reg.get("supply_chain_v1") is not None
    assert (tmp_path / "supply_chain_v1.yaml").exists()


def test_registry_skips_malformed_files(tmp_path: Path, caplog) -> None:
    (tmp_path / "broken.yaml").write_text("not: a: valid: ontology")
    (tmp_path / "good.yaml").write_text(yaml.safe_dump(SAMPLE_ONTOLOGY))
    reg = OntologyRegistry.from_directory(tmp_path)
    assert reg.ids() == ["supply_chain_v1"]


def test_mapping_save_requires_known_ontology(tmp_path: Path) -> None:
    reg = OntologyRegistry.from_directory(tmp_path)
    mapping = Mapping(ontology_id="not_registered", mappings={})
    with pytest.raises(OntologyError):
        reg.save_mapping(mapping)


def test_mapping_roundtrip(tmp_path: Path) -> None:
    reg = OntologyRegistry.from_directory(tmp_path)
    reg.register(parse_ontology(SAMPLE_ONTOLOGY))

    mapping_doc = {
        "ontology_id": "supply_chain_v1",
        "mappings": {
            "Supplier": {
                "sources": [
                    {
                        "data_source": "suppliers_csv",
                        "identifier_column": "supplier_id",
                        "attribute_map": {
                            "supplier_id": "supplier_id",
                            "name": "name",
                        },
                        "confidence": 0.9,
                        "suggested_by": "operator",
                    }
                ],
            }
        },
    }
    mapping = parse_mapping(mapping_doc)
    reg.save_mapping(mapping)

    on_disk = tmp_path / "supply_chain_v1.mappings.yaml"
    assert on_disk.exists()

    reg2 = OntologyRegistry.from_directory(tmp_path)
    m = reg2.get_mapping("supply_chain_v1")
    assert m is not None
    assert m.for_class("Supplier").sources[0].data_source == "suppliers_csv"

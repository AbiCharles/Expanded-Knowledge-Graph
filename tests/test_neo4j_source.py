"""Neo4j connector tests.

The driver is mocked so the suite doesn't need a live Neo4j. The goal is
to exercise:

  - Cypher safety guard (write clauses rejected, reads allowed)
  - Binding-driven dispatch (mapping's query_template wins; auto-derived
    MATCH otherwise)
  - Row → KnowledgeFact conversion (node properties + tabular returns)
  - run_cypher() playground path
"""
from __future__ import annotations

import pytest
from tcs_hitl_context import KnowledgeQuery

from backend.datasources.neo4j_source import (
    Neo4jResolver,
    _jsonable,
    _node_to_dict,
)
from backend.ontology.cypher_safety import CypherSafetyError, assert_read_only


# =============================================================================
# Cypher safety guard — pure unit tests
# =============================================================================
class TestCypherSafety:
    def test_plain_match_passes(self) -> None:
        assert_read_only("MATCH (n:Supplier) RETURN n LIMIT 10")

    def test_match_with_where_passes(self) -> None:
        assert_read_only(
            "MATCH (n:Supplier) WHERE n.country = $c RETURN n LIMIT $max_results"
        )

    def test_call_read_proc_passes(self) -> None:
        assert_read_only("CALL db.labels() YIELD label RETURN label")

    @pytest.mark.parametrize(
        "cypher",
        [
            "CREATE (n:Supplier {id: 'X'}) RETURN n",
            "MATCH (n) DETACH DELETE n",
            "MERGE (n:Foo {x: 1}) RETURN n",
            "MATCH (n:Supplier) SET n.country = 'NL' RETURN n",
            "MATCH (n:Supplier) REMOVE n.country RETURN n",
            "DROP INDEX my_idx",
            "FOREACH (x IN [1,2,3] | CREATE (n:Foo {id: x}))",
            "LOAD CSV FROM 'file:///x.csv' AS row CREATE (n:Foo {id: row[0]})",
        ],
    )
    def test_write_clauses_rejected(self, cypher: str) -> None:
        with pytest.raises(CypherSafetyError):
            assert_read_only(cypher)

    @pytest.mark.parametrize(
        "cypher",
        [
            "CALL apoc.create.node(['Foo'], {x:1})",
            "CALL apoc.refactor.mergeNodes([n,m])",
            "CALL apoc.periodic.iterate('MATCH (n) RETURN n', 'DELETE n', {})",
            "CALL n10s.rdf.import.fetch('http://x.com/data.ttl', 'Turtle')",
            "CALL gds.graph.project('g', 'A', 'REL')",
            "CALL db.create.fulltextIndex('idx', ['A'], ['name'])",
        ],
    )
    def test_dangerous_procs_rejected(self, cypher: str) -> None:
        with pytest.raises(CypherSafetyError):
            assert_read_only(cypher)

    def test_comments_are_stripped_before_scan(self) -> None:
        # `CREATE` inside a comment should not trip the guard.
        assert_read_only("MATCH (n) RETURN n // would CREATE if not commented")
        assert_read_only("/* CREATE (x) */ MATCH (n) RETURN n")

    def test_empty_input_rejected(self) -> None:
        with pytest.raises(CypherSafetyError):
            assert_read_only("")


# =============================================================================
# Driver mock helpers
# =============================================================================
class _FakeRecord(dict):
    """Acts like the real neo4j.Record — dict-like access by column name."""

    def keys(self):  # type: ignore[override]
        return list(super().keys())


class _FakeNode:
    """Minimal stand-in for neo4j.graph.Node — has `.items()` and `.labels`."""

    def __init__(self, labels: list[str], props: dict):
        self._labels = labels
        self._props = props

    @property
    def labels(self):
        return self._labels

    def items(self):
        return self._props.items()


class _FakeSession:
    def __init__(self, rows: list[dict]):
        self._rows = rows
        self.last_cypher: str | None = None
        self.last_params: dict | None = None

    def __enter__(self):
        return self

    def __exit__(self, *_a):
        return False

    def run(self, cypher: str, **params):
        self.last_cypher = cypher
        self.last_params = params
        return [_FakeRecord(r) for r in self._rows]


class _FakeDriver:
    def __init__(self, rows: list[dict]):
        self._session = _FakeSession(rows)

    def session(self, **_kw):
        return self._session

    def close(self):
        pass


def _resolver_with_rows(rows: list[dict]) -> Neo4jResolver:
    r = Neo4jResolver(source_id="graph_test", uri="bolt://unused:7687")
    r._driver = _FakeDriver(rows)  # type: ignore[assignment]
    return r


# =============================================================================
# Binding-driven dispatch
# =============================================================================
def test_binding_query_template_is_executed() -> None:
    r = _resolver_with_rows(
        [{"id": "S-001", "title": "Acme", "summary": "DE supplier"}]
    )
    q = KnowledgeQuery(
        ontology_type="Supplier",
        filters={
            "__binding__": {
                "data_source": "graph_test",
                "identifier_column": "supplier_id",
                "attribute_map": {},
                "query_template": (
                    "MATCH (n:Supplier) WHERE n.country = $country "
                    "RETURN n.supplier_id AS id, n.name AS title, n.country AS summary"
                ),
            },
            "country": "DE",
        },
        requested_by="t",
        purpose="t",
        max_results=10,
    )
    facts = r.resolve(q)
    # The fake driver received the template (not an auto-derived one)
    sess = r._driver._session  # type: ignore[attr-defined]
    assert "MATCH (n:Supplier) WHERE n.country = $country" in sess.last_cypher
    # __binding__ is stripped from the params handed to the driver
    assert "__binding__" not in sess.last_params
    assert sess.last_params["country"] == "DE"
    assert sess.last_params["max_results"] == 10
    # Fact shape
    assert len(facts) == 1
    assert facts[0].ref.id == "S-001"
    assert facts[0].ref.source == "neo4j:graph_test"


def test_no_binding_falls_back_to_auto_match() -> None:
    """Without a query_template, the resolver auto-derives a MATCH on the
    requested class label."""
    r = _resolver_with_rows([{"n": _FakeNode(["Supplier"], {"id": "S-9", "name": "X"})}])
    q = KnowledgeQuery(
        ontology_type="Supplier",
        filters={},
        requested_by="t",
        purpose="t",
        max_results=5,
    )
    facts = r.resolve(q)
    sess = r._driver._session  # type: ignore[attr-defined]
    # Auto-derived MATCH on the class label, no WHERE (no id supplied)
    assert "MATCH (n:`Supplier`)" in sess.last_cypher
    assert "WHERE" not in sess.last_cypher
    assert "LIMIT $max_results" in sess.last_cypher
    # Node properties flattened into the fact
    assert len(facts) == 1
    assert facts[0].ref.id == "S-9"
    assert facts[0].payload["title"] == "X"


def test_query_template_params_auto_filled_with_none_when_missing() -> None:
    """If the binding's `query_template` references `$param` that the
    caller didn't supply in `filters`, the resolver auto-fills it with
    None so the optional-filter idiom (`$x IS NULL OR …`) works.

    Cypher itself rejects unbound `$param` references; this regression
    test catches the case where a chip-driven proposal stage passes
    `where: {}` and the template expects named params."""
    r = _resolver_with_rows([{"id": "S-001", "title": "Acme", "summary": "NL"}])
    q = KnowledgeQuery(
        ontology_type="Supplier",
        filters={
            "__binding__": {
                "data_source": "graph_test",
                "query_template": (
                    "MATCH (n:Supplier) "
                    "WHERE ($supplier_id IS NULL OR n.supplier_id = $supplier_id) "
                    "  AND ($country IS NULL OR n.country = $country) "
                    "RETURN n.supplier_id AS id, n.name AS title, "
                    "       n.country AS summary "
                    "LIMIT $max_results"
                ),
            },
            # Crucially: neither supplier_id nor country supplied
        },
        requested_by="t",
        purpose="t",
        max_results=10,
    )
    facts = r.resolve(q)
    sess = r._driver._session  # type: ignore[attr-defined]
    # Both `$supplier_id` and `$country` end up bound — to None — so the
    # driver doesn't raise.
    assert sess.last_params.get("supplier_id") is None
    assert sess.last_params.get("country") is None
    assert sess.last_params["max_results"] == 10
    assert len(facts) == 1


def test_no_binding_scopes_by_id_when_supplied() -> None:
    """If the filter dict includes the id key, the auto MATCH adds WHERE."""
    r = _resolver_with_rows([])
    q = KnowledgeQuery(
        ontology_type="Supplier",
        filters={
            "__binding__": {"identifier_column": "supplier_id"},
            "supplier_id": "S-9",
        },
        requested_by="t",
        purpose="t",
        max_results=5,
    )
    r.resolve(q)
    sess = r._driver._session  # type: ignore[attr-defined]
    assert "WHERE n.`supplier_id` = $supplier_id" in sess.last_cypher


def test_write_cypher_in_query_template_is_rejected() -> None:
    """A binding that smuggles a CREATE into query_template returns 0
    facts (logged warning) — the guard fires before the driver call."""
    r = _resolver_with_rows([{"id": "X"}])
    q = KnowledgeQuery(
        ontology_type="Supplier",
        filters={
            "__binding__": {
                "data_source": "graph_test",
                "query_template": "CREATE (n:Supplier {id: 'X'}) RETURN n",
            },
        },
        requested_by="t",
        purpose="t",
        max_results=5,
    )
    facts = r.resolve(q)
    assert facts == []
    # Verify the driver was never asked
    assert r._driver._session.last_cypher is None  # type: ignore[attr-defined]


# =============================================================================
# run_cypher() playground path
# =============================================================================
def test_run_cypher_returns_rows() -> None:
    r = _resolver_with_rows([{"n": "row1"}, {"n": "row2"}])
    out = r.run_cypher("MATCH (n) RETURN n LIMIT $max_results", {}, limit=10)
    assert out == {"columns": ["n"], "rows": [["row1"], ["row2"]]}


def test_run_cypher_rejects_writes() -> None:
    r = _resolver_with_rows([])
    out = r.run_cypher("CREATE (n:Foo) RETURN n", {}, limit=10)
    assert "error" in out
    assert "write clause" in out["error"].lower()


# =============================================================================
# Helpers
# =============================================================================
def test_node_to_dict_recognises_node_protocol() -> None:
    n = _FakeNode(["Supplier"], {"id": "S-1", "name": "x"})
    assert _node_to_dict(n) == {"id": "S-1", "name": "x"}


def test_node_to_dict_passes_plain_dict_through() -> None:
    assert _node_to_dict({"x": 1}) == {"x": 1}


def test_node_to_dict_returns_none_for_primitives() -> None:
    assert _node_to_dict("hello") is None
    assert _node_to_dict(42) is None
    assert _node_to_dict(None) is None


def test_jsonable_coerces_node_into_dict() -> None:
    n = _FakeNode(["Supplier"], {"id": "S-1"})
    out = _jsonable(n)
    assert out == {"id": "S-1", "_labels": ["Supplier"]}

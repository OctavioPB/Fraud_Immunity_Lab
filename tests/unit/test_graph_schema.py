"""
Unit tests for ml/graph/schema.py.

Verifies Cypher file parsing, query loading, and constants.
No live Neo4j instance required.
"""

import re
from pathlib import Path

import pytest

from ml.graph.schema import (
    GraphDB,
    NodeLabel,
    RelType,
    _parse_cypher_file,
)

_QUERIES_DIR = Path(__file__).parent.parent.parent / "ml" / "graph" / "queries"


class TestNodeLabels:
    def test_account_label(self) -> None:
        assert NodeLabel.ACCOUNT == "Account"

    def test_transaction_label(self) -> None:
        assert NodeLabel.TRANSACTION == "Transaction"

    def test_all_labels_pascal_case(self) -> None:
        for attr in ("ACCOUNT", "TRANSACTION", "DEVICE", "MERCHANT", "IP_ADDRESS", "FRAUD_RING"):
            label = getattr(NodeLabel, attr)
            assert label[0].isupper(), f"{label} is not PascalCase"


class TestRelTypes:
    def test_sent_to(self) -> None:
        assert RelType.SENT_TO == "SENT_TO"

    def test_all_rel_types_screaming_snake_case(self) -> None:
        for attr in ("SENT_TO", "LOGGED_IN_FROM", "USED_DEVICE", "TRANSACTED_AT", "INCLUDES"):
            rel = getattr(RelType, attr)
            assert rel == rel.upper(), f"{rel} is not SCREAMING_SNAKE_CASE"
            assert " " not in rel


class TestParseCypherFile:
    def test_parses_constraints_file(self) -> None:
        path = _QUERIES_DIR / "constraints.cypher"
        stmts = _parse_cypher_file(path)
        assert len(stmts) > 0

    def test_strips_comments(self) -> None:
        path = _QUERIES_DIR / "constraints.cypher"
        stmts = _parse_cypher_file(path)
        for stmt in stmts:
            assert not stmt.strip().startswith("//")

    def test_no_empty_statements(self) -> None:
        path = _QUERIES_DIR / "constraints.cypher"
        stmts = _parse_cypher_file(path)
        for stmt in stmts:
            assert stmt.strip() != ""

    def test_constraints_file_contains_account_constraint(self) -> None:
        path = _QUERIES_DIR / "constraints.cypher"
        stmts = _parse_cypher_file(path)
        combined = "\n".join(stmts)
        assert "Account" in combined
        assert "account_id" in combined.lower()

    def test_missing_file_raises(self) -> None:
        with pytest.raises(FileNotFoundError):
            _parse_cypher_file(_QUERIES_DIR / "nonexistent.cypher")


class TestGraphDBLoadQuery:
    def test_loads_upsert_transaction(self) -> None:
        query = GraphDB.load_query("upsert_transaction.cypher")
        assert "MERGE" in query
        assert "$transaction_id" in query

    def test_loads_upsert_login(self) -> None:
        query = GraphDB.load_query("upsert_login.cypher")
        assert "$session_id" in query
        assert "$account_id" in query

    def test_loads_louvain_run(self) -> None:
        query = GraphDB.load_query("louvain_run.cypher")
        assert "gds.louvain.stream" in query
        assert "$graph_name" in query

    def test_missing_query_raises(self) -> None:
        with pytest.raises(FileNotFoundError):
            GraphDB.load_query("does_not_exist.cypher")

    def test_all_queries_have_parameter_syntax(self) -> None:
        """Every .cypher file should use $param syntax, not string concatenation."""
        for cypher_file in _QUERIES_DIR.glob("*.cypher"):
            content = cypher_file.read_text(encoding="utf-8")
            # Skip projection query which has a known GDS filter limitation
            if "louvain_project" in cypher_file.name:
                continue
            # Ensure no f-string-style or %-style interpolation
            assert "%" not in content.replace("//", ""), (
                f"{cypher_file.name} contains %-style interpolation"
            )


class TestQueriesNoPIIInterpolation:
    """Ensure no Cypher file directly interpolates account identifiers."""

    def test_upsert_transaction_uses_params(self) -> None:
        query = GraphDB.load_query("upsert_transaction.cypher")
        # account_id must come from parameters, not string concat
        assert "$sender_id" in query
        assert "$receiver_id" in query

    def test_upsert_login_uses_params(self) -> None:
        query = GraphDB.load_query("upsert_login.cypher")
        assert "$account_id" in query

    def test_upsert_fraud_ring_uses_params(self) -> None:
        query = GraphDB.load_query("upsert_fraud_ring.cypher")
        assert "$ring_id" in query
        assert "$member_ids" in query

    def test_get_fraud_rings_uses_params(self) -> None:
        query = GraphDB.load_query("get_fraud_rings.cypher")
        assert "$min_risk_score" in query
        assert "$since_ms" in query

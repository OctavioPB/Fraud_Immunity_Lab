"""
schema — Neo4j Graph Schema Management
=======================================

Defines the graph schema for the Fraud Immunity Lab:
  - Node labels: Account, Transaction, Device, Merchant, IPAddress, FraudRing
  - Relationship types: SENT_TO, LOGGED_IN_FROM, USED_DEVICE, TRANSACTED_AT, INCLUDES
  - Applies constraints and indexes from queries/constraints.cypher

CLAUDE.md conventions:
  - Node labels: PascalCase
  - Relationship types: SCREAMING_SNAKE_CASE
  - All Cypher queries parameterized — no string interpolation of user data

Usage:
    driver = GraphDB.get_driver()
    GraphDB.apply_constraints(driver)
"""

import os
from pathlib import Path
from typing import Any

import structlog

log = structlog.get_logger(__name__)

_QUERIES_DIR = Path(__file__).parent / "queries"

_NEO4J_URI: str = os.getenv("NEO4J_URI", "bolt://localhost:7687")
_NEO4J_USER: str = os.getenv("NEO4J_USERNAME", "neo4j")
_NEO4J_PASSWORD: str = os.getenv("NEO4J_PASSWORD", "password")
_NEO4J_DATABASE: str = os.getenv("NEO4J_DATABASE", "neo4j")


# ── Node label constants ───────────────────────────────────────────────────────

class NodeLabel:
    ACCOUNT = "Account"
    TRANSACTION = "Transaction"
    DEVICE = "Device"
    MERCHANT = "Merchant"
    IP_ADDRESS = "IPAddress"
    FRAUD_RING = "FraudRing"


# ── Relationship type constants ────────────────────────────────────────────────

class RelType:
    SENT_TO = "SENT_TO"
    LOGGED_IN_FROM = "LOGGED_IN_FROM"
    USED_DEVICE = "USED_DEVICE"
    TRANSACTED_AT = "TRANSACTED_AT"
    INCLUDES = "INCLUDES"


# ── Driver management ──────────────────────────────────────────────────────────

class GraphDB:
    """
    Neo4j driver factory and schema management.

    All methods are class-level to allow use without instantiation.
    The driver is not cached at module level — callers manage lifecycle.
    """

    @classmethod
    def get_driver(
        cls,
        uri: str | None = None,
        user: str | None = None,
        password: str | None = None,
    ) -> Any:
        """
        Create and return a Neo4j driver instance.

        Args:
            uri: Bolt URI. Falls back to `NEO4J_URI` env var.
            user: Username. Falls back to `NEO4J_USERNAME` env var.
            password: Password. Falls back to `NEO4J_PASSWORD` env var.

        Returns:
            neo4j.GraphDatabase driver instance.
        """
        try:
            from neo4j import GraphDatabase  # type: ignore[import]
        except ImportError:
            raise RuntimeError(
                "neo4j driver not installed. Run: pip install neo4j"
            )

        driver = GraphDatabase.driver(
            uri or _NEO4J_URI,
            auth=(user or _NEO4J_USER, password or _NEO4J_PASSWORD),
        )
        return driver

    @classmethod
    def apply_constraints(cls, driver: Any, database: str | None = None) -> None:
        """
        Apply all constraints and indexes from queries/constraints.cypher.

        Safe to call repeatedly — uses IF NOT EXISTS for idempotency.
        """
        db = database or _NEO4J_DATABASE
        cypher_path = _QUERIES_DIR / "constraints.cypher"
        statements = _parse_cypher_file(cypher_path)

        with driver.session(database=db) as session:
            for stmt in statements:
                try:
                    session.run(stmt)
                except Exception as exc:
                    log.warning(
                        "constraint_apply_warning",
                        statement=stmt[:80],
                        error=str(exc),
                    )

        log.info(
            "graph_constraints_applied",
            database=db,
            statement_count=len(statements),
        )

    @classmethod
    def verify_connectivity(cls, driver: Any) -> bool:
        """
        Verify Neo4j connectivity by running a trivial query.

        Returns:
            True if connection is healthy.
        """
        try:
            driver.verify_connectivity()
            return True
        except Exception as exc:
            log.error("neo4j_connectivity_failed", error=str(exc))
            return False

    @classmethod
    def load_query(cls, filename: str) -> str:
        """
        Load a named Cypher query from the queries/ directory.

        Args:
            filename: File name (e.g. "upsert_transaction.cypher").

        Returns:
            Query string with comments stripped.
        """
        path = _QUERIES_DIR / filename
        if not path.exists():
            raise FileNotFoundError(f"Cypher query not found: {path}")
        return path.read_text(encoding="utf-8")

    @classmethod
    def run_query(
        cls,
        driver: Any,
        query: str,
        parameters: dict[str, Any] | None = None,
        *,
        database: str | None = None,
    ) -> list[dict[str, Any]]:
        """
        Execute a parameterized Cypher query and return all records as dicts.

        Args:
            driver: Neo4j driver instance.
            query: Cypher query string (must use $param syntax — no interpolation).
            parameters: Query parameters dict.
            database: Target database name.

        Returns:
            List of record dicts.
        """
        db = database or _NEO4J_DATABASE
        with driver.session(database=db) as session:
            result = session.run(query, parameters or {})
            return [dict(record) for record in result]


# ── Cypher file parser ─────────────────────────────────────────────────────────

def _parse_cypher_file(path: Path) -> list[str]:
    """
    Parse a .cypher file into individual statements.

    Strips comments (lines starting with //) and splits on semicolons.
    Empty statements are skipped.
    """
    raw = path.read_text(encoding="utf-8")
    # Strip single-line comments
    lines = [
        line for line in raw.splitlines()
        if not line.strip().startswith("//") and line.strip()
    ]
    joined = "\n".join(lines)
    statements = [s.strip() for s in joined.split(";") if s.strip()]
    return statements

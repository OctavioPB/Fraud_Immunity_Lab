"""
test_tenant_isolation — Two-Tenant Data Isolation Integration Test
==================================================================

Verifies Sprint 9 DoD: two tenants (`acme` and `globex`) have zero data bleed
across Pinecone, Neo4j, and the cost tracking PostgreSQL table.

Run with real infrastructure (not mocked):
    pytest tests/integration/test_tenant_isolation.py -v -m integration

Prerequisites:
    - Running PostgreSQL, Redis, Neo4j, and Pinecone (or a Pinecone-compatible stub)
    - PINECONE_API_KEY, NEO4J_URI/USERNAME/PASSWORD, DATABASE_URL in environment
"""

import os
import time
import uuid

import pytest

# ── Tenant fixtures ────────────────────────────────────────────────────────────

TENANT_A = "acme"
TENANT_B = "globex"
FAKE_ACCOUNT_A = f"acct_a_{uuid.uuid4().hex[:8]}"
FAKE_ACCOUNT_B = f"acct_b_{uuid.uuid4().hex[:8]}"

# Stub embedding vector (3072-d zeros with one distinguishing dimension)
_DIM = 3072


def _vec_a() -> list[float]:
    v = [0.0] * _DIM
    v[0] = 1.0
    return v


def _vec_b() -> list[float]:
    v = [0.0] * _DIM
    v[1] = 1.0
    return v


# ── Helpers ────────────────────────────────────────────────────────────────────

def _pinecone_namespace(tenant_id: str) -> str:
    return "" if tenant_id == "default" else tenant_id


# ── Pinecone isolation tests ────────────────────────────────────────────────────

@pytest.mark.integration
class TestPineconeNamespaceIsolation:
    """Vectors upserted to tenant A's namespace must not be visible from tenant B's namespace."""

    @pytest.fixture(autouse=True)
    def setup_pinecone(self):
        pc_key = os.getenv("PINECONE_API_KEY", "")
        if not pc_key:
            pytest.skip("PINECONE_API_KEY not set")
        try:
            from pinecone import Pinecone  # type: ignore[import]
        except ImportError:
            pytest.skip("pinecone-client not installed")

        pc = Pinecone(api_key=pc_key)
        index_name = os.getenv("PINECONE_INDEX_CLEAN", "clean-profiles")
        self.index = pc.Index(index_name)
        self.ns_a = _pinecone_namespace(TENANT_A)
        self.ns_b = _pinecone_namespace(TENANT_B)
        self.vec_id_a = f"test_{FAKE_ACCOUNT_A}"
        self.vec_id_b = f"test_{FAKE_ACCOUNT_B}"

        yield

        # Cleanup: remove test vectors from both namespaces
        try:
            self.index.delete(ids=[self.vec_id_a], namespace=self.ns_a)
            self.index.delete(ids=[self.vec_id_b], namespace=self.ns_b)
        except Exception:
            pass

    def test_upsert_to_tenant_a_namespace(self):
        """Upsert a vector to acme namespace — should succeed."""
        self.index.upsert(
            vectors=[(self.vec_id_a, _vec_a(), {"tenant_id": TENANT_A, "label": "legitimate"})],
            namespace=self.ns_a,
        )
        time.sleep(1)  # Pinecone eventual consistency

        result = self.index.fetch(ids=[self.vec_id_a], namespace=self.ns_a)
        assert self.vec_id_a in result.get("vectors", {}), (
            f"Vector {self.vec_id_a} not found in namespace '{self.ns_a}'"
        )

    def test_tenant_b_cannot_see_tenant_a_vector(self):
        """Vectors in acme namespace must not appear in globex namespace."""
        self.index.upsert(
            vectors=[(self.vec_id_a, _vec_a(), {"tenant_id": TENANT_A, "label": "legitimate"})],
            namespace=self.ns_a,
        )
        time.sleep(1)

        result = self.index.fetch(ids=[self.vec_id_a], namespace=self.ns_b)
        vectors = result.get("vectors", {})
        assert self.vec_id_a not in vectors, (
            f"DATA BLEED: vector '{self.vec_id_a}' from namespace '{self.ns_a}' "
            f"is visible in namespace '{self.ns_b}'"
        )

    def test_query_returns_only_same_namespace_results(self):
        """A query from tenant B's namespace must not return tenant A's vectors."""
        # Upsert a highly similar vector to namespace A
        self.index.upsert(
            vectors=[(self.vec_id_a, _vec_a(), {"tenant_id": TENANT_A})],
            namespace=self.ns_a,
        )
        # Upsert a different vector to namespace B
        self.index.upsert(
            vectors=[(self.vec_id_b, _vec_b(), {"tenant_id": TENANT_B})],
            namespace=self.ns_b,
        )
        time.sleep(1)

        # Query from namespace B with vec_a (which should match acme's vector)
        result = self.index.query(
            vector=_vec_a(),
            top_k=5,
            include_metadata=True,
            namespace=self.ns_b,
        )
        match_ids = [m["id"] for m in result.get("matches", [])]
        assert self.vec_id_a not in match_ids, (
            f"DATA BLEED: query in namespace '{self.ns_b}' returned tenant A vector '{self.vec_id_a}'"
        )


# ── Neo4j isolation tests ───────────────────────────────────────────────────────

@pytest.mark.integration
class TestNeo4jTenantIsolation:
    """Account nodes tagged with tenant_id must not be visible across tenant queries."""

    @pytest.fixture(autouse=True)
    def setup_neo4j(self):
        uri = os.getenv("NEO4J_URI", "bolt://localhost:7687")
        user = os.getenv("NEO4J_USERNAME", "neo4j")
        password = os.getenv("NEO4J_PASSWORD", "")
        if not password:
            pytest.skip("NEO4J_PASSWORD not set")
        try:
            from neo4j import GraphDatabase  # type: ignore[import]
        except ImportError:
            pytest.skip("neo4j package not installed")

        self.driver = GraphDatabase.driver(uri, auth=(user, password))
        self.acct_a = f"tok_{FAKE_ACCOUNT_A}"
        self.acct_b = f"tok_{FAKE_ACCOUNT_B}"
        self.tx_id = f"tx_{uuid.uuid4().hex}"

        yield

        # Cleanup: remove test nodes
        with self.driver.session() as session:
            session.run(
                "MATCH (a:Account) WHERE a.account_id IN $ids DETACH DELETE a",
                {"ids": [self.acct_a, self.acct_b]},
            )
        self.driver.close()

    def _create_account(self, account_id: str, tenant_id: str) -> None:
        with self.driver.session() as session:
            session.run(
                """
                MERGE (a:Account {account_id: $account_id, tenant_id: $tenant_id})
                  ON CREATE SET a.created_at = timestamp(), a.segment = 'retail_banking'
                """,
                {"account_id": account_id, "tenant_id": tenant_id},
            )

    def test_account_created_with_tenant_id(self):
        self._create_account(self.acct_a, TENANT_A)
        with self.driver.session() as session:
            result = session.run(
                "MATCH (a:Account {account_id: $id, tenant_id: $tenant}) RETURN a",
                {"id": self.acct_a, "tenant": TENANT_A},
            )
            records = list(result)
        assert len(records) == 1, "Account node not found with correct tenant_id"

    def test_tenant_b_query_does_not_return_tenant_a_accounts(self):
        """A query filtering by tenant_id=globex must not return acme accounts."""
        self._create_account(self.acct_a, TENANT_A)
        self._create_account(self.acct_b, TENANT_B)

        with self.driver.session() as session:
            result = session.run(
                "MATCH (a:Account {tenant_id: $tenant}) RETURN a.account_id AS id",
                {"tenant": TENANT_B},
            )
            ids = [r["id"] for r in result]

        assert self.acct_a not in ids, (
            f"DATA BLEED: acme account '{self.acct_a}' visible in globex query"
        )
        assert self.acct_b in ids, "globex account missing from globex query"


# ── PostgreSQL cost log isolation ───────────────────────────────────────────────

@pytest.mark.integration
class TestCostTrackerTenantIsolation:
    """LLM cost records must be isolated per tenant in the llm_cost_log table."""

    @pytest.fixture(autouse=True)
    def setup_db(self):
        dsn = os.getenv("DATABASE_URL", "")
        if not dsn:
            pytest.skip("DATABASE_URL not set")
        try:
            import psycopg2  # type: ignore[import]
        except ImportError:
            pytest.skip("psycopg2 not installed")

        self.conn = psycopg2.connect(dsn)
        self.run_id = f"test_{uuid.uuid4().hex}"

        yield

        # Cleanup: remove test rows
        cur = self.conn.cursor()
        cur.execute("DELETE FROM llm_cost_log WHERE dag_run_id = %s", (self.run_id,))
        self.conn.commit()
        cur.close()
        self.conn.close()

    def _insert_cost(self, tenant_id: str, cost_usd: float) -> None:
        cur = self.conn.cursor()
        cur.execute(
            """
            INSERT INTO llm_cost_log
                (tenant_id, model, prompt_tokens, completion_tokens, cost_usd, dag_run_id, recorded_at_ms)
            VALUES (%s, %s, %s, %s, %s, %s, %s)
            """,
            (tenant_id, "gpt-4o", 1000, 200, cost_usd, self.run_id, int(time.time() * 1000)),
        )
        self.conn.commit()
        cur.close()

    def _get_spend(self, tenant_id: str) -> float:
        cur = self.conn.cursor()
        cur.execute(
            "SELECT COALESCE(SUM(cost_usd), 0) FROM llm_cost_log "
            "WHERE tenant_id = %s AND dag_run_id = %s",
            (tenant_id, self.run_id),
        )
        row = cur.fetchone()
        cur.close()
        return float(row[0]) if row else 0.0

    def test_cost_log_is_tenant_scoped(self):
        """Cost records inserted for acme must not appear in globex spend."""
        self._insert_cost(TENANT_A, 1.50)
        self._insert_cost(TENANT_B, 0.75)

        spend_a = self._get_spend(TENANT_A)
        spend_b = self._get_spend(TENANT_B)

        assert abs(spend_a - 1.50) < 0.01, f"Expected acme spend ~1.50, got {spend_a}"
        assert abs(spend_b - 0.75) < 0.01, f"Expected globex spend ~0.75, got {spend_b}"

    def test_globex_spend_excludes_acme_records(self):
        self._insert_cost(TENANT_A, 100.0)

        spend_b = self._get_spend(TENANT_B)
        assert spend_b == 0.0, (
            f"DATA BLEED: globex spend query returned {spend_b} (should be 0, acme data leaking)"
        )


# ── Tenant Provisioner isolation ────────────────────────────────────────────────

@pytest.mark.integration
class TestTenantProvisionerIsolation:
    """Provisioning and deactivating tenants must not affect each other's records."""

    @pytest.fixture(autouse=True)
    def setup(self):
        dsn = os.getenv("DATABASE_URL", "")
        if not dsn:
            pytest.skip("DATABASE_URL not set")
        try:
            from api.services.tenant_provisioner import TenantProvisioner
        except ImportError:
            pytest.skip("api.services.tenant_provisioner not importable in this environment")

        self.provisioner = TenantProvisioner()
        self.tid_a = f"test-{uuid.uuid4().hex[:8]}"
        self.tid_b = f"test-{uuid.uuid4().hex[:8]}"

        yield

        # Cleanup: deactivate + delete test tenants
        try:
            import psycopg2  # type: ignore[import]
            conn = psycopg2.connect(dsn)
            cur = conn.cursor()
            cur.execute("DELETE FROM tenants WHERE tenant_id IN (%s, %s)", (self.tid_a, self.tid_b))
            conn.commit()
            cur.close()
            conn.close()
        except Exception:
            pass

    def test_provision_two_tenants_independently(self):
        status_a = self.provisioner.provision(self.tid_a, "Test Tenant A", 50.0)
        status_b = self.provisioner.provision(self.tid_b, "Test Tenant B", 100.0)

        assert status_a.postgres_record_ready, "Tenant A not provisioned in PostgreSQL"
        assert status_b.postgres_record_ready, "Tenant B not provisioned in PostgreSQL"

        rec_a = self.provisioner.get_tenant(self.tid_a)
        rec_b = self.provisioner.get_tenant(self.tid_b)

        assert rec_a is not None
        assert rec_b is not None
        assert rec_a["monthly_llm_budget_usd"] == 50.0
        assert rec_b["monthly_llm_budget_usd"] == 100.0

    def test_deactivating_tenant_a_does_not_affect_tenant_b(self):
        self.provisioner.provision(self.tid_a, "Test Tenant A", 50.0)
        self.provisioner.provision(self.tid_b, "Test Tenant B", 100.0)

        deactivated = self.provisioner.deactivate(self.tid_a)
        assert deactivated, "Tenant A deactivation returned False"

        rec_a = self.provisioner.get_tenant(self.tid_a)
        rec_b = self.provisioner.get_tenant(self.tid_b)

        assert rec_a["active"] is False, "Tenant A should be inactive"
        assert rec_b["active"] is True, "Tenant B should still be active"

"""
tenant_provisioner — Tenant Resource Provisioning
==================================================

Creates all per-tenant infrastructure resources when a new tenant is onboarded.

Provisioning steps (each is idempotent and gracefully skipped on failure):
  1. PostgreSQL — insert record into `tenants` table
  2. Redis — write sentinel key `tenant:{id}:provisioned` to confirm namespace
  3. Neo4j — verify connectivity; constraints are applied globally, not per-tenant
  4. Pinecone — namespace is implicit (first upsert creates it); we validate API access
  5. Airflow — set `DEFAULT_TENANT_ID` Variable if Airflow admin API is reachable

Hard Rule #4: tenant_id is a slug (never raw PII) and safe to use as a namespace key.
"""

import os
import time
from typing import Any

import structlog

from api.schemas.tenants import TenantProvisioningStatus

log = structlog.get_logger(__name__)

_REDIS_URL: str = os.getenv("REDIS_URL", "redis://localhost:6379/0")
_AIRFLOW_API_URL: str = os.getenv("AIRFLOW_API_URL", "http://localhost:8080/api/v1")
_AIRFLOW_USERNAME: str = os.getenv("AIRFLOW_USERNAME", "admin")
_AIRFLOW_PASSWORD: str = os.getenv("AIRFLOW_PASSWORD", "admin")

# PostgreSQL DSN — falls back gracefully if not set
_POSTGRES_DSN: str = os.getenv(
    "DATABASE_URL",
    "postgresql://airflow:airflow@localhost:5432/airflow",
)


class TenantProvisioner:
    """Orchestrates creation of all per-tenant resources."""

    def provision(
        self,
        tenant_id: str,
        display_name: str,
        monthly_llm_budget_usd: float,
    ) -> TenantProvisioningStatus:
        """
        Run all provisioning steps and return a status report.

        All steps are attempted independently — a failure in one does not
        block the others. Errors are collected in `status.errors`.
        """
        status = TenantProvisioningStatus()

        self._provision_postgres(tenant_id, display_name, monthly_llm_budget_usd, status)
        self._provision_redis(tenant_id, status)
        self._provision_neo4j(status)
        self._provision_pinecone(tenant_id, status)
        self._provision_airflow(tenant_id, status)

        log.info(
            "tenant_provisioned",
            tenant_id=tenant_id,
            fully_provisioned=status.fully_provisioned,
            errors=status.errors,
        )
        return status

    # ── Step 1: PostgreSQL ─────────────────────────────────────────────────────

    def _provision_postgres(
        self,
        tenant_id: str,
        display_name: str,
        monthly_llm_budget_usd: float,
        status: TenantProvisioningStatus,
    ) -> None:
        try:
            import psycopg2  # type: ignore[import]

            conn = psycopg2.connect(_POSTGRES_DSN)
            cur = conn.cursor()

            # Ensure tenants table exists
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS tenants (
                    tenant_id              VARCHAR(64) PRIMARY KEY,
                    display_name           VARCHAR(128) NOT NULL,
                    monthly_llm_budget_usd REAL        NOT NULL DEFAULT 100.0,
                    active                 BOOLEAN     NOT NULL DEFAULT TRUE,
                    created_at_ms          BIGINT      NOT NULL
                )
                """
            )
            cur.execute(
                """
                INSERT INTO tenants
                    (tenant_id, display_name, monthly_llm_budget_usd, created_at_ms)
                VALUES (%s, %s, %s, %s)
                ON CONFLICT (tenant_id) DO NOTHING
                """,
                (
                    tenant_id,
                    display_name,
                    monthly_llm_budget_usd,
                    int(time.time() * 1000),
                ),
            )
            conn.commit()
            cur.close()
            conn.close()
            status.postgres_record_ready = True
            log.info("tenant_postgres_provisioned", tenant_id=tenant_id)

        except Exception as exc:
            status.errors.append(f"PostgreSQL: {exc}")
            log.warning("tenant_postgres_provision_failed", tenant_id=tenant_id, error=str(exc))

    # ── Step 2: Redis ──────────────────────────────────────────────────────────

    def _provision_redis(
        self,
        tenant_id: str,
        status: TenantProvisioningStatus,
    ) -> None:
        try:
            import redis as redis_lib  # type: ignore[import]

            r = redis_lib.from_url(_REDIS_URL, decode_responses=True)
            # Write a sentinel key so the namespace is visible in Redis
            r.set(
                f"tenant:{tenant_id}:provisioned",
                int(time.time() * 1000),
                ex=365 * 86_400,  # 1-year TTL — refreshed on each login
            )
            # Initialize rate-limit budget sentinel
            r.set(
                f"tenant:{tenant_id}:active",
                "1",
                ex=365 * 86_400,
            )
            status.redis_namespace_ready = True
            log.info("tenant_redis_provisioned", tenant_id=tenant_id)

        except Exception as exc:
            status.errors.append(f"Redis: {exc}")
            log.warning("tenant_redis_provision_failed", tenant_id=tenant_id, error=str(exc))

    # ── Step 3: Neo4j ──────────────────────────────────────────────────────────

    def _provision_neo4j(self, status: TenantProvisioningStatus) -> None:
        try:
            from ml.graph.schema import GraphDB

            db = GraphDB()
            db.verify_connectivity()
            # Constraints are global (applied on startup); we just verify reachability.
            status.neo4j_constraints_ready = True
            log.info("tenant_neo4j_verified")

        except Exception as exc:
            # Neo4j is optional — graph features degrade gracefully
            status.errors.append(f"Neo4j (non-blocking): {exc}")
            log.warning("tenant_neo4j_provision_failed", error=str(exc))

    # ── Step 4: Pinecone ───────────────────────────────────────────────────────

    def _provision_pinecone(
        self,
        tenant_id: str,
        status: TenantProvisioningStatus,
    ) -> None:
        try:
            from pinecone import Pinecone  # type: ignore[import]

            pc = Pinecone(api_key=os.getenv("PINECONE_API_KEY", ""))
            # Namespaces are created implicitly on first upsert.
            # We validate that the index exists and is accessible.
            clean_index_name = os.getenv("PINECONE_INDEX_CLEAN", "clean-profiles")
            pc.Index(clean_index_name).describe_index_stats()
            status.pinecone_namespace_ready = True
            log.info(
                "tenant_pinecone_namespace_ready",
                tenant_id=tenant_id,
                namespace=_pinecone_namespace(tenant_id),
            )

        except Exception as exc:
            status.errors.append(f"Pinecone (non-blocking): {exc}")
            log.warning("tenant_pinecone_provision_failed", tenant_id=tenant_id, error=str(exc))

    # ── Step 5: Airflow ────────────────────────────────────────────────────────

    def _provision_airflow(
        self,
        tenant_id: str,
        status: TenantProvisioningStatus,
    ) -> None:
        try:
            import urllib.request
            import json

            variable_key = f"TENANT_{tenant_id.upper().replace('-', '_')}_ID"
            payload = json.dumps({"key": variable_key, "value": tenant_id}).encode()

            req = urllib.request.Request(
                f"{_AIRFLOW_API_URL}/variables",
                data=payload,
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            import base64

            creds = base64.b64encode(
                f"{_AIRFLOW_USERNAME}:{_AIRFLOW_PASSWORD}".encode()
            ).decode()
            req.add_header("Authorization", f"Basic {creds}")

            with urllib.request.urlopen(req, timeout=3) as resp:
                if resp.status in (200, 201):
                    status.airflow_variable_set = True
                    log.info("tenant_airflow_variable_set", variable=variable_key)

        except Exception as exc:
            # Airflow is optional in dev; missing it is a warning, not a hard failure
            status.errors.append(f"Airflow (non-blocking): {exc}")
            log.warning("tenant_airflow_provision_failed", tenant_id=tenant_id, error=str(exc))

    # ── Soft-delete ────────────────────────────────────────────────────────────

    def deactivate(self, tenant_id: str) -> bool:
        """Soft-delete a tenant: set active=false in PostgreSQL and Redis."""
        deactivated = False
        try:
            import psycopg2  # type: ignore[import]

            conn = psycopg2.connect(_POSTGRES_DSN)
            cur = conn.cursor()
            cur.execute(
                "UPDATE tenants SET active = FALSE WHERE tenant_id = %s",
                (tenant_id,),
            )
            deactivated = cur.rowcount > 0
            conn.commit()
            cur.close()
            conn.close()
        except Exception as exc:
            log.error("tenant_deactivate_failed", tenant_id=tenant_id, error=str(exc))

        try:
            import redis as redis_lib  # type: ignore[import]

            r = redis_lib.from_url(_REDIS_URL, decode_responses=True)
            r.delete(f"tenant:{tenant_id}:active")
        except Exception:
            pass

        log.info("tenant_deactivated", tenant_id=tenant_id, success=deactivated)
        return deactivated

    # ── List / Get ─────────────────────────────────────────────────────────────

    def list_tenants(self) -> list[dict[str, Any]]:
        """Return all tenants from PostgreSQL."""
        try:
            import psycopg2  # type: ignore[import]
            import psycopg2.extras

            conn = psycopg2.connect(_POSTGRES_DSN)
            cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
            cur.execute(
                "SELECT tenant_id, display_name, monthly_llm_budget_usd, "
                "active, created_at_ms FROM tenants ORDER BY created_at_ms DESC"
            )
            rows = [dict(r) for r in cur.fetchall()]
            cur.close()
            conn.close()
            return rows
        except Exception as exc:
            log.warning("tenant_list_failed", error=str(exc))
            return []

    def get_tenant(self, tenant_id: str) -> dict[str, Any] | None:
        """Fetch a single tenant record."""
        try:
            import psycopg2  # type: ignore[import]
            import psycopg2.extras

            conn = psycopg2.connect(_POSTGRES_DSN)
            cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
            cur.execute(
                "SELECT tenant_id, display_name, monthly_llm_budget_usd, "
                "active, created_at_ms FROM tenants WHERE tenant_id = %s",
                (tenant_id,),
            )
            row = cur.fetchone()
            cur.close()
            conn.close()
            return dict(row) if row else None
        except Exception as exc:
            log.warning("tenant_get_failed", tenant_id=tenant_id, error=str(exc))
            return None


def _pinecone_namespace(tenant_id: str) -> str:
    """Return the Pinecone namespace for a tenant. 'default' maps to '' for legacy compat."""
    return "" if tenant_id == "default" else tenant_id

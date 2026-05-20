"""
admin — Admin Panel API
=======================

POST /admin/reset  Clear all tenant-scoped data from Redis and Neo4j.
POST /admin/seed   Populate Redis metrics and Neo4j graph with synthetic demo data.

Both endpoints are JWT-protected and strictly scoped to the tenant_id extracted
from the caller's JWT claim — an operator can only modify their own tenant's data.

These endpoints exist exclusively for demo and testing workflows. They are not
intended for production use; gate them with RED_TEAM_ENABLED or a separate flag
in production deployments.
"""

import os
import random
import time
import uuid
from typing import Any

import structlog
from fastapi import APIRouter, Request, status

from api.routers.immunity_score import get_tenant_id

log = structlog.get_logger(__name__)

router = APIRouter(prefix="/admin", tags=["Admin"])

_REDIS_URL: str = os.getenv("REDIS_URL", "redis://localhost:6379/0")
_PG_CONN: str = os.getenv(
    "POSTGRESQL_CONNECTION",
    "postgresql://postgres:postgres@localhost:5432/fraud_immunity",
)
_SCENARIO_WINDOW_S: int = 30 * 86_400  # 30 days

_CANONICAL_ATTACK_TYPES: list[str] = [
    "phishing",
    "money_laundering",
    "account_takeover",
    "credential_stuffing",
    "smurfing",
    "card_fraud",
    "synthetic_identity",
    "first_party_fraud",
    "mule_account",
    "friendly_fraud",
]

# Realistic recall values for demo — three attack types intentionally below 0.90
# threshold so the dashboard shows interesting gap signals.
_DEMO_RECALLS: dict[str, float] = {
    "phishing": 0.94,
    "money_laundering": 0.91,
    "account_takeover": 0.96,
    "credential_stuffing": 0.88,
    "smurfing": 0.93,
    "card_fraud": 0.97,
    "synthetic_identity": 0.92,
    "first_party_fraud": 0.85,
    "mule_account": 0.90,
    "friendly_fraud": 0.78,
}


# ── Helpers ────────────────────────────────────────────────────────────────────

def _redis_client() -> Any:
    try:
        import redis as redis_lib  # type: ignore[import]
        return redis_lib.from_url(_REDIS_URL, decode_responses=True)
    except ImportError:
        raise RuntimeError("redis package not installed. Run: pip install redis")


# ── Reset ──────────────────────────────────────────────────────────────────────

def _reset_redis(tenant_id: str) -> list[str]:
    r = _redis_client()
    patterns = [
        f"immunity_score:{tenant_id}",
        f"fp_rate:{tenant_id}",
        f"fp_total_evaluated:{tenant_id}",
        f"stale_profile_count:{tenant_id}",
        f"scenarios_tested_30d:{tenant_id}",
        f"detection_recall:{tenant_id}:*",
        f"last_scenario_run:{tenant_id}:*",
        f"scenario_count_30d:{tenant_id}:*",
    ]
    deleted = 0
    for pattern in patterns:
        for key in r.scan_iter(pattern):
            r.delete(key)
            deleted += 1
    return [f"Redis: deleted {deleted} key(s) for tenant '{tenant_id}'"]


def _reset_neo4j(tenant_id: str) -> list[str]:
    try:
        from ml.graph.schema import GraphDB  # type: ignore[import]

        driver = GraphDB.get_driver()
        GraphDB.run_query(
            driver,
            "MATCH (n) WHERE n.tenant_id = $tenant_id DETACH DELETE n",
            {"tenant_id": tenant_id},
        )
        driver.close()
        return [f"Neo4j: removed all nodes for tenant '{tenant_id}'"]
    except Exception as exc:
        log.warning("admin_reset_neo4j_skipped", error=str(exc))
        return [f"Neo4j: skipped (unavailable) — {exc}"]


def _reset_postgres(tenant_id: str) -> list[str]:
    try:
        import psycopg2  # type: ignore[import]

        conn = psycopg2.connect(_PG_CONN)
        with conn, conn.cursor() as cur:
            cur.execute(
                "DELETE FROM immunity_score_history WHERE tenant_id = %s",
                (tenant_id,),
            )
            deleted = cur.rowcount
        conn.close()
        return [f"PostgreSQL: deleted {deleted} score history row(s) for tenant '{tenant_id}'"]
    except ImportError:
        return ["PostgreSQL: skipped (psycopg2 not installed)"]
    except Exception as exc:
        log.warning("admin_reset_postgres_skipped", error=str(exc))
        return [f"PostgreSQL: skipped (unavailable) — {exc}"]


# ── Seed ───────────────────────────────────────────────────────────────────────

def _seed_redis(tenant_id: str) -> list[str]:
    r = _redis_client()
    now_ms = int(time.time() * 1000)
    window_s = _SCENARIO_WINDOW_S
    steps: list[str] = []

    pipe = r.pipeline()
    for attack_type, recall in _DEMO_RECALLS.items():
        # Stagger last_scenario_run timestamps across the past 7 days
        last_run_ms = now_ms - random.randint(0, 7 * 86_400_000)
        scenario_count = random.randint(1, 5)

        pipe.setex(f"detection_recall:{tenant_id}:{attack_type}", window_s, str(recall))
        pipe.setex(f"last_scenario_run:{tenant_id}:{attack_type}", window_s, str(last_run_ms))
        pipe.setex(f"scenario_count_30d:{tenant_id}:{attack_type}", window_s, str(scenario_count))
        pipe.sadd(f"scenarios_tested_30d:{tenant_id}", attack_type)

    pipe.expire(f"scenarios_tested_30d:{tenant_id}", window_s)
    pipe.set(f"fp_rate:{tenant_id}", "0.03")
    pipe.set(f"fp_total_evaluated:{tenant_id}", "4820")
    pipe.set(f"stale_profile_count:{tenant_id}", "12")
    pipe.delete(f"immunity_score:{tenant_id}")  # force recompute on next request
    pipe.execute()

    steps.append(f"Redis: seeded recall metrics for {len(_DEMO_RECALLS)} attack types")
    steps.append("Redis: set false-positive rate → 3.0% (4 820 evaluated)")
    steps.append("Redis: set scenario diversity → 10 / 10 attack types tested")
    steps.append("Redis: invalidated score cache (will recompute on next request)")
    return steps


def _seed_neo4j(tenant_id: str) -> list[str]:
    steps: list[str] = []
    try:
        from ml.graph.schema import GraphDB  # type: ignore[import]

        driver = GraphDB.get_driver()
        now_ms = int(time.time() * 1000)

        # 20 synthetic Account nodes
        accounts = [f"tok_{uuid.uuid4().hex[:8]}" for _ in range(20)]
        GraphDB.run_query(
            driver,
            """
            UNWIND $accounts AS acc_id
            MERGE (a:Account {account_id: acc_id})
            SET a.tenant_id    = $tenant_id,
                a.synthetic     = true,
                a.label         = 'unknown',
                a.created_at_ms = $now_ms
            """,
            {"accounts": accounts, "tenant_id": tenant_id, "now_ms": now_ms},
        )
        steps.append(f"Neo4j: created {len(accounts)} Account nodes")

        # 30 SENT_TO transaction edges between random account pairs
        txn_pairs = [
            {
                "src": accounts[i % len(accounts)],
                "dst": accounts[(i + 3) % len(accounts)],
                "txn_id": f"txn_{uuid.uuid4().hex[:12]}",
                "amount": round(random.uniform(10.0, 5000.0), 2),
                "ts": now_ms - random.randint(0, 7 * 86_400_000),
            }
            for i in range(30)
        ]
        GraphDB.run_query(
            driver,
            """
            UNWIND $txns AS t
            MATCH (src:Account {account_id: t.src}),
                  (dst:Account {account_id: t.dst})
            MERGE (src)-[r:SENT_TO {transaction_id: t.txn_id}]->(dst)
            SET r.amount    = t.amount,
                r.timestamp = t.ts,
                r.synthetic  = true,
                r.tenant_id  = $tenant_id
            """,
            {"txns": txn_pairs, "tenant_id": tenant_id},
        )
        steps.append(f"Neo4j: created {len(txn_pairs)} SENT_TO transaction edges")

        # 3 FraudRing clusters
        rings = [
            {
                "ring_id": f"ring-{uuid.uuid4()}",
                "risk_score": 0.92,
                "signals": ["unidirectional_flow", "shared_ip", "synthetic_injection"],
                "members": accounts[0:4],
            },
            {
                "ring_id": f"ring-{uuid.uuid4()}",
                "risk_score": 0.78,
                "signals": ["unidirectional_flow", "shared_device"],
                "members": accounts[4:8],
            },
            {
                "ring_id": f"ring-{uuid.uuid4()}",
                "risk_score": 0.61,
                "signals": ["shared_ip"],
                "members": accounts[8:13],
            },
        ]
        for ring in rings:
            GraphDB.run_query(
                driver,
                """
                MERGE (r:FraudRing {ring_id: $ring_id})
                SET r.risk_score    = $risk_score,
                    r.signals       = $signals,
                    r.synthetic      = true,
                    r.tenant_id     = $tenant_id,
                    r.detected_at_ms = $now_ms
                WITH r
                UNWIND $members AS acc_id
                MATCH (a:Account {account_id: acc_id})
                MERGE (r)-[:INCLUDES]->(a)
                """,
                {
                    "ring_id": ring["ring_id"],
                    "risk_score": ring["risk_score"],
                    "signals": ring["signals"],
                    "tenant_id": tenant_id,
                    "now_ms": now_ms - random.randint(0, 86_400_000),
                    "members": ring["members"],
                },
            )
        steps.append(f"Neo4j: created {len(rings)} FraudRing nodes with INCLUDES edges")
        driver.close()
    except Exception as exc:
        log.warning("admin_seed_neo4j_skipped", error=str(exc))
        steps.append(f"Neo4j: skipped (unavailable) — {exc}")
    return steps


def _seed_postgres(tenant_id: str) -> list[str]:
    """Seed 30 days of Immunity Score history so the trend chart has data."""
    try:
        import psycopg2  # type: ignore[import]

        conn = psycopg2.connect(_PG_CONN)
        now_ms = int(time.time() * 1000)
        rows_inserted = 0

        # Generate a realistic upward trend with some noise
        with conn, conn.cursor() as cur:
            for day in range(29, -1, -1):
                # Score climbs from ~62 to ~84 over the window with noise
                base_score = 62.0 + (29 - day) * 0.73
                score = round(min(100.0, base_score + random.uniform(-3.0, 3.0)), 2)
                detection_coverage = round(min(1.0, 0.55 + (29 - day) * 0.012 + random.uniform(-0.05, 0.05)), 4)
                fp_health = round(min(1.0, 0.92 + random.uniform(-0.04, 0.04)), 4)
                freshness = round(min(1.0, 0.80 + random.uniform(-0.06, 0.06)), 4)
                diversity = round(min(1.0, 0.60 + (29 - day) * 0.013 + random.uniform(-0.03, 0.03)), 4)
                recorded_at_ms = now_ms - day * 86_400_000

                cur.execute(
                    """
                    INSERT INTO immunity_score_history
                      (tenant_id, score, detection_coverage, false_positive_health,
                       model_freshness, scenario_diversity, recorded_at_ms)
                    VALUES (%s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT DO NOTHING
                    """,
                    (
                        tenant_id,
                        score,
                        detection_coverage,
                        fp_health,
                        freshness,
                        diversity,
                        recorded_at_ms,
                    ),
                )
                rows_inserted += cur.rowcount
        conn.close()
        return [f"PostgreSQL: inserted {rows_inserted} score history row(s) (30-day trend)"]
    except ImportError:
        return ["PostgreSQL: skipped (psycopg2 not installed)"]
    except Exception as exc:
        log.warning("admin_seed_postgres_skipped", error=str(exc))
        return [f"PostgreSQL: skipped (unavailable) — {exc}"]


# ── Endpoints ──────────────────────────────────────────────────────────────────

@router.post(
    "/reset",
    status_code=status.HTTP_200_OK,
    summary="Clear tenant database",
    description=(
        "Deletes all data scoped to the authenticated tenant from Redis, Neo4j, "
        "and PostgreSQL score history. Cannot affect other tenants. "
        "Intended for demo resets and test environment teardown."
    ),
)
async def reset_database(request: Request) -> dict:
    tenant_id = get_tenant_id(request)
    log.warning("admin_reset_requested", tenant_id=tenant_id)

    steps: list[str] = []
    errors: list[str] = []

    for label, fn in [
        ("Redis", lambda: _reset_redis(tenant_id)),
        ("Neo4j", lambda: _reset_neo4j(tenant_id)),
        ("PostgreSQL", lambda: _reset_postgres(tenant_id)),
    ]:
        try:
            steps.extend(fn())
        except Exception as exc:
            errors.append(f"{label}: {exc}")

    log.warning("admin_reset_completed", tenant_id=tenant_id, steps=steps, errors=errors)
    return {"tenant_id": tenant_id, "steps": steps, "errors": errors, "ok": len(errors) == 0}


@router.post(
    "/seed",
    status_code=status.HTTP_200_OK,
    summary="Seed demo data",
    description=(
        "Populates Redis detection metrics, Neo4j fraud graph nodes, and PostgreSQL "
        "score history with realistic synthetic data for the authenticated tenant. "
        "Safe to call repeatedly — Neo4j uses MERGE, PostgreSQL uses ON CONFLICT DO NOTHING."
    ),
)
async def seed_database(request: Request) -> dict:
    tenant_id = get_tenant_id(request)
    log.info("admin_seed_requested", tenant_id=tenant_id)

    steps: list[str] = []
    errors: list[str] = []

    for label, fn in [
        ("Redis", lambda: _seed_redis(tenant_id)),
        ("Neo4j", lambda: _seed_neo4j(tenant_id)),
        ("PostgreSQL", lambda: _seed_postgres(tenant_id)),
    ]:
        try:
            steps.extend(fn())
        except Exception as exc:
            errors.append(f"{label}: {exc}")

    log.info("admin_seed_completed", tenant_id=tenant_id, steps=steps, errors=errors)
    return {"tenant_id": tenant_id, "steps": steps, "errors": errors, "ok": len(errors) == 0}

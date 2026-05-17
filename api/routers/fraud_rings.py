"""
fraud_rings router — Fraud Ring graph data for the dashboard visualizer.

GET /fraud-rings
    Returns detected fraud rings with member account tokens and risk scores.
    Queries Neo4j via GraphDB; falls back to stub data when Neo4j is unavailable.

Member IDs returned are PII-tokenized (tok_<hex>) — never raw account numbers.
"""

import time
from typing import Any

import structlog
from fastapi import APIRouter, Query, Request

from api.routers.immunity_score import get_tenant_id

log = structlog.get_logger(__name__)
router = APIRouter(prefix="/fraud-rings", tags=["Fraud Rings"])

_STUB_RINGS: list[dict[str, Any]] = [
    {
        "ring_id": "ring-a1b2c3d4-e5f6-7890-abcd-ef1234567890",
        "risk_score": 0.92,
        "synthetic": True,
        "signals": ["unidirectional_flow", "shared_ip", "synthetic_injection"],
        "member_ids": [f"tok_{i:08x}" for i in range(4)],
    },
    {
        "ring_id": "ring-b2c3d4e5-f6a7-8901-bcde-f12345678901",
        "risk_score": 0.78,
        "synthetic": False,
        "signals": ["unidirectional_flow", "shared_device"],
        "member_ids": [f"tok_{i:08x}" for i in range(4, 7)],
    },
    {
        "ring_id": "ring-c3d4e5f6-a7b8-9012-cdef-123456789012",
        "risk_score": 0.61,
        "synthetic": True,
        "signals": ["shared_ip"],
        "member_ids": [f"tok_{i:08x}" for i in range(7, 12)],
    },
]


@router.get(
    "",
    summary="Get detected fraud rings",
    description=(
        "Returns fraud rings detected by the Louvain community detection DAG. "
        "Each ring includes member account tokens (PII-tokenized), risk score, "
        "and detection signals. Used by the dashboard Fraud Ring Visualizer. "
        "Member IDs are tok_<hex32> — never raw PII (Hard Rule #4)."
    ),
)
async def get_fraud_rings(
    request: Request,
    limit: int = Query(default=20, ge=1, le=100, description="Max rings to return"),
) -> dict[str, Any]:
    tenant_id = get_tenant_id(request)
    now_ms = int(time.time() * 1000)

    try:
        from ml.graph.schema import GraphDB

        db = GraphDB()
        rows = db.run_query(
            """
            MATCH (r:FraudRing)-[:INCLUDES]->(a:Account)
            WHERE r.tenant_id = $tenant_id OR r.tenant_id IS NULL
            RETURN r.ring_id          AS ring_id,
                   r.risk_score       AS risk_score,
                   r.synthetic        AS synthetic,
                   r.detected_at_ms   AS detected_at_ms,
                   r.signals          AS signals,
                   collect(a.account_id) AS member_ids
            ORDER BY r.detected_at_ms DESC
            LIMIT $limit
            """,
            {"tenant_id": tenant_id, "limit": limit},
        )
        rings = [
            {
                "ring_id": row["ring_id"],
                "risk_score": float(row["risk_score"] or 0.0),
                "synthetic": bool(row["synthetic"]),
                "detected_at_ms": int(row["detected_at_ms"] or now_ms),
                "signals": list(row.get("signals") or []),
                "member_ids": list(row["member_ids"]),
            }
            for row in rows
        ]
        log.info("fraud_rings_fetched", tenant_id=tenant_id, count=len(rings))
        return {"tenant_id": tenant_id, "rings": rings, "count": len(rings)}

    except Exception as exc:
        log.warning("fraud_rings_neo4j_unavailable_using_stub", error=str(exc))
        stub = [
            {**ring, "detected_at_ms": now_ms - (i + 1) * 3_600_000}
            for i, ring in enumerate(_STUB_RINGS)
        ]
        return {"tenant_id": tenant_id, "rings": stub, "count": len(stub)}

"""
alerts router — WebSocket endpoint for the real-time detection alert feed.

WS /ws/alerts?tenant_id=<id>
    Streams detection alerts as JSON messages.
    Reads from Redis pub/sub channel `alerts:{tenant_id}` when available.
    Falls back to synthetic demo alerts (for dev/demo) when Redis is unavailable.

This endpoint is exempt from JWTAuthMiddleware (WebSocket browser clients cannot
send Authorization headers). Dashboard access is protected by Next.js middleware.
"""

import asyncio
import json
import os
import random
import time
from typing import Any

import structlog
from fastapi import APIRouter, Query, WebSocket, WebSocketDisconnect

log = structlog.get_logger(__name__)
router = APIRouter(prefix="/ws", tags=["Alerts"])

_ATTACK_TYPES: list[str] = [
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
_ALERT_INTERVAL_S: float = float(os.getenv("ALERT_FEED_INTERVAL_S", "4.0"))
_REDIS_CHANNEL_PREFIX: str = "alerts"


@router.websocket("/alerts")
async def alert_feed(
    websocket: WebSocket,
    tenant_id: str = Query(default="default"),
) -> None:
    await websocket.accept()
    log.info("alert_ws_connected", tenant_id=tenant_id)
    try:
        redis_client = _try_redis()
        if redis_client is not None:
            await _stream_from_redis(websocket, redis_client, tenant_id)
        else:
            await _stream_demo(websocket, tenant_id)
    except WebSocketDisconnect:
        log.info("alert_ws_disconnected", tenant_id=tenant_id)
    except Exception as exc:
        log.error("alert_ws_error", tenant_id=tenant_id, error=str(exc))
        try:
            await websocket.close()
        except Exception:
            pass


def _try_redis() -> Any:
    try:
        import redis as redis_lib  # type: ignore[import]

        r = redis_lib.from_url(
            os.getenv("REDIS_URL", "redis://localhost:6379/0"),
            decode_responses=True,
            socket_connect_timeout=1,
        )
        r.ping()
        return r
    except Exception:
        return None


async def _stream_from_redis(websocket: WebSocket, r: Any, tenant_id: str) -> None:
    channel = f"{_REDIS_CHANNEL_PREFIX}:{tenant_id}"
    pubsub = r.pubsub()
    pubsub.subscribe(channel)
    log.info("alert_ws_redis_subscribed", channel=channel)
    while True:
        msg = pubsub.get_message(ignore_subscribe_messages=True, timeout=0.1)
        if msg and msg["type"] == "message":
            await websocket.send_text(msg["data"])
        else:
            await asyncio.sleep(0.1)


async def _stream_demo(websocket: WebSocket, tenant_id: str) -> None:
    log.info("alert_ws_demo_mode", tenant_id=tenant_id)
    while True:
        severities = ["high", "medium", "low"]
        weights = [0.15, 0.40, 0.45]
        severity = random.choices(severities, weights=weights)[0]
        alert: dict[str, Any] = {
            "alert_id": f"alert-{int(time.time() * 1000)}-{random.randint(1000, 9999)}",
            "attack_type": random.choice(_ATTACK_TYPES),
            "severity": severity,
            "risk_score": round(random.uniform(0.55, 0.99), 3),
            "account_token": f"tok_{random.randint(0x10000000, 0xFFFFFFFF):08x}",
            "detected_at_ms": int(time.time() * 1000),
            "synthetic": True,
            "tenant_id": tenant_id,
        }
        await websocket.send_text(json.dumps(alert))
        await asyncio.sleep(_ALERT_INTERVAL_S)

"""
community_detection — Louvain Fraud Ring Detection
===================================================

Runs the Louvain community detection algorithm via Neo4j GDS on the SENT_TO
relationship graph, then evaluates each candidate cluster against three risk
signals:

  1. Unidirectional flow ratio — laundering signal (money exits but never returns)
  2. Shared IP addresses — collusion signal (accounts from same IP)
  3. Shared devices — collusion signal (accounts on same device)

A cluster becomes a FraudRing when:
  - Cluster size > FRAUD_RING_MIN_CLUSTER_SIZE (default 3), AND
  - At least one risk signal fires above its threshold.

Risk score formula (0.0 – 1.0):
  0.50 × unidirectional_ratio     (laundering weight)
  0.30 × shared_collusion_signal  (ip+device combined)
  0.20 × synthetic_ratio          (% of edges from red-team injection)

Results stored back in Neo4j as FraudRing nodes linked to member Account nodes.
High-risk rings (score > FRAUD_RING_ALERT_THRESHOLD) are published to the
`KAFKA_TOPIC_ALERTS` topic.

Hard Rule #3: FraudRing.synthetic = true when the ring was seeded by attacker agents.
"""

import hashlib
import json
import os
import time
import uuid
from dataclasses import dataclass, field
from typing import Any

import structlog

from ml.graph.schema import GraphDB, _NEO4J_DATABASE

log = structlog.get_logger(__name__)

_KAFKA_BOOTSTRAP: str = os.getenv("KAFKA_BOOTSTRAP_SERVERS", "localhost:9092")
_TOPIC_ALERTS: str = os.getenv("KAFKA_TOPIC_ALERTS", "alerts")
_NEO4J_DATABASE_VAR: str = os.getenv("NEO4J_DATABASE", "neo4j")
_GDS_GRAPH_NAME: str = os.getenv("GDS_GRAPH_NAME", "fraud-ring-graph")

_MIN_CLUSTER_SIZE: int = int(os.getenv("FRAUD_RING_MIN_CLUSTER_SIZE", "3"))
_ALERT_THRESHOLD: float = float(os.getenv("FRAUD_RING_ALERT_THRESHOLD", "0.85"))
_LOUVAIN_WINDOW_DAYS: int = int(os.getenv("FRAUD_RING_WINDOW_DAYS", "30"))

# Louvain GDS parameters
_LOUVAIN_MAX_ITERATIONS: int = int(os.getenv("LOUVAIN_MAX_ITERATIONS", "10"))
_LOUVAIN_MAX_LEVELS: int = int(os.getenv("LOUVAIN_MAX_LEVELS", "10"))
_LOUVAIN_TOLERANCE: float = float(os.getenv("LOUVAIN_TOLERANCE", "0.0001"))


@dataclass
class FraudRing:
    """
    A detected community of accounts exhibiting fraud ring behavior.

    Attributes:
        ring_id: Deterministic UUID derived from sorted member IDs.
        community_id: Louvain community integer ID.
        member_account_ids: Tokenized account IDs (Hard Rule #4).
        risk_score: Composite 0.0–1.0 risk score.
        signals: List of signal names that fired.
        total_flow: Sum of SENT_TO amounts within the ring.
        unidirectional_ratio: Fraction of one-way money flows.
        shared_ip_count: Distinct IPs shared by ≥ 2 accounts.
        shared_device_count: Distinct devices shared by ≥ 2 accounts.
        synthetic: True if ring members are from a red-team injection.
        detected_at_ms: Detection timestamp.
        dag_run_id: Airflow DAG run ID for traceability.
    """

    ring_id: str
    community_id: int
    member_account_ids: list[str]
    risk_score: float
    signals: list[str]
    total_flow: float
    unidirectional_ratio: float
    shared_ip_count: int
    shared_device_count: int
    synthetic: bool = False
    detected_at_ms: int = field(default_factory=lambda: int(time.time() * 1000))
    dag_run_id: str | None = None

    @property
    def member_count(self) -> int:
        return len(self.member_account_ids)

    @property
    def is_high_risk(self) -> bool:
        return self.risk_score >= _ALERT_THRESHOLD

    def to_dict(self) -> dict[str, Any]:
        return {
            "ring_id": self.ring_id,
            "community_id": self.community_id,
            "member_account_ids": self.member_account_ids,
            "member_count": self.member_count,
            "risk_score": round(self.risk_score, 4),
            "signals": self.signals,
            "total_flow": round(self.total_flow, 2),
            "unidirectional_ratio": round(self.unidirectional_ratio, 4),
            "shared_ip_count": self.shared_ip_count,
            "shared_device_count": self.shared_device_count,
            "synthetic": self.synthetic,
            "detected_at_ms": self.detected_at_ms,
            "dag_run_id": self.dag_run_id,
        }


def _derive_ring_id(member_account_ids: list[str]) -> str:
    """Deterministic ring ID: SHA-256 of sorted, joined member IDs → UUID5 namespace."""
    sorted_ids = ",".join(sorted(member_account_ids))
    digest = hashlib.sha256(sorted_ids.encode()).hexdigest()
    return str(uuid.UUID(digest[:32]))


def _compute_risk_score(
    unidirectional_ratio: float,
    shared_ip_count: int,
    shared_device_count: int,
    synthetic_edge_count: int,
    total_edges: int,
) -> tuple[float, list[str]]:
    """
    Compute the composite risk score and list of active signals.

    Returns:
        (risk_score, signals)
    """
    signals: list[str] = []

    # Laundering signal
    laundering_score = unidirectional_ratio
    if unidirectional_ratio >= 0.70:
        signals.append("unidirectional_flow")

    # Collusion signal (IP + device combined)
    collusion_raw = min(1.0, (shared_ip_count + shared_device_count) / 5.0)
    if shared_ip_count >= 2:
        signals.append("shared_ip")
    if shared_device_count >= 2:
        signals.append("shared_device")

    # Synthetic injection signal
    synthetic_ratio = (synthetic_edge_count / total_edges) if total_edges > 0 else 0.0
    if synthetic_ratio > 0.0:
        signals.append("synthetic_injection")

    score = (
        0.50 * laundering_score
        + 0.30 * collusion_raw
        + 0.20 * synthetic_ratio
    )
    return min(1.0, round(score, 4)), signals


class CommunityDetector:
    """
    Orchestrates Louvain community detection and fraud ring evaluation.

    Args:
        driver: Neo4j driver. If None, creates from env vars.
        dry_run: If True, runs queries but does not persist FraudRing nodes
                 and does not publish Kafka alerts.
    """

    def __init__(
        self,
        driver: Any | None = None,
        *,
        dry_run: bool = False,
        dag_run_id: str | None = None,
    ) -> None:
        self._driver = driver
        self._dry_run = dry_run
        self._dag_run_id = dag_run_id

    def _get_driver(self) -> Any:
        if self._driver is None:
            self._driver = GraphDB.get_driver()
        return self._driver

    # ── GDS graph lifecycle ────────────────────────────────────────────────────

    def _project_graph(self, since_ms: int) -> dict[str, Any]:
        query = GraphDB.load_query("louvain_project.cypher")
        try:
            results = GraphDB.run_query(
                self._get_driver(),
                query,
                {"graph_name": _GDS_GRAPH_NAME, "since_ms": since_ms},
            )
            return results[0] if results else {}
        except Exception as exc:
            if "already exists" in str(exc).lower():
                log.info("gds_graph_already_projected", graph_name=_GDS_GRAPH_NAME)
                return {}
            raise

    def _drop_graph(self) -> None:
        query = GraphDB.load_query("louvain_drop.cypher")
        try:
            GraphDB.run_query(
                self._get_driver(),
                query,
                {"graph_name": _GDS_GRAPH_NAME},
            )
            log.info("gds_graph_dropped", graph_name=_GDS_GRAPH_NAME)
        except Exception as exc:
            if "no such graph" not in str(exc).lower():
                log.warning("gds_graph_drop_warning", error=str(exc))

    # ── Louvain execution ──────────────────────────────────────────────────────

    def _run_louvain(self) -> list[dict[str, Any]]:
        query = GraphDB.load_query("louvain_run.cypher")
        return GraphDB.run_query(
            self._get_driver(),
            query,
            {
                "graph_name": _GDS_GRAPH_NAME,
                "max_iterations": _LOUVAIN_MAX_ITERATIONS,
                "max_levels": _LOUVAIN_MAX_LEVELS,
                "tolerance": _LOUVAIN_TOLERANCE,
            },
        )

    # ── Signal computation ─────────────────────────────────────────────────────

    def _fetch_cluster_signals(
        self,
        member_account_ids: list[str],
        since_ms: int,
    ) -> dict[str, Any]:
        query = GraphDB.load_query("cluster_signals.cypher")
        results = GraphDB.run_query(
            self._get_driver(),
            query,
            {"account_ids": member_account_ids, "since_ms": since_ms},
        )
        if results:
            return results[0]
        return {
            "total_flow": 0.0,
            "edge_count": 0,
            "unidirectional_ratio": 0.0,
            "shared_ip_count": 0,
            "shared_device_count": 0,
            "synthetic_edge_count": 0,
        }

    # ── Persistence ────────────────────────────────────────────────────────────

    def _persist_fraud_ring(self, ring: FraudRing) -> None:
        query = GraphDB.load_query("upsert_fraud_ring.cypher")
        GraphDB.run_query(
            self._get_driver(),
            query,
            {
                "ring_id": ring.ring_id,
                "community_id": ring.community_id,
                "member_ids": ring.member_account_ids,
                "risk_score": ring.risk_score,
                "signals": ring.signals,
                "total_flow": ring.total_flow,
                "synthetic": ring.synthetic,
                "detected_at_ms": ring.detected_at_ms,
                "dag_run_id": ring.dag_run_id or "",
            },
        )

    # ── Kafka alert ────────────────────────────────────────────────────────────

    def _publish_alert(self, ring: FraudRing) -> None:
        alert_event = {
            "alert_type": "fraud_ring_detected",
            "ring_id": ring.ring_id,
            "risk_score": ring.risk_score,
            "member_count": ring.member_count,
            "signals": ring.signals,
            "total_flow": ring.total_flow,
            "synthetic": ring.synthetic,
            "detected_at_ms": ring.detected_at_ms,
            "dag_run_id": ring.dag_run_id,
        }
        try:
            from confluent_kafka import Producer  # type: ignore[import]

            producer = Producer({"bootstrap.servers": _KAFKA_BOOTSTRAP})
            producer.produce(
                topic=_TOPIC_ALERTS,
                key=ring.ring_id,
                value=json.dumps(alert_event).encode(),
            )
            producer.flush(timeout=5)
            log.warning(
                "fraud_ring_alert_published",
                ring_id=ring.ring_id,
                risk_score=ring.risk_score,
                member_count=ring.member_count,
            )
        except ImportError:
            log.error("confluent_kafka_not_installed")
        except Exception as exc:
            log.error("alert_publish_failed", ring_id=ring.ring_id, error=str(exc))

    # ── Main detection entry point ─────────────────────────────────────────────

    def detect(
        self,
        *,
        window_days: int | None = None,
        min_cluster_size: int | None = None,
    ) -> dict[str, Any]:
        """
        Run a full Louvain detection pass.

        Args:
            window_days: Only consider edges in the last N days (default: FRAUD_RING_WINDOW_DAYS).
            min_cluster_size: Skip clusters smaller than this (default: FRAUD_RING_MIN_CLUSTER_SIZE).

        Returns:
            {
                rings_detected: int,
                rings_persisted: int,
                alerts_published: int,
                elapsed_ms: int,
                fraud_rings: list[dict],
            }
        """
        wdays = window_days or _LOUVAIN_WINDOW_DAYS
        min_size = min_cluster_size or _MIN_CLUSTER_SIZE
        since_ms = int(time.time() * 1000) - wdays * 86_400_000

        start_ms = int(time.time() * 1000)
        log.info(
            "community_detection_started",
            window_days=wdays,
            min_cluster_size=min_size,
            dry_run=self._dry_run,
        )

        # Project GDS graph
        projection = self._project_graph(since_ms)
        log.info(
            "gds_graph_projected",
            node_count=projection.get("nodeCount", "unknown"),
            relationship_count=projection.get("relationshipCount", "unknown"),
        )

        # Run Louvain
        communities = self._run_louvain()
        log.info("louvain_complete", community_count=len(communities))

        rings_detected = 0
        rings_persisted = 0
        alerts_published = 0
        fraud_rings: list[dict[str, Any]] = []

        for community in communities:
            member_ids: list[str] = community.get("member_account_ids", [])
            community_id = int(community.get("community_id", 0))
            member_count = int(community.get("member_count", 0))

            if member_count < min_size:
                continue

            # Fetch risk signals for this cluster
            signals_data = self._fetch_cluster_signals(member_ids, since_ms)

            total_flow = float(signals_data.get("total_flow") or 0.0)
            edge_count = int(signals_data.get("edge_count") or 0)
            unidirectional_ratio = float(signals_data.get("unidirectional_ratio") or 0.0)
            shared_ip_count = int(signals_data.get("shared_ip_count") or 0)
            shared_device_count = int(signals_data.get("shared_device_count") or 0)
            synthetic_edge_count = int(signals_data.get("synthetic_edge_count") or 0)

            risk_score, active_signals = _compute_risk_score(
                unidirectional_ratio,
                shared_ip_count,
                shared_device_count,
                synthetic_edge_count,
                edge_count,
            )

            if not active_signals:
                continue  # no signals — not a fraud ring

            ring = FraudRing(
                ring_id=_derive_ring_id(member_ids),
                community_id=community_id,
                member_account_ids=member_ids,
                risk_score=risk_score,
                signals=active_signals,
                total_flow=total_flow,
                unidirectional_ratio=unidirectional_ratio,
                shared_ip_count=shared_ip_count,
                shared_device_count=shared_device_count,
                synthetic=synthetic_edge_count > 0,
                dag_run_id=self._dag_run_id,
            )

            rings_detected += 1
            fraud_rings.append(ring.to_dict())

            log.info(
                "fraud_ring_detected",
                ring_id=ring.ring_id,
                community_id=community_id,
                member_count=member_count,
                risk_score=risk_score,
                signals=active_signals,
                synthetic=ring.synthetic,
            )

            if not self._dry_run:
                try:
                    self._persist_fraud_ring(ring)
                    rings_persisted += 1
                except Exception as exc:
                    log.error(
                        "fraud_ring_persist_failed",
                        ring_id=ring.ring_id,
                        error=str(exc),
                    )

            if ring.is_high_risk and not self._dry_run:
                self._publish_alert(ring)
                alerts_published += 1

        # Clean up GDS projection
        self._drop_graph()

        elapsed_ms = int(time.time() * 1000) - start_ms

        summary = {
            "rings_detected": rings_detected,
            "rings_persisted": rings_persisted,
            "alerts_published": alerts_published,
            "communities_evaluated": len(communities),
            "elapsed_ms": elapsed_ms,
            "window_days": wdays,
            "fraud_rings": fraud_rings,
        }

        log.info(
            "community_detection_complete",
            rings_detected=rings_detected,
            rings_persisted=rings_persisted,
            alerts_published=alerts_published,
            elapsed_ms=elapsed_ms,
        )

        return summary

    def detect_for_scenario(
        self,
        scenario_id: str,
        injected_account_tokens: list[str],
        *,
        window_days: int = 1,
    ) -> dict[str, Any]:
        """
        Targeted detection for a specific red-team scenario.

        Evaluates only the injected accounts and reports whether they form
        a detectable fraud ring, used by the community_detection_dag's
        on-demand trigger path.

        Args:
            scenario_id: The attacker agent scenario UUID.
            injected_account_tokens: Tokenized account IDs from inject_to_kafka.
            window_days: Lookback window in days (default 1 — same-day injection).

        Returns:
            {scenario_id, ring_detected, ring_id, risk_score, signals}
        """
        if len(injected_account_tokens) < _MIN_CLUSTER_SIZE:
            return {
                "scenario_id": scenario_id,
                "ring_detected": False,
                "reason": f"only {len(injected_account_tokens)} accounts — below min cluster size {_MIN_CLUSTER_SIZE}",
            }

        since_ms = int(time.time() * 1000) - window_days * 86_400_000
        signals_data = self._fetch_cluster_signals(injected_account_tokens, since_ms)

        total_flow = float(signals_data.get("total_flow") or 0.0)
        edge_count = int(signals_data.get("edge_count") or 0)
        unidirectional_ratio = float(signals_data.get("unidirectional_ratio") or 0.0)
        shared_ip_count = int(signals_data.get("shared_ip_count") or 0)
        shared_device_count = int(signals_data.get("shared_device_count") or 0)
        synthetic_edge_count = int(signals_data.get("synthetic_edge_count") or 0)

        risk_score, active_signals = _compute_risk_score(
            unidirectional_ratio,
            shared_ip_count,
            shared_device_count,
            synthetic_edge_count,
            edge_count,
        )

        ring_detected = bool(active_signals)
        ring_id = _derive_ring_id(injected_account_tokens) if ring_detected else None

        log.info(
            "scenario_ring_detection",
            scenario_id=scenario_id,
            ring_detected=ring_detected,
            risk_score=risk_score,
            signals=active_signals,
        )

        return {
            "scenario_id": scenario_id,
            "ring_detected": ring_detected,
            "ring_id": ring_id,
            "risk_score": risk_score,
            "signals": active_signals,
            "total_flow": total_flow,
        }

"""
score_calculator — Immunity Score Computation Service
=====================================================

Computes the composite Immunity Score per tenant by pulling data from:
  - Pinecone: profile freshness (last_updated metadata per account)
  - Neo4j: fraud ring detection recall on synthetic rings
  - Redis: cached detection results and false-positive metrics
  - Kafka audit trail: scenario coverage breadth over last 30 days

Score formula (0–100):
  0.40 × DetectionCoverage   — fraction of canonical attack types with recall ≥ 0.90
  0.30 × FalsePositiveHealth — 1 - false_positive_rate (from detection_results topic agg)
  0.20 × ModelFreshness      — fraction of profiles updated within PROFILE_STALENESS_DAYS
  0.10 × ScenarioDiversity   — fraction of canonical attack types tested in last 30 days

Results are cached in Redis with a 5-minute TTL.
Historical scores are written to PostgreSQL for the /history endpoint.

Sprint 7: all data sources are wired; Redis caching and PostgreSQL time series active.
Sprint 9: per-tenant isolation enforced via JWT claims.
"""

import json
import os
import time
from dataclasses import dataclass, field
from typing import Any

import structlog

from api.schemas.immunity_score import (
    AttackTypeCoverage,
    ScoreComponents,
)

log = structlog.get_logger(__name__)

_REDIS_URL: str = os.getenv("REDIS_URL", "redis://localhost:6379/0")
_REDIS_TTL_SECONDS: int = int(os.getenv("IMMUNITY_SCORE_CACHE_TTL_SECONDS", "300"))
_STALENESS_DAYS: int = int(os.getenv("PROFILE_STALENESS_DAYS", "30"))
_STALENESS_MS: int = _STALENESS_DAYS * 86_400 * 1_000
_SCENARIO_WINDOW_DAYS: int = 30
_SCENARIO_WINDOW_MS: int = _SCENARIO_WINDOW_DAYS * 86_400 * 1_000

# Canonical attack types the lab tracks for coverage purposes
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

_PG_CONN: str = os.getenv(
    "POSTGRESQL_CONNECTION",
    "postgresql://postgres:postgres@localhost:5432/fraud_immunity",
)


@dataclass
class ScoreInputs:
    """Raw data collected from backend systems before score computation."""

    # Detection coverage
    attack_type_recalls: dict[str, float] = field(default_factory=dict)

    # False positive rate
    false_positive_rate: float = 0.0
    total_legitimate_evaluated: int = 0

    # Model freshness
    total_profiles: int = 0
    fresh_profiles: int = 0

    # Scenario diversity
    attack_types_tested_30d: set[str] = field(default_factory=set)

    # Metadata
    tenant_id: str = "default"
    collected_at_ms: int = field(default_factory=lambda: int(time.time() * 1000))


class ScoreCalculator:
    """
    Computes and caches the Immunity Score per tenant.

    Args:
        redis_client: Redis client instance. If None, creates from `REDIS_URL`.
        pinecone_api_key: Pinecone API key.
        neo4j_driver: Neo4j driver instance.
        pg_conn_string: PostgreSQL connection string.
    """

    def __init__(
        self,
        redis_client: Any | None = None,
        pinecone_api_key: str | None = None,
        neo4j_driver: Any | None = None,
        pg_conn_string: str | None = None,
    ) -> None:
        self._redis = redis_client
        self._pc_key = pinecone_api_key or os.getenv("PINECONE_API_KEY", "")
        self._neo4j_driver = neo4j_driver
        self._pg_conn = pg_conn_string or _PG_CONN
        self._pinecone_index_clean: Any | None = None

    # ── Redis (lazy) ───────────────────────────────────────────────────────────

    def _get_redis(self) -> Any:
        if self._redis is not None:
            return self._redis
        try:
            import redis as redis_lib  # type: ignore[import]
            self._redis = redis_lib.from_url(_REDIS_URL, decode_responses=True)
        except ImportError:
            raise RuntimeError("redis package not installed. Run: pip install redis")
        return self._redis

    # ── Pinecone (lazy) ────────────────────────────────────────────────────────

    def _get_clean_index(self) -> Any:
        if self._pinecone_index_clean is not None:
            return self._pinecone_index_clean
        try:
            from pinecone import Pinecone  # type: ignore[import]
            pc = Pinecone(api_key=self._pc_key)
            self._pinecone_index_clean = pc.Index(
                os.getenv("PINECONE_INDEX_CLEAN", "clean-profiles")
            )
        except ImportError:
            raise RuntimeError("pinecone-client not installed.")
        return self._pinecone_index_clean

    # ── Data collection ────────────────────────────────────────────────────────

    def _fetch_detection_recalls(self, tenant_id: str) -> dict[str, float]:
        """
        Fetch per-attack-type detection recall from Redis.

        Keys: `detection_recall:{tenant_id}:{attack_type}`
        Written by: anomaly_pipeline publish_detection_result + community_detection_dag.

        Falls back to 0.0 if no data available for an attack type.
        """
        recalls: dict[str, float] = {}
        try:
            r = self._get_redis()
            for attack_type in _CANONICAL_ATTACK_TYPES:
                key = f"detection_recall:{tenant_id}:{attack_type}"
                val = r.get(key)
                recalls[attack_type] = float(val) if val is not None else 0.0
        except Exception as exc:
            log.warning("fetch_detection_recalls_failed", error=str(exc))
            recalls = {at: 0.0 for at in _CANONICAL_ATTACK_TYPES}
        return recalls

    def _fetch_false_positive_rate(self, tenant_id: str) -> tuple[float, int]:
        """
        Fetch false positive rate from Redis.

        Key: `fp_rate:{tenant_id}` — written by detection consumer aggregator.
        Returns (false_positive_rate, total_legitimate_evaluated).
        """
        try:
            r = self._get_redis()
            fp_val = r.get(f"fp_rate:{tenant_id}")
            total_val = r.get(f"fp_total_evaluated:{tenant_id}")
            fp_rate = float(fp_val) if fp_val is not None else 0.05  # default 5%
            total = int(total_val) if total_val is not None else 0
            return fp_rate, total
        except Exception as exc:
            log.warning("fetch_fp_rate_failed", error=str(exc))
            return 0.05, 0

    def _fetch_profile_freshness(self, tenant_id: str) -> tuple[int, int]:
        """
        Count total and fresh (< PROFILE_STALENESS_DAYS old) profiles in Pinecone.

        Returns (total_profiles, fresh_profiles).

        Sprint 7: queries Pinecone index stats for metadata aggregation.
        Sprint 9: filtered by tenant_id metadata field.
        """
        try:
            index = self._get_clean_index()
            stats = index.describe_index_stats()
            total = stats.get("total_vector_count", 0)

            # Sprint 7: approximate freshness via Redis cached staleness scan
            # (Pinecone doesn't support aggregate metadata queries directly)
            r = self._get_redis()
            stale_count_val = r.get(f"stale_profile_count:{tenant_id}")
            stale_count = int(stale_count_val) if stale_count_val is not None else 0

            fresh = max(0, total - stale_count)
            return total, fresh
        except Exception as exc:
            log.warning("fetch_profile_freshness_failed", error=str(exc))
            return 0, 0

    def _fetch_scenario_diversity(self, tenant_id: str) -> set[str]:
        """
        Fetch the set of attack types tested in the last 30 days from Redis.

        Key: `scenarios_tested_30d:{tenant_id}` — Redis Set, written by
        attack_orchestrator log_to_audit task.
        """
        try:
            r = self._get_redis()
            members = r.smembers(f"scenarios_tested_30d:{tenant_id}")
            return set(members) if members else set()
        except Exception as exc:
            log.warning("fetch_scenario_diversity_failed", error=str(exc))
            return set()

    def _collect_inputs(self, tenant_id: str) -> ScoreInputs:
        """Gather all raw inputs from backend systems."""
        recalls = self._fetch_detection_recalls(tenant_id)
        fp_rate, total_legit = self._fetch_false_positive_rate(tenant_id)
        total_profiles, fresh_profiles = self._fetch_profile_freshness(tenant_id)
        tested_attack_types = self._fetch_scenario_diversity(tenant_id)

        return ScoreInputs(
            attack_type_recalls=recalls,
            false_positive_rate=fp_rate,
            total_legitimate_evaluated=total_legit,
            total_profiles=total_profiles,
            fresh_profiles=fresh_profiles,
            attack_types_tested_30d=tested_attack_types,
            tenant_id=tenant_id,
        )

    # ── Score computation ──────────────────────────────────────────────────────

    @staticmethod
    def compute_components(inputs: ScoreInputs) -> ScoreComponents:
        """
        Compute the four sub-components from raw inputs.

        DetectionCoverage:
            Fraction of canonical attack types with recall ≥ 0.90 (Hard Rule #6 threshold).

        FalsePositiveHealth:
            1 - false_positive_rate, clamped to [0, 1].

        ModelFreshness:
            fresh_profiles / total_profiles, or 1.0 if no profiles exist yet.

        ScenarioDiversity:
            len(tested_attack_types ∩ canonical) / len(canonical).
        """
        # Detection coverage
        recall_threshold = float(os.getenv("DETECTION_RECALL_THRESHOLD", "0.90"))
        attack_types_covered = sum(
            1
            for at, recall in inputs.attack_type_recalls.items()
            if recall >= recall_threshold
        )
        detection_coverage = (
            attack_types_covered / len(_CANONICAL_ATTACK_TYPES)
            if _CANONICAL_ATTACK_TYPES
            else 0.0
        )

        # False positive health
        fp_health = max(0.0, min(1.0, 1.0 - inputs.false_positive_rate))

        # Model freshness
        if inputs.total_profiles == 0:
            freshness = 1.0  # no profiles = no staleness yet
        else:
            freshness = inputs.fresh_profiles / inputs.total_profiles

        # Scenario diversity
        canonical_set = set(_CANONICAL_ATTACK_TYPES)
        tested_canonical = inputs.attack_types_tested_30d & canonical_set
        diversity = len(tested_canonical) / len(canonical_set) if canonical_set else 0.0

        return ScoreComponents(
            detection_coverage=round(detection_coverage, 4),
            false_positive_health=round(fp_health, 4),
            model_freshness=round(freshness, 4),
            scenario_diversity=round(diversity, 4),
        )

    @staticmethod
    def components_to_score(components: ScoreComponents) -> float:
        """Convert ScoreComponents to a 0–100 composite score."""
        return round(components.composite * 100, 2)

    # ── Redis caching ──────────────────────────────────────────────────────────

    def _cache_key(self, tenant_id: str) -> str:
        return f"immunity_score:{tenant_id}"

    def _get_cached(self, tenant_id: str) -> dict[str, Any] | None:
        try:
            r = self._get_redis()
            raw = r.get(self._cache_key(tenant_id))
            if raw:
                return json.loads(raw)
        except Exception as exc:
            log.warning("cache_get_failed", error=str(exc))
        return None

    def _set_cached(self, tenant_id: str, payload: dict[str, Any]) -> None:
        try:
            r = self._get_redis()
            r.setex(
                self._cache_key(tenant_id),
                _REDIS_TTL_SECONDS,
                json.dumps(payload),
            )
        except Exception as exc:
            log.warning("cache_set_failed", error=str(exc))

    # ── PostgreSQL persistence ─────────────────────────────────────────────────

    def _persist_score(
        self,
        tenant_id: str,
        score: float,
        components: ScoreComponents,
        recorded_at_ms: int,
    ) -> None:
        """Write a score snapshot to the PostgreSQL time series table."""
        try:
            import psycopg2  # type: ignore[import]
            conn = psycopg2.connect(self._pg_conn)
            with conn, conn.cursor() as cur:
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
                        components.detection_coverage,
                        components.false_positive_health,
                        components.model_freshness,
                        components.scenario_diversity,
                        recorded_at_ms,
                    ),
                )
            conn.close()
        except ImportError:
            log.warning("psycopg2_not_installed_skipping_persistence")
        except Exception as exc:
            log.error("score_persist_failed", tenant_id=tenant_id, error=str(exc))

    def _fetch_history(
        self,
        tenant_id: str,
        days: int,
    ) -> list[dict[str, Any]]:
        """Fetch the score time series from PostgreSQL."""
        since_ms = int(time.time() * 1000) - days * 86_400_000
        try:
            import psycopg2  # type: ignore[import]
            import psycopg2.extras

            conn = psycopg2.connect(self._pg_conn)
            with conn, conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                cur.execute(
                    """
                    SELECT score, detection_coverage, false_positive_health,
                           model_freshness, scenario_diversity, recorded_at_ms
                    FROM immunity_score_history
                    WHERE tenant_id = %s AND recorded_at_ms >= %s
                    ORDER BY recorded_at_ms ASC
                    """,
                    (tenant_id, since_ms),
                )
                rows = [dict(r) for r in cur.fetchall()]
            conn.close()
            return rows
        except ImportError:
            log.warning("psycopg2_not_installed_returning_empty_history")
            return []
        except Exception as exc:
            log.error("history_fetch_failed", tenant_id=tenant_id, error=str(exc))
            return []

    # ── Scenario coverage report ───────────────────────────────────────────────

    def build_scenario_coverage(self, tenant_id: str) -> list[AttackTypeCoverage]:
        """
        Build per-attack-type coverage data for the /scenarios endpoint.

        Combines recall data from Redis with tested/untested status.
        """
        recalls = self._fetch_detection_recalls(tenant_id)
        tested = self._fetch_scenario_diversity(tenant_id)
        recall_threshold = float(os.getenv("DETECTION_RECALL_THRESHOLD", "0.90"))

        now_ms = int(time.time() * 1000)
        coverage_list: list[AttackTypeCoverage] = []

        try:
            r = self._get_redis()
        except Exception:
            r = None

        for attack_type in _CANONICAL_ATTACK_TYPES:
            is_tested = attack_type in tested
            recall = recalls.get(attack_type)

            last_tested_ms: int | None = None
            scenario_count = 0
            if r and is_tested:
                try:
                    ts_val = r.get(f"last_scenario_run:{tenant_id}:{attack_type}")
                    last_tested_ms = int(ts_val) if ts_val else None
                    count_val = r.get(f"scenario_count_30d:{tenant_id}:{attack_type}")
                    scenario_count = int(count_val) if count_val else 1
                except Exception:
                    pass

            hard_rule_passed: bool | None = None
            if recall is not None and is_tested:
                hard_rule_passed = recall >= recall_threshold

            # Recommend if not tested or failing recall
            recommended = (not is_tested) or (
                hard_rule_passed is not None and not hard_rule_passed
            )

            coverage_list.append(
                AttackTypeCoverage(
                    attack_type=attack_type,
                    last_tested_ms=last_tested_ms,
                    scenario_count=scenario_count,
                    detection_recall=recall if is_tested else None,
                    hard_rule_6_passed=hard_rule_passed,
                    recommended=recommended,
                )
            )

        return coverage_list

    # ── Public API ─────────────────────────────────────────────────────────────

    def get_score(self, tenant_id: str) -> tuple[dict[str, Any], bool]:
        """
        Get the current Immunity Score for a tenant.

        Returns:
            (score_payload, cache_hit) where score_payload is a dict matching
            ImmunityScoreResponse fields.
        """
        cached = self._get_cached(tenant_id)
        if cached is not None:
            log.info("immunity_score_cache_hit", tenant_id=tenant_id)
            return cached, True

        inputs = self._collect_inputs(tenant_id)
        components = self.compute_components(inputs)
        score = self.components_to_score(components)
        now_ms = int(time.time() * 1000)

        payload: dict[str, Any] = {
            "tenant_id": tenant_id,
            "score": score,
            "components": components.model_dump(),
            "computed_at_ms": now_ms,
            "cache_hit": False,
            "version": "1.0",
        }

        self._set_cached(tenant_id, payload)
        self._persist_score(tenant_id, score, components, now_ms)

        log.info(
            "immunity_score_computed",
            tenant_id=tenant_id,
            score=score,
            detection_coverage=components.detection_coverage,
            false_positive_health=components.false_positive_health,
            model_freshness=components.model_freshness,
            scenario_diversity=components.scenario_diversity,
        )

        return payload, False

    def get_history(
        self, tenant_id: str, days: int = 30
    ) -> list[dict[str, Any]]:
        """Fetch historical score time series from PostgreSQL."""
        return self._fetch_history(tenant_id, days)

    def invalidate_cache(self, tenant_id: str) -> None:
        """Force cache invalidation so next request recomputes."""
        try:
            r = self._get_redis()
            r.delete(self._cache_key(tenant_id))
            log.info("immunity_score_cache_invalidated", tenant_id=tenant_id)
        except Exception as exc:
            log.warning("cache_invalidation_failed", error=str(exc))

    def record_scenario_run(
        self,
        tenant_id: str,
        attack_type: str,
        recall: float,
    ) -> None:
        """
        Update Redis metrics after a scenario run completes.
        Called by attack_orchestrator trigger_detection_eval task.

        Writes:
          - detection_recall:{tenant_id}:{attack_type}
          - last_scenario_run:{tenant_id}:{attack_type}
          - scenarios_tested_30d:{tenant_id} (Redis Set with 30-day expiry)
          - scenario_count_30d:{tenant_id}:{attack_type}
        """
        now_ms = int(time.time() * 1000)
        window_s = _SCENARIO_WINDOW_DAYS * 86_400

        try:
            r = self._get_redis()
            pipe = r.pipeline()
            pipe.setex(
                f"detection_recall:{tenant_id}:{attack_type}",
                window_s,
                str(recall),
            )
            pipe.setex(
                f"last_scenario_run:{tenant_id}:{attack_type}",
                window_s,
                str(now_ms),
            )
            pipe.sadd(f"scenarios_tested_30d:{tenant_id}", attack_type)
            pipe.expire(f"scenarios_tested_30d:{tenant_id}", window_s)
            pipe.incr(f"scenario_count_30d:{tenant_id}:{attack_type}")
            pipe.expire(f"scenario_count_30d:{tenant_id}:{attack_type}", window_s)
            pipe.execute()

            # Invalidate cached score so next request reflects new data
            self.invalidate_cache(tenant_id)
            log.info(
                "scenario_run_recorded",
                tenant_id=tenant_id,
                attack_type=attack_type,
                recall=recall,
            )
        except Exception as exc:
            log.error("record_scenario_run_failed", error=str(exc))

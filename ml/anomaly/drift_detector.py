"""
drift_detector — Behavioral Drift Detection
===========================================

Detects behavioral drift by comparing an incoming transaction embedding to a
user's clean baseline profile stored in Pinecone.

Two-stage detection:
  1. Cosine distance from the user's `clean-profiles` vector (personal baseline).
  2. Nearest-neighbor similarity to `suspicious-profiles` vectors (known attack patterns).

A transaction is flagged when:
  - Its cosine distance from the clean profile exceeds `threshold` (drift), OR
  - Its similarity to a suspicious profile exceeds `suspicion_threshold`.

Multi-tenancy: all Pinecone calls pass `namespace=_pinecone_namespace(tenant_id)`.
  - "default" tenant maps to namespace="" (Pinecone default namespace, legacy compat).

Redis cache (clean-profile vectors):
  - Key: `drift_profile:{tenant_id}:{account_token}`
  - TTL: DRIFT_PROFILE_CACHE_TTL_S (default 300s / 5 min)
  - On cache hit: skip Pinecone fetch, compute cosine similarity locally.
  - On cache miss: fetch from Pinecone, store serialized vector in Redis.

Threshold configuration:
  - Default: 0.85 cosine similarity (i.e., distance > 0.15 triggers flag).
  - High-value account segment: 0.90 (more conservative — fewer false negatives).
  - Configurable via `DRIFT_THRESHOLD_DEFAULT` and `DRIFT_THRESHOLD_HIGH_VALUE` env vars.

DriftResult:
  - score: cosine similarity to user's clean baseline (1.0 = identical, 0.0 = orthogonal)
  - flagged: bool
  - drift_type: "personal_drift" | "suspicious_pattern" | "both" | None
  - nearest_neighbors: list of top-k Pinecone matches with scores
"""

import json
import math
import os
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

import structlog

log = structlog.get_logger(__name__)

_THRESHOLD_DEFAULT: float = float(os.getenv("DRIFT_THRESHOLD_DEFAULT", "0.85"))
_THRESHOLD_HIGH_VALUE: float = float(os.getenv("DRIFT_THRESHOLD_HIGH_VALUE", "0.90"))
_SUSPICION_THRESHOLD: float = float(os.getenv("DRIFT_SUSPICION_THRESHOLD", "0.80"))
_TOP_K: int = int(os.getenv("DRIFT_TOP_K", "5"))
_PINECONE_INDEX_CLEAN: str = os.getenv("PINECONE_INDEX_CLEAN", "clean-profiles")
_PINECONE_INDEX_SUSPICIOUS: str = os.getenv(
    "PINECONE_INDEX_SUSPICIOUS", "suspicious-profiles"
)
_REDIS_URL: str = os.getenv("REDIS_URL", "redis://localhost:6379/0")
_CACHE_TTL_S: int = int(os.getenv("DRIFT_PROFILE_CACHE_TTL_S", "300"))


class AccountSegment(str, Enum):
    RETAIL = "retail_banking"
    CORPORATE = "corporate_banking"
    HIGH_VALUE = "high_value"
    DEFAULT = "default"


@dataclass
class NeighborMatch:
    """A single Pinecone nearest-neighbor result."""

    vector_id: str
    score: float
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class DriftResult:
    """
    Outcome of drift detection for a single transaction.

    Attributes:
        account_token: Tokenized account identifier.
        transaction_id: UUID of the evaluated transaction.
        score: Cosine similarity to the user's clean profile (1.0 = identical).
        flagged: True if drift or suspicious pattern was detected.
        drift_type: Classification of what triggered the flag (or None).
        nearest_clean_neighbors: Top-k from clean-profiles index.
        nearest_suspicious_neighbors: Top-k from suspicious-profiles index.
        threshold_used: The cosine similarity threshold applied.
        evaluated_at_ms: Epoch milliseconds when detection ran.
        profile_exists: Whether a clean profile was found for this account.
    """

    account_token: str
    transaction_id: str
    score: float
    flagged: bool
    drift_type: str | None
    nearest_clean_neighbors: list[NeighborMatch] = field(default_factory=list)
    nearest_suspicious_neighbors: list[NeighborMatch] = field(default_factory=list)
    threshold_used: float = _THRESHOLD_DEFAULT
    evaluated_at_ms: int = field(default_factory=lambda: int(time.time() * 1000))
    profile_exists: bool = True
    latency_ms: int = 0


class DriftDetector:
    """
    Computes behavioral drift for incoming transactions.

    Args:
        pinecone_api_key: Pinecone API key. Falls back to `PINECONE_API_KEY` env var.
        redis_url: Redis URL for profile vector cache. Falls back to `REDIS_URL` env var.
        top_k: Number of nearest neighbors to retrieve from each index.
    """

    def __init__(
        self,
        pinecone_api_key: str | None = None,
        redis_url: str | None = None,
        *,
        top_k: int = _TOP_K,
    ) -> None:
        self._pc_key = pinecone_api_key or os.getenv("PINECONE_API_KEY", "")
        self._redis_url = redis_url or _REDIS_URL
        self._top_k = top_k
        self._clean_index: Any | None = None
        self._suspicious_index: Any | None = None
        self._redis: Any | None = None

    # ── Connections (lazy) ─────────────────────────────────────────────────────

    def _get_clean_index(self) -> Any:
        if self._clean_index is not None:
            return self._clean_index
        try:
            from pinecone import Pinecone  # type: ignore[import]

            pc = Pinecone(api_key=self._pc_key)
            self._clean_index = pc.Index(_PINECONE_INDEX_CLEAN)
        except ImportError:
            raise RuntimeError("pinecone-client not installed.")
        return self._clean_index

    def _get_suspicious_index(self) -> Any:
        if self._suspicious_index is not None:
            return self._suspicious_index
        try:
            from pinecone import Pinecone  # type: ignore[import]

            pc = Pinecone(api_key=self._pc_key)
            self._suspicious_index = pc.Index(_PINECONE_INDEX_SUSPICIOUS)
        except ImportError:
            raise RuntimeError("pinecone-client not installed.")
        return self._suspicious_index

    def _get_redis(self) -> Any | None:
        if self._redis is not None:
            return self._redis
        try:
            import redis as redis_lib  # type: ignore[import]

            self._redis = redis_lib.from_url(self._redis_url, decode_responses=True)
        except Exception:
            return None
        return self._redis

    # ── Redis-cached clean profile vector fetch ────────────────────────────────

    def _fetch_clean_profile_vector(
        self,
        account_token: str,
        namespace: str,
    ) -> list[float] | None:
        """
        Return the clean profile vector for account_token, using Redis as a cache.

        Cache key: drift_profile:{namespace or 'default'}:{account_token}
        TTL: DRIFT_PROFILE_CACHE_TTL_S (default 300s)

        Returns None if the profile does not exist in Pinecone.
        """
        ns_key = namespace if namespace else "default"
        cache_key = f"drift_profile:{ns_key}:{account_token}"

        r = self._get_redis()
        if r is not None:
            try:
                cached = r.get(cache_key)
                if cached is not None:
                    log.debug("drift_profile_cache_hit", account_token=account_token)
                    return json.loads(cached)
            except Exception as exc:
                log.warning("drift_profile_cache_read_error", error=str(exc))

        # Cache miss — fetch from Pinecone
        try:
            index = self._get_clean_index()
            result = index.fetch(ids=[account_token], namespace=namespace)
            vectors = result.get("vectors", {})
            if account_token not in vectors:
                return None
            vector: list[float] = vectors[account_token]["values"]
        except Exception as exc:
            log.warning(
                "drift_profile_pinecone_fetch_failed",
                account_token=account_token,
                error=str(exc),
            )
            return None

        if r is not None:
            try:
                r.set(cache_key, json.dumps(vector), ex=_CACHE_TTL_S)
                log.debug("drift_profile_cache_set", account_token=account_token)
            except Exception as exc:
                log.warning("drift_profile_cache_write_error", error=str(exc))

        return vector

    # ── Vector math ────────────────────────────────────────────────────────────

    @staticmethod
    def cosine_similarity(a: list[float], b: list[float]) -> float:
        """Compute cosine similarity between two vectors."""
        if len(a) != len(b):
            raise ValueError(
                f"Vector dimension mismatch: {len(a)} vs {len(b)}"
            )
        dot = sum(x * y for x, y in zip(a, b))
        norm_a = math.sqrt(sum(x * x for x in a))
        norm_b = math.sqrt(sum(y * y for y in b))
        if norm_a == 0 or norm_b == 0:
            return 0.0
        return dot / (norm_a * norm_b)

    # ── Threshold selection ────────────────────────────────────────────────────

    @staticmethod
    def get_threshold(account_segment: str | None) -> float:
        """Return the appropriate drift threshold for the given account segment."""
        if account_segment in (AccountSegment.HIGH_VALUE, "high_value", "corporate_banking"):
            return _THRESHOLD_HIGH_VALUE
        return _THRESHOLD_DEFAULT

    # ── Pinecone queries ───────────────────────────────────────────────────────

    def _query_clean_index(
        self,
        embedding: list[float],
        account_token: str,
        top_k: int,
        namespace: str = "",
    ) -> tuple[float, list[NeighborMatch]]:
        """
        Compute personal drift score using a Redis-cached profile vector, and
        return top-k nearest neighbors from Pinecone.

        The personal score is computed via local cosine similarity against the
        cached profile vector — skipping a redundant Pinecone query per request.

        Returns:
            (personal_score, neighbors) — personal_score is 0.0 if no profile found.
        """
        profile_vector = self._fetch_clean_profile_vector(account_token, namespace)
        personal_score = 0.0
        if profile_vector is not None:
            personal_score = self.cosine_similarity(embedding, profile_vector)

        # Top-k neighbors still queried from Pinecone for explainability
        index = self._get_clean_index()
        result = index.query(
            vector=embedding,
            top_k=top_k,
            include_metadata=True,
            namespace=namespace,
        )

        matches = result.get("matches", [])
        neighbors: list[NeighborMatch] = [
            NeighborMatch(
                vector_id=m.get("id", ""),
                score=float(m.get("score", 0.0)),
                metadata=m.get("metadata", {}),
            )
            for m in matches
        ]

        return personal_score, neighbors

    def _query_suspicious_index(
        self,
        embedding: list[float],
        top_k: int,
        namespace: str = "",
    ) -> tuple[float, list[NeighborMatch]]:
        """
        Query suspicious-profiles for known fraud pattern matches.

        Returns:
            (max_suspicious_score, neighbors)
        """
        index = self._get_suspicious_index()
        result = index.query(
            vector=embedding,
            top_k=top_k,
            include_metadata=True,
            namespace=namespace,
        )

        matches = result.get("matches", [])
        neighbors: list[NeighborMatch] = []
        max_score = 0.0

        for match in matches:
            vid = match.get("id", "")
            score = float(match.get("score", 0.0))
            meta = match.get("metadata", {})
            neighbors.append(NeighborMatch(vector_id=vid, score=score, metadata=meta))
            if score > max_score:
                max_score = score

        return max_score, neighbors

    # ── Public API ─────────────────────────────────────────────────────────────

    def detect(
        self,
        account_token: str,
        transaction_id: str,
        transaction_embedding: list[float],
        *,
        account_segment: str | None = None,
        tenant_id: str = "default",
    ) -> DriftResult:
        """
        Run drift detection for a single transaction embedding.

        Args:
            account_token: Tokenized account identifier (`tok_...`). Hard Rule #4:
                this must already be tokenized before calling this method.
            transaction_id: UUID of the transaction being evaluated.
            transaction_embedding: OpenAI embedding of the transaction text.
            account_segment: Account segment string for threshold selection.
            tenant_id: Tenant namespace for Pinecone isolation and Redis cache.

        Returns:
            DriftResult with score, flagged status, drift type, and neighbors.
        """
        start_ms = int(time.time() * 1000)
        threshold = self.get_threshold(account_segment)
        namespace = _pinecone_namespace(tenant_id)

        try:
            personal_score, clean_neighbors = self._query_clean_index(
                transaction_embedding, account_token, self._top_k, namespace
            )
            max_suspicious_score, suspicious_neighbors = self._query_suspicious_index(
                transaction_embedding, self._top_k, namespace
            )
        except Exception as exc:
            log.error(
                "drift_detection_query_failed",
                account_token=account_token,
                transaction_id=transaction_id,
                tenant_id=tenant_id,
                error=str(exc),
            )
            raise

        profile_exists = personal_score > 0.0

        # Drift logic
        personal_drift = profile_exists and (personal_score < threshold)
        suspicious_match = max_suspicious_score >= _SUSPICION_THRESHOLD

        flagged = personal_drift or suspicious_match

        if personal_drift and suspicious_match:
            drift_type = "both"
        elif personal_drift:
            drift_type = "personal_drift"
        elif suspicious_match:
            drift_type = "suspicious_pattern"
        else:
            drift_type = None

        latency_ms = int(time.time() * 1000) - start_ms

        result = DriftResult(
            account_token=account_token,
            transaction_id=transaction_id,
            score=personal_score,
            flagged=flagged,
            drift_type=drift_type,
            nearest_clean_neighbors=clean_neighbors,
            nearest_suspicious_neighbors=suspicious_neighbors,
            threshold_used=threshold,
            profile_exists=profile_exists,
            latency_ms=latency_ms,
        )

        log.info(
            "drift_detection_result",
            account_token=account_token,
            transaction_id=transaction_id,
            tenant_id=tenant_id,
            score=round(personal_score, 4),
            flagged=flagged,
            drift_type=drift_type,
            latency_ms=latency_ms,
            threshold=threshold,
        )

        return result

    def detect_batch(
        self,
        evaluations: list[dict[str, Any]],
        *,
        tenant_id: str = "default",
    ) -> list[DriftResult]:
        """
        Run drift detection for multiple transactions.

        Args:
            evaluations: List of dicts, each with keys:
                {account_token, transaction_id, transaction_embedding, account_segment (optional)}
            tenant_id: Tenant namespace for Pinecone isolation and Redis cache.

        Returns:
            List of DriftResult, one per evaluation.
        """
        results: list[DriftResult] = []
        for ev in evaluations:
            result = self.detect(
                account_token=ev["account_token"],
                transaction_id=ev["transaction_id"],
                transaction_embedding=ev["transaction_embedding"],
                account_segment=ev.get("account_segment"),
                tenant_id=tenant_id,
            )
            results.append(result)
        return results

    def to_detection_event(self, result: DriftResult) -> dict[str, Any]:
        """
        Serialize a DriftResult to a detection event dict suitable for Kafka.

        The dict is published to `KAFKA_TOPIC_DETECTION_RESULTS`.
        """
        return {
            "account_token": result.account_token,
            "transaction_id": result.transaction_id,
            "score": result.score,
            "flagged": result.flagged,
            "drift_type": result.drift_type,
            "threshold_used": result.threshold_used,
            "profile_exists": result.profile_exists,
            "latency_ms": result.latency_ms,
            "evaluated_at_ms": result.evaluated_at_ms,
            "nearest_clean": [
                {"id": n.vector_id, "score": n.score}
                for n in result.nearest_clean_neighbors[:3]
            ],
            "nearest_suspicious": [
                {
                    "id": n.vector_id,
                    "score": n.score,
                    "attack_type": n.metadata.get("attack_type", "unknown"),
                }
                for n in result.nearest_suspicious_neighbors[:3]
            ],
        }


def _pinecone_namespace(tenant_id: str) -> str:
    """Return the Pinecone namespace for a tenant. 'default' maps to '' for legacy compat."""
    return "" if tenant_id == "default" else tenant_id

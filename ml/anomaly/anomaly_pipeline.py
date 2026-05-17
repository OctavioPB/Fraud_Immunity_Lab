"""
anomaly_pipeline — Celery Drift Detection Pipeline
===================================================

Celery tasks that run behavioral drift detection on every TransactionEvent
consumed from Kafka, then publish results to `KAFKA_TOPIC_DETECTION_RESULTS`.

Task graph:
  embed_transaction          ← convert TransactionEvent to text + call OpenAI embedding
      ↓
  detect_drift               ← query Pinecone clean + suspicious indexes
      ↓
  publish_detection_result   ← produce result to detection_results Kafka topic

The tasks are designed to be called from:
  1. The Kafka TransactionConsumer (_emit_for_processing callback) — hot path.
  2. The attack_orchestrator DAG trigger_detection_eval task — red-team validation path.

Celery config: broker URL from `REDIS_URL` env var; task serializer: json.

Sprint 5: end-to-end pipeline wired with real Pinecone queries.
Sprint 7: wired to Immunity Score engine for DetectionCoverage component.
"""

import json
import os
import time
from typing import Any

import structlog

log = structlog.get_logger(__name__)

_REDIS_URL: str = os.getenv("REDIS_URL", "redis://localhost:6379/0")
_KAFKA_BOOTSTRAP: str = os.getenv("KAFKA_BOOTSTRAP_SERVERS", "localhost:9092")
_TOPIC_DETECTION_RESULTS: str = os.getenv(
    "KAFKA_TOPIC_DETECTION_RESULTS", "detection_results"
)
_OPENAI_MODEL: str = os.getenv("OPENAI_EMBEDDING_MODEL", "text-embedding-3-large")


# ── Celery app ─────────────────────────────────────────────────────────────────

def _make_celery_app() -> Any:
    try:
        from celery import Celery  # type: ignore[import]

        app = Celery(
            "anomaly_pipeline",
            broker=_REDIS_URL,
            backend=_REDIS_URL,
        )
        app.conf.update(
            task_serializer="json",
            accept_content=["json"],
            result_serializer="json",
            timezone="UTC",
            enable_utc=True,
            task_track_started=True,
            task_acks_late=True,           # re-queue on worker crash
            worker_prefetch_multiplier=1,  # one task at a time per worker
        )
        return app
    except ImportError:
        return None


celery_app = _make_celery_app()


def _task(*args, **kwargs):
    """Decorator that registers a Celery task if Celery is available, else is a no-op."""
    def decorator(fn):
        if celery_app is not None:
            return celery_app.task(*args, **kwargs)(fn)
        return fn
    if len(args) == 1 and callable(args[0]):
        # Called without arguments: @_task
        fn = args[0]
        if celery_app is not None:
            return celery_app.task(fn)
        return fn
    return decorator


# ── Embedding helper ───────────────────────────────────────────────────────────

def _build_transaction_text(event: dict[str, Any]) -> str:
    """Serialize a TransactionEvent into text suitable for embedding."""
    lines: list[str] = []

    amount = event.get("amount", 0)
    currency = event.get("currency", "USD")
    channel = event.get("channel", "unknown")
    merchant_id = event.get("merchant_id", "")
    metadata = event.get("metadata") or {}

    lines.append(f"transaction amount: {amount:.2f} {currency}")
    lines.append(f"channel: {channel}")

    if merchant_id:
        lines.append(f"merchant: {merchant_id}")

    category = metadata.get("category", "")
    if category:
        lines.append(f"merchant category: {category}")

    geo_country = metadata.get("geo_country", "")
    if geo_country:
        lines.append(f"country: {geo_country}")

    # Time-of-day hint (from timestamp ms)
    ts_ms = event.get("timestamp", 0)
    if ts_ms:
        hour = (ts_ms // 3_600_000) % 24
        lines.append(f"hour of day: {hour}")

    # Synthetic flag preserved in text for audit trail (not in embedding semantics)
    # but excluded from embedding text to avoid polluting the feature space

    return "\n".join(lines)


def _embed_text(text: str, openai_key: str) -> list[float]:
    try:
        from openai import OpenAI  # type: ignore[import]

        client = OpenAI(api_key=openai_key)
        response = client.embeddings.create(model=_OPENAI_MODEL, input=text)
        return response.data[0].embedding
    except ImportError:
        raise RuntimeError("openai package not installed.")


# ── Kafka result publisher ─────────────────────────────────────────────────────

def _publish_detection_result(result_dict: dict[str, Any]) -> None:
    """Produce a detection result event to the detection_results Kafka topic."""
    try:
        from confluent_kafka import Producer  # type: ignore[import]

        producer = Producer({"bootstrap.servers": _KAFKA_BOOTSTRAP})
        producer.produce(
            topic=_TOPIC_DETECTION_RESULTS,
            key=result_dict.get("transaction_id", "unknown"),
            value=json.dumps(result_dict).encode(),
        )
        producer.flush(timeout=5)
        log.info(
            "detection_result_published",
            transaction_id=result_dict.get("transaction_id"),
            flagged=result_dict.get("flagged"),
        )
    except ImportError:
        log.error("confluent_kafka_not_installed")
    except Exception as exc:
        log.error(
            "detection_result_publish_failed",
            transaction_id=result_dict.get("transaction_id"),
            error=str(exc),
        )


# ── Celery Tasks ───────────────────────────────────────────────────────────────

@_task(name="anomaly_pipeline.embed_transaction", bind=True, max_retries=3)
def embed_transaction(
    self: Any,
    transaction_event: dict[str, Any],
    account_token: str,
) -> dict[str, Any]:
    """
    Celery task: embed a TransactionEvent into a vector.

    Args:
        transaction_event: Raw transaction event dict from Kafka.
        account_token: Pre-tokenized account identifier (Hard Rule #4).

    Returns:
        {account_token, transaction_id, embedding, text}
    """
    transaction_id = transaction_event.get("transaction_id", "unknown")

    try:
        openai_key = os.getenv("OPENAI_API_KEY", "")
        text = _build_transaction_text(transaction_event)
        embedding = _embed_text(text, openai_key)

        log.info(
            "transaction_embedded",
            transaction_id=transaction_id,
            account_token=account_token,
            embedding_dim=len(embedding),
        )

        return {
            "account_token": account_token,
            "transaction_id": transaction_id,
            "embedding": embedding,
            "text": text,
        }
    except Exception as exc:
        log.error(
            "embed_transaction_failed",
            transaction_id=transaction_id,
            error=str(exc),
            retries=self.request.retries if hasattr(self, "request") else 0,
        )
        if hasattr(self, "retry"):
            raise self.retry(exc=exc, countdown=2 ** (self.request.retries + 1))
        raise


@_task(name="anomaly_pipeline.detect_drift", bind=True, max_retries=3)
def detect_drift(
    self: Any,
    embed_result: dict[str, Any],
    account_segment: str | None = None,
) -> dict[str, Any]:
    """
    Celery task: run drift detection on a pre-computed transaction embedding.

    Args:
        embed_result: Output of `embed_transaction` task.
        account_segment: Account segment string for threshold selection.

    Returns:
        Serialized DriftResult dict.
    """
    from ml.anomaly.drift_detector import DriftDetector

    account_token = embed_result["account_token"]
    transaction_id = embed_result["transaction_id"]
    embedding = embed_result["embedding"]

    try:
        detector = DriftDetector()
        result = detector.detect(
            account_token=account_token,
            transaction_id=transaction_id,
            transaction_embedding=embedding,
            account_segment=account_segment,
        )
        return detector.to_detection_event(result)
    except Exception as exc:
        log.error(
            "detect_drift_failed",
            transaction_id=transaction_id,
            error=str(exc),
        )
        if hasattr(self, "retry"):
            raise self.retry(exc=exc, countdown=2 ** (self.request.retries + 1))
        raise


@_task(name="anomaly_pipeline.publish_detection_result", bind=True, max_retries=5)
def publish_detection_result(
    self: Any,
    detection_event: dict[str, Any],
) -> dict[str, Any]:
    """
    Celery task: publish a detection result to the detection_results Kafka topic.

    Args:
        detection_event: Serialized DriftResult dict from `detect_drift`.

    Returns:
        {published: bool, transaction_id: str}
    """
    transaction_id = detection_event.get("transaction_id", "unknown")

    try:
        _publish_detection_result(detection_event)
        return {"published": True, "transaction_id": transaction_id}
    except Exception as exc:
        log.error(
            "publish_detection_result_failed",
            transaction_id=transaction_id,
            error=str(exc),
        )
        if hasattr(self, "retry"):
            raise self.retry(exc=exc, countdown=2 ** (self.request.retries + 1))
        raise


# ── Chain helper ───────────────────────────────────────────────────────────────

def run_detection_pipeline(
    transaction_event: dict[str, Any],
    account_token: str,
    *,
    account_segment: str | None = None,
    async_mode: bool = True,
) -> Any:
    """
    Kick off the full detection pipeline for a transaction.

    Called from:
      - TransactionConsumer._emit_for_processing()
      - attack_orchestrator trigger_detection_eval task

    Args:
        transaction_event: Raw Kafka transaction event dict.
        account_token: Pre-tokenized account identifier.
        account_segment: Account segment for threshold selection.
        async_mode: If True, dispatch as async Celery chain. If False, run synchronously.

    Returns:
        AsyncResult (async) or detection_event dict (sync).
    """
    if async_mode and celery_app is not None:
        try:
            from celery import chain  # type: ignore[import]

            pipeline = chain(
                embed_transaction.s(transaction_event, account_token),
                detect_drift.s(account_segment),
                publish_detection_result.s(),
            )
            return pipeline.apply_async()
        except Exception as exc:
            log.error(
                "detection_pipeline_dispatch_failed",
                transaction_id=transaction_event.get("transaction_id", "unknown"),
                error=str(exc),
            )
            raise

    # Synchronous fallback (used in tests and dry-run scenarios)
    embed_result = embed_transaction(transaction_event, account_token)
    detection_event = detect_drift(embed_result, account_segment)
    publish_detection_result(detection_event)
    return detection_event


def run_scenario_detection_eval(
    scenario_id: str,
    scenario_dict: dict[str, Any],
    injected_account_tokens: list[str],
    *,
    async_mode: bool = False,
) -> dict[str, Any]:
    """
    Run detection evaluation for a red-team scenario (called by attack_orchestrator).

    For each injected account token, synthesizes a representative transaction event
    and runs the full detection pipeline. Used to validate Hard Rule #6: ≥90% recall.

    Args:
        scenario_id: The scenario's UUID.
        scenario_dict: The full scenario config dict.
        injected_account_tokens: List of tokenized account IDs that received synthetic events.
        async_mode: Whether to dispatch as Celery chain (True) or run synchronously (False).

    Returns:
        {scenario_id, accounts_evaluated, flagged_count, recall, eval_status}
    """
    attack_type = scenario_dict.get("attack_type", "unknown")
    tx_pattern = scenario_dict.get("transaction_pattern") or {}

    results: list[dict[str, Any]] = []
    flagged_count = 0

    for account_token in injected_account_tokens:
        # Build a representative synthetic transaction event for this scenario
        synthetic_event: dict[str, Any] = {
            "transaction_id": f"eval_{scenario_id}_{account_token[:8]}",
            "account_id": account_token,  # already tokenized
            "amount": float(tx_pattern.get("avg_amount", 500.0)),
            "currency": "USD",
            "merchant_id": f"eval_merchant_{attack_type}",
            "timestamp": int(time.time() * 1000),
            "channel": "card_not_present",
            "metadata": {
                "synthetic": "true",
                "origin": "red_team",
                "scenario_id": scenario_id,
                "attack_type": attack_type,
            },
        }

        try:
            result = run_detection_pipeline(
                synthetic_event,
                account_token,
                account_segment=scenario_dict.get("target_segment"),
                async_mode=async_mode,
            )
            flagged = (
                result.get("flagged", False)
                if isinstance(result, dict)
                else False
            )
            if flagged:
                flagged_count += 1
            results.append(
                {"account_token": account_token, "flagged": flagged}
            )
        except Exception as exc:
            log.error(
                "scenario_eval_detection_failed",
                scenario_id=scenario_id,
                account_token=account_token,
                error=str(exc),
            )
            results.append(
                {"account_token": account_token, "flagged": False, "error": str(exc)}
            )

    accounts_evaluated = len(injected_account_tokens)
    recall = flagged_count / accounts_evaluated if accounts_evaluated > 0 else 0.0

    log.info(
        "scenario_detection_eval_complete",
        scenario_id=scenario_id,
        attack_type=attack_type,
        accounts_evaluated=accounts_evaluated,
        flagged_count=flagged_count,
        recall=round(recall, 4),
        hard_rule="Rule #6: recall must be >= 0.90 before deployment",
    )

    if recall < 0.90 and accounts_evaluated > 0:
        log.warning(
            "scenario_recall_below_threshold",
            scenario_id=scenario_id,
            recall=round(recall, 4),
            hard_rule="Rule #6 VIOLATION: this scenario type must NOT be deployed",
        )

    return {
        "scenario_id": scenario_id,
        "attack_type": attack_type,
        "accounts_evaluated": accounts_evaluated,
        "flagged_count": flagged_count,
        "recall": round(recall, 4),
        "eval_status": "complete" if accounts_evaluated > 0 else "no_accounts",
        "hard_rule_6_passed": recall >= 0.90,
    }

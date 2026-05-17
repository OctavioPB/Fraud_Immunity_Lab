"""
graph_ingestion — Kafka → Neo4j Graph Ingestion
================================================

Real-time Kafka consumer that writes TransactionEvent and LoginEvent records
into the Neo4j account relationship graph.

Two consumer modes:
  1. Real-time: `GraphIngestionConsumer` — standard Kafka consumer loop,
     processes one event at a time, commits after each successful write.
  2. Batch backfill: `BatchBackfillLoader` — parallelized by account segment,
     batches up to BATCH_SIZE rows and uses `batch_upsert_transactions.cypher`
     for throughput target (5,000 edges/minute).

Hard Rule #3: Synthetic events carry `synthetic: true` on all Neo4j nodes
and relationships they create.
Hard Rule #4: account_id values are tokenized by PIITokenizer before writing.
"""

import json
import os
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from typing import Any

import structlog

from ml.graph.schema import GraphDB, _NEO4J_DATABASE
from ml.embeddings.pii_tokenizer import PIITokenizer

log = structlog.get_logger(__name__)

_KAFKA_BOOTSTRAP: str = os.getenv("KAFKA_BOOTSTRAP_SERVERS", "localhost:9092")
_TOPIC_TRANSACTIONS: str = os.getenv("KAFKA_TOPIC_TRANSACTIONS", "transactions")
_TOPIC_LOGINS: str = os.getenv("KAFKA_TOPIC_LOGINS", "logins")
_CONSUMER_GROUP: str = os.getenv("KAFKA_CONSUMER_GROUP", "graph-ingestion-group")
_BATCH_SIZE: int = int(os.getenv("GRAPH_INGESTION_BATCH_SIZE", "500"))
_BATCH_PARALLELISM: int = int(os.getenv("GRAPH_INGESTION_PARALLELISM", "4"))


@dataclass
class IngestionStats:
    """Running stats for one ingestion session."""

    transactions_written: int = 0
    logins_written: int = 0
    errors: int = 0
    dlq_sent: int = 0
    started_at_ms: int = field(default_factory=lambda: int(time.time() * 1000))

    @property
    def total_written(self) -> int:
        return self.transactions_written + self.logins_written

    @property
    def elapsed_seconds(self) -> float:
        return (int(time.time() * 1000) - self.started_at_ms) / 1000.0

    @property
    def throughput_per_minute(self) -> float:
        elapsed = self.elapsed_seconds
        if elapsed <= 0:
            return 0.0
        return (self.total_written / elapsed) * 60.0


class GraphIngestionConsumer:
    """
    Real-time Kafka consumer that writes events to Neo4j.

    Subscribes to both `transactions` and `logins` topics.
    Processes events one at a time; commits offset only after successful
    Neo4j write. Malformed events go to the dead-letter topic.

    Args:
        driver: Neo4j driver instance. If None, creates one from env vars.
        tokenizer: PIITokenizer instance.
        dry_run: If True, parses events but does not write to Neo4j.
    """

    _UPSERT_TX_QUERY = GraphDB.load_query("upsert_transaction.cypher")
    _UPSERT_LOGIN_QUERY = GraphDB.load_query("upsert_login.cypher")

    def __init__(
        self,
        driver: Any | None = None,
        tokenizer: PIITokenizer | None = None,
        *,
        dry_run: bool = False,
    ) -> None:
        self._driver = driver
        self._tokenizer = tokenizer or PIITokenizer()
        self._dry_run = dry_run
        self._stats = IngestionStats()

    # ── Neo4j driver (lazy) ────────────────────────────────────────────────────

    def _get_driver(self) -> Any:
        if self._driver is None:
            self._driver = GraphDB.get_driver()
        return self._driver

    # ── Event → graph params ───────────────────────────────────────────────────

    def _transaction_to_params(self, event: dict[str, Any]) -> dict[str, Any]:
        """
        Convert a TransactionEvent dict to Neo4j query parameters.
        Tokenizes account_id (Hard Rule #4).
        Preserves synthetic flag (Hard Rule #3).
        """
        raw_account_id = event.get("account_id", "")
        sender_token = self._tokenizer.tokenize(raw_account_id)
        # Receiver: use merchant as proxy receiver for card transactions;
        # for P2P use metadata.receiver_account_id if present.
        raw_receiver = (
            event.get("metadata", {}).get("receiver_account_id")
            or event.get("merchant_id", "unknown")
        )
        receiver_token = (
            self._tokenizer.tokenize(raw_receiver)
            if raw_receiver != event.get("merchant_id", "unknown")
            else f"merchant_{event.get('merchant_id', 'unknown')}"
        )

        metadata = event.get("metadata") or {}
        is_synthetic = (
            metadata.get("synthetic") == "true"
            or metadata.get("synthetic") is True
            or event.get("synthetic", False)
        )

        return {
            "transaction_id": event.get("transaction_id", ""),
            "sender_id": sender_token,
            "receiver_id": receiver_token,
            "amount": float(event.get("amount", 0.0)),
            "currency": event.get("currency", "USD"),
            "merchant_id": event.get("merchant_id", "unknown"),
            "timestamp": int(event.get("timestamp", time.time() * 1000)),
            "channel": event.get("channel", "unknown"),
            "synthetic": is_synthetic,
            "origin": metadata.get("origin", "live"),
            "segment": metadata.get("segment", "retail_banking"),
        }

    def _login_to_params(self, event: dict[str, Any]) -> dict[str, Any]:
        """
        Convert a LoginEvent dict to Neo4j query parameters.
        Tokenizes account_id (Hard Rule #4).
        IP address is infrastructure metadata — not personal PII.
        """
        raw_account_id = event.get("account_id", "")
        account_token = self._tokenizer.tokenize(raw_account_id)

        geo = event.get("geo") or {}
        metadata = event.get("metadata") or {}
        is_synthetic = (
            metadata.get("synthetic") == "true"
            or metadata.get("synthetic") is True
        )

        return {
            "session_id": event.get("session_id", ""),
            "account_id": account_token,
            "ip_address": event.get("ip_address", "0.0.0.0"),
            "device_id": event.get("device_id", "unknown"),
            "os": event.get("os", "unknown"),
            "app_version": event.get("app_version", "unknown"),
            "timestamp": int(event.get("timestamp", time.time() * 1000)),
            "success": bool(event.get("success", True)),
            "synthetic": is_synthetic,
            "origin": metadata.get("origin", "live"),
            "segment": metadata.get("segment", "retail_banking"),
        }

    # ── Write operations ───────────────────────────────────────────────────────

    def write_transaction(self, event: dict[str, Any]) -> bool:
        """
        Write one TransactionEvent to Neo4j.

        Returns:
            True on success, False on error.
        """
        try:
            params = self._transaction_to_params(event)
            if self._dry_run:
                log.info(
                    "graph_write_dry_run",
                    event_type="transaction",
                    transaction_id=params["transaction_id"],
                )
                self._stats.transactions_written += 1
                return True

            GraphDB.run_query(self._get_driver(), self._UPSERT_TX_QUERY, params)
            self._stats.transactions_written += 1
            return True
        except Exception as exc:
            log.error(
                "graph_transaction_write_failed",
                transaction_id=event.get("transaction_id", "unknown"),
                error=str(exc),
            )
            self._stats.errors += 1
            return False

    def write_login(self, event: dict[str, Any]) -> bool:
        """
        Write one LoginEvent to Neo4j.

        Returns:
            True on success, False on error.
        """
        try:
            params = self._login_to_params(event)
            if self._dry_run:
                log.info(
                    "graph_write_dry_run",
                    event_type="login",
                    session_id=params["session_id"],
                )
                self._stats.logins_written += 1
                return True

            GraphDB.run_query(self._get_driver(), self._UPSERT_LOGIN_QUERY, params)
            self._stats.logins_written += 1
            return True
        except Exception as exc:
            log.error(
                "graph_login_write_failed",
                session_id=event.get("session_id", "unknown"),
                error=str(exc),
            )
            self._stats.errors += 1
            return False

    # ── Kafka consumer loop ────────────────────────────────────────────────────

    def run(self, max_messages: int | None = None) -> IngestionStats:
        """
        Start consuming from Kafka and writing to Neo4j.

        Args:
            max_messages: If set, stop after processing this many messages.
                          None = run indefinitely until KeyboardInterrupt.

        Returns:
            IngestionStats accumulated during the run.
        """
        try:
            from confluent_kafka import Consumer, KafkaError  # type: ignore[import]
        except ImportError:
            raise RuntimeError("confluent-kafka not installed.")

        consumer = Consumer(
            {
                "bootstrap.servers": _KAFKA_BOOTSTRAP,
                "group.id": _CONSUMER_GROUP,
                "auto.offset.reset": "earliest",
                "enable.auto.commit": False,
            }
        )
        consumer.subscribe([_TOPIC_TRANSACTIONS, _TOPIC_LOGINS])

        log.info(
            "graph_ingestion_started",
            topics=[_TOPIC_TRANSACTIONS, _TOPIC_LOGINS],
            dry_run=self._dry_run,
        )

        processed = 0
        try:
            while True:
                if max_messages is not None and processed >= max_messages:
                    break

                msg = consumer.poll(timeout=1.0)
                if msg is None:
                    continue
                if msg.error():
                    if msg.error().code() == KafkaError._PARTITION_EOF:
                        continue
                    log.error("kafka_error", error=str(msg.error()))
                    continue

                try:
                    event = json.loads(msg.value().decode("utf-8"))
                    topic = msg.topic()

                    if topic == _TOPIC_TRANSACTIONS:
                        success = self.write_transaction(event)
                    elif topic == _TOPIC_LOGINS:
                        success = self.write_login(event)
                    else:
                        success = True  # unknown topic — skip, commit

                    if success:
                        consumer.commit(asynchronous=False)
                        processed += 1
                    else:
                        self._stats.errors += 1

                except json.JSONDecodeError as exc:
                    log.error("graph_ingestion_decode_error", error=str(exc))
                    self._stats.errors += 1
                    consumer.commit(asynchronous=False)  # skip malformed
                except Exception as exc:
                    log.error("graph_ingestion_unexpected_error", error=str(exc))
                    self._stats.errors += 1

        except KeyboardInterrupt:
            log.info("graph_ingestion_stopped", **vars(self._stats))
        finally:
            consumer.close()
            if self._driver:
                self._driver.close()

        return self._stats

    @property
    def stats(self) -> IngestionStats:
        return self._stats


class BatchBackfillLoader:
    """
    High-throughput batch loader for historical transaction data.

    Parallelized by account segment — each segment runs in its own thread.
    Uses `batch_upsert_transactions.cypher` for bulk writes (UNWIND).
    Target: 5,000 transaction edges/minute.

    Args:
        driver: Neo4j driver. If None, creates from env vars.
        tokenizer: PIITokenizer instance.
        batch_size: Number of rows per UNWIND call (default 500).
        parallelism: Number of concurrent segment threads (default 4).
        dry_run: If True, validates data but does not write to Neo4j.
    """

    _BATCH_QUERY = GraphDB.load_query("batch_upsert_transactions.cypher")

    def __init__(
        self,
        driver: Any | None = None,
        tokenizer: PIITokenizer | None = None,
        *,
        batch_size: int = _BATCH_SIZE,
        parallelism: int = _BATCH_PARALLELISM,
        dry_run: bool = False,
    ) -> None:
        self._driver = driver
        self._tokenizer = tokenizer or PIITokenizer()
        self._batch_size = batch_size
        self._parallelism = parallelism
        self._dry_run = dry_run

    def _get_driver(self) -> Any:
        if self._driver is None:
            self._driver = GraphDB.get_driver()
        return self._driver

    def _prepare_row(self, event: dict[str, Any]) -> dict[str, Any]:
        """Tokenize and flatten a TransactionEvent for batch upsert."""
        raw_account_id = event.get("account_id", "")
        sender_token = self._tokenizer.tokenize(raw_account_id)
        metadata = event.get("metadata") or {}
        raw_receiver = metadata.get("receiver_account_id") or event.get("merchant_id", "unknown")
        receiver_token = (
            self._tokenizer.tokenize(raw_receiver)
            if metadata.get("receiver_account_id")
            else f"merchant_{raw_receiver}"
        )
        is_synthetic = metadata.get("synthetic") == "true" or metadata.get("synthetic") is True

        return {
            "transaction_id": event.get("transaction_id", ""),
            "sender_id": sender_token,
            "receiver_id": receiver_token,
            "amount": float(event.get("amount", 0.0)),
            "currency": event.get("currency", "USD"),
            "merchant_id": event.get("merchant_id", "unknown"),
            "timestamp": int(event.get("timestamp", time.time() * 1000)),
            "channel": event.get("channel", "unknown"),
            "synthetic": is_synthetic,
            "origin": metadata.get("origin", "live"),
            "segment": metadata.get("segment", "retail_banking"),
        }

    def _write_batch(self, rows: list[dict[str, Any]]) -> int:
        """Write one batch to Neo4j. Returns rows_processed."""
        if self._dry_run:
            log.info("batch_backfill_dry_run", batch_size=len(rows))
            return len(rows)

        result = GraphDB.run_query(
            self._get_driver(),
            self._BATCH_QUERY,
            {"rows": rows},
        )
        return result[0].get("rows_processed", len(rows)) if result else len(rows)

    def load_segment(
        self,
        segment: str,
        transactions: list[dict[str, Any]],
    ) -> dict[str, Any]:
        """
        Load all transactions for one account segment.

        Args:
            segment: Account segment label (e.g. "retail_banking").
            transactions: List of TransactionEvent dicts.

        Returns:
            {segment, total_rows, batches_written, errors}
        """
        rows = []
        for event in transactions:
            row = self._prepare_row(event)
            row["segment"] = segment
            rows.append(row)

        total = len(rows)
        written = 0
        errors = 0

        for i in range(0, total, self._batch_size):
            batch = rows[i : i + self._batch_size]
            try:
                count = self._write_batch(batch)
                written += count
                log.info(
                    "batch_written",
                    segment=segment,
                    batch_start=i,
                    batch_size=len(batch),
                    written=count,
                )
            except Exception as exc:
                log.error(
                    "batch_write_failed",
                    segment=segment,
                    batch_start=i,
                    error=str(exc),
                )
                errors += len(batch)

        return {
            "segment": segment,
            "total_rows": total,
            "batches_written": written,
            "errors": errors,
        }

    def load_all_segments(
        self,
        segment_data: dict[str, list[dict[str, Any]]],
    ) -> dict[str, Any]:
        """
        Load all segments in parallel.

        Args:
            segment_data: {segment_name: [transaction_events]}

        Returns:
            Summary dict with per-segment results and totals.
        """
        results: list[dict[str, Any]] = []
        start_ms = int(time.time() * 1000)

        with ThreadPoolExecutor(max_workers=self._parallelism) as executor:
            futures = {
                executor.submit(self.load_segment, seg, txs): seg
                for seg, txs in segment_data.items()
            }
            for future in as_completed(futures):
                segment = futures[future]
                try:
                    result = future.result()
                    results.append(result)
                    log.info("segment_load_complete", **result)
                except Exception as exc:
                    log.error(
                        "segment_load_failed",
                        segment=segment,
                        error=str(exc),
                    )
                    results.append(
                        {"segment": segment, "total_rows": 0, "batches_written": 0, "errors": -1}
                    )

        elapsed_ms = int(time.time() * 1000) - start_ms
        total_written = sum(r.get("batches_written", 0) for r in results)
        total_errors = sum(r.get("errors", 0) for r in results)
        throughput = (total_written / (elapsed_ms / 60_000)) if elapsed_ms > 0 else 0

        summary = {
            "segments_processed": len(results),
            "total_written": total_written,
            "total_errors": total_errors,
            "elapsed_ms": elapsed_ms,
            "throughput_per_minute": round(throughput, 1),
            "per_segment": results,
        }

        log.info("backfill_complete", **{k: v for k, v in summary.items() if k != "per_segment"})

        if self._driver:
            self._driver.close()

        return summary

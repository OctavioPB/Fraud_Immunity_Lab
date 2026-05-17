"""
Unit tests for ml/graph/graph_ingestion.py.

All Neo4j driver calls are mocked — no live database required.
Tests cover event-to-params conversion, PII tokenization, synthetic flag,
and batch backfill throughput logic.
"""

import time
import unittest.mock as mock

import pytest

from ml.embeddings.pii_tokenizer import PIITokenizer
from ml.graph.graph_ingestion import (
    BatchBackfillLoader,
    GraphIngestionConsumer,
    IngestionStats,
)


def _make_transaction_event(
    account_id: str = "ACC-001",
    merchant_id: str = "merchant-42",
    amount: float = 150.0,
    synthetic: bool = False,
) -> dict:
    ts = int(time.time() * 1000)
    return {
        "transaction_id": f"tx-{ts}",
        "account_id": account_id,
        "amount": amount,
        "currency": "USD",
        "merchant_id": merchant_id,
        "timestamp": ts,
        "channel": "card_not_present",
        "metadata": {
            "synthetic": "true" if synthetic else "false",
            "origin": "red_team" if synthetic else "live",
            "segment": "retail_banking",
            "category": "retail",
        },
    }


def _make_login_event(
    account_id: str = "ACC-002",
    ip_address: str = "192.168.1.1",
    synthetic: bool = False,
) -> dict:
    ts = int(time.time() * 1000)
    return {
        "session_id": f"sess-{ts}",
        "account_id": account_id,
        "ip_address": ip_address,
        "device_id": "device-abc",
        "os": "iOS 17",
        "app_version": "3.2.1",
        "timestamp": ts,
        "success": True,
        "metadata": {
            "synthetic": "true" if synthetic else "false",
            "origin": "red_team" if synthetic else "live",
            "segment": "retail_banking",
        },
    }


@pytest.fixture
def consumer() -> GraphIngestionConsumer:
    tokenizer = PIITokenizer(secret=b"test-secret")
    return GraphIngestionConsumer(tokenizer=tokenizer, dry_run=True)


@pytest.fixture
def loader() -> BatchBackfillLoader:
    tokenizer = PIITokenizer(secret=b"test-secret")
    return BatchBackfillLoader(tokenizer=tokenizer, dry_run=True, batch_size=5)


class TestIngestionStats:
    def test_total_written(self) -> None:
        stats = IngestionStats(transactions_written=10, logins_written=5)
        assert stats.total_written == 15

    def test_throughput_is_zero_for_zero_elapsed(self) -> None:
        stats = IngestionStats()
        stats.started_at_ms = int(time.time() * 1000) + 999_999
        assert stats.throughput_per_minute == 0.0


class TestTransactionToParams:
    def test_account_id_tokenized(self, consumer: GraphIngestionConsumer) -> None:
        event = _make_transaction_event(account_id="ACC-SENSITIVE-001")
        params = consumer._transaction_to_params(event)
        assert params["sender_id"].startswith("tok_")
        assert "ACC-SENSITIVE-001" not in params["sender_id"]

    def test_synthetic_flag_preserved_true(self, consumer: GraphIngestionConsumer) -> None:
        event = _make_transaction_event(synthetic=True)
        params = consumer._transaction_to_params(event)
        assert params["synthetic"] is True

    def test_synthetic_flag_false_for_live(self, consumer: GraphIngestionConsumer) -> None:
        event = _make_transaction_event(synthetic=False)
        params = consumer._transaction_to_params(event)
        assert params["synthetic"] is False

    def test_amount_preserved(self, consumer: GraphIngestionConsumer) -> None:
        event = _make_transaction_event(amount=999.99)
        params = consumer._transaction_to_params(event)
        assert params["amount"] == pytest.approx(999.99)

    def test_currency_preserved(self, consumer: GraphIngestionConsumer) -> None:
        event = _make_transaction_event()
        params = consumer._transaction_to_params(event)
        assert params["currency"] == "USD"

    def test_origin_live_for_non_synthetic(self, consumer: GraphIngestionConsumer) -> None:
        event = _make_transaction_event(synthetic=False)
        params = consumer._transaction_to_params(event)
        assert params["origin"] == "live"

    def test_origin_red_team_for_synthetic(self, consumer: GraphIngestionConsumer) -> None:
        event = _make_transaction_event(synthetic=True)
        params = consumer._transaction_to_params(event)
        assert params["origin"] == "red_team"


class TestLoginToParams:
    def test_account_id_tokenized(self, consumer: GraphIngestionConsumer) -> None:
        event = _make_login_event(account_id="ACC-PII-LOGIN")
        params = consumer._login_to_params(event)
        assert params["account_id"].startswith("tok_")
        assert "ACC-PII-LOGIN" not in params["account_id"]

    def test_ip_address_preserved(self, consumer: GraphIngestionConsumer) -> None:
        event = _make_login_event(ip_address="10.0.0.1")
        params = consumer._login_to_params(event)
        assert params["ip_address"] == "10.0.0.1"

    def test_synthetic_flag_true(self, consumer: GraphIngestionConsumer) -> None:
        event = _make_login_event(synthetic=True)
        params = consumer._login_to_params(event)
        assert params["synthetic"] is True

    def test_success_preserved(self, consumer: GraphIngestionConsumer) -> None:
        event = _make_login_event()
        event["success"] = False
        params = consumer._login_to_params(event)
        assert params["success"] is False


class TestWriteTransaction:
    def test_dry_run_returns_true(self, consumer: GraphIngestionConsumer) -> None:
        event = _make_transaction_event()
        result = consumer.write_transaction(event)
        assert result is True

    def test_dry_run_increments_stats(self, consumer: GraphIngestionConsumer) -> None:
        event = _make_transaction_event()
        consumer.write_transaction(event)
        assert consumer.stats.transactions_written == 1

    def test_write_failure_increments_errors(self, consumer: GraphIngestionConsumer) -> None:
        consumer._dry_run = False
        event = _make_transaction_event()
        with mock.patch.object(consumer, "_get_driver", side_effect=RuntimeError("no neo4j")):
            result = consumer.write_transaction(event)
        assert result is False
        assert consumer.stats.errors == 1


class TestWriteLogin:
    def test_dry_run_returns_true(self, consumer: GraphIngestionConsumer) -> None:
        event = _make_login_event()
        result = consumer.write_login(event)
        assert result is True

    def test_dry_run_increments_stats(self, consumer: GraphIngestionConsumer) -> None:
        event = _make_login_event()
        consumer.write_login(event)
        assert consumer.stats.logins_written == 1


class TestBatchBackfillLoader:
    def test_load_segment_returns_result(self, loader: BatchBackfillLoader) -> None:
        transactions = [_make_transaction_event() for _ in range(12)]
        result = loader.load_segment("retail_banking", transactions)
        assert result["segment"] == "retail_banking"
        assert result["total_rows"] == 12

    def test_dry_run_writes_all_rows(self, loader: BatchBackfillLoader) -> None:
        transactions = [_make_transaction_event() for _ in range(7)]
        result = loader.load_segment("corporate_banking", transactions)
        assert result["batches_written"] == 7
        assert result["errors"] == 0

    def test_pii_tokenized_in_batch(self, loader: BatchBackfillLoader) -> None:
        events = [_make_transaction_event(account_id="VERY-SENSITIVE-ID")]
        rows = [loader._prepare_row(e) for e in events]
        assert rows[0]["sender_id"].startswith("tok_")
        assert "VERY-SENSITIVE-ID" not in rows[0]["sender_id"]

    def test_synthetic_flag_in_prepared_row(self, loader: BatchBackfillLoader) -> None:
        event = _make_transaction_event(synthetic=True)
        row = loader._prepare_row(event)
        assert row["synthetic"] is True

    def test_load_all_segments_returns_summary(self, loader: BatchBackfillLoader) -> None:
        segment_data = {
            "retail_banking": [_make_transaction_event() for _ in range(5)],
            "corporate_banking": [_make_transaction_event() for _ in range(3)],
        }
        summary = loader.load_all_segments(segment_data)
        assert summary["segments_processed"] == 2
        assert summary["total_written"] > 0
        assert "throughput_per_minute" in summary

    def test_batches_split_by_batch_size(self, loader: BatchBackfillLoader) -> None:
        """Batch size is 5; 12 transactions should produce 3 batches (5+5+2)."""
        transactions = [_make_transaction_event() for _ in range(12)]
        written_batches: list[list] = []

        original_write = loader._write_batch

        def capture_batch(rows):
            written_batches.append(rows)
            return len(rows)

        with mock.patch.object(loader, "_write_batch", side_effect=capture_batch):
            loader.load_segment("retail_banking", transactions)

        assert len(written_batches) == 3
        assert len(written_batches[0]) == 5
        assert len(written_batches[2]) == 2

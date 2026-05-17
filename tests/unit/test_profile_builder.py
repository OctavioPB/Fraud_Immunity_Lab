"""
Unit tests for ml/embeddings/profile_builder.py.

All tests run in dry_run=True mode so no OpenAI or Pinecone calls are made.
Behavioral stats computation is tested without any external dependencies.
"""

import time

import pytest

from ml.embeddings.pii_tokenizer import PIITokenizer
from ml.embeddings.profile_builder import ProfileBuilder, ProfileUpsertResult


@pytest.fixture
def builder() -> ProfileBuilder:
    return ProfileBuilder(dry_run=True)


def _make_transactions(n: int = 20) -> list[dict]:
    now_ms = int(time.time() * 1000)
    transactions = []
    channels = ["card_present", "card_not_present", "ach"]
    for i in range(n):
        transactions.append(
            {
                "transaction_id": f"tx-{i:04d}",
                "account_id": "tok_test_account",
                "amount": 50.0 + i * 10,
                "currency": "USD",
                "merchant_id": f"merchant-{i % 5:03d}",
                "timestamp": now_ms - i * 3_600_000,
                "channel": channels[i % len(channels)],
                "metadata": {
                    "category": ["retail", "dining", "travel"][i % 3],
                    "geo_country": "US",
                },
            }
        )
    return transactions


class TestComputeBehavioralStats:
    def test_returns_transaction_count(self) -> None:
        txs = _make_transactions(15)
        stats = ProfileBuilder.compute_behavioral_stats(txs)
        assert stats["transaction_count"] == 15

    def test_computes_avg_amount(self) -> None:
        txs = [
            {
                "amount": 100.0,
                "currency": "USD",
                "channel": "card_present",
                "timestamp": 0,
                "merchant_id": "m1",
                "metadata": {},
            },
            {
                "amount": 200.0,
                "currency": "USD",
                "channel": "card_present",
                "timestamp": 0,
                "merchant_id": "m2",
                "metadata": {},
            },
        ]
        stats = ProfileBuilder.compute_behavioral_stats(txs)
        assert stats["avg_amount"] == pytest.approx(150.0)

    def test_computes_max_amount(self) -> None:
        txs = _make_transactions(10)
        stats = ProfileBuilder.compute_behavioral_stats(txs)
        assert stats["max_amount"] >= stats["avg_amount"]

    def test_empty_transactions_returns_zero_count(self) -> None:
        stats = ProfileBuilder.compute_behavioral_stats([])
        assert stats["transaction_count"] == 0

    def test_channel_distribution_present(self) -> None:
        txs = _make_transactions(9)
        stats = ProfileBuilder.compute_behavioral_stats(txs)
        assert "channels" in stats
        assert isinstance(stats["channels"], dict)

    def test_currency_detected(self) -> None:
        txs = _make_transactions(5)
        stats = ProfileBuilder.compute_behavioral_stats(txs)
        assert stats["currency"] == "USD"

    def test_geo_countries_present(self) -> None:
        txs = _make_transactions(5)
        stats = ProfileBuilder.compute_behavioral_stats(txs)
        assert "geo_countries" in stats
        assert "US" in stats["geo_countries"]


class TestBuildProfile:
    def test_returns_profile_upsert_result(self, builder: ProfileBuilder) -> None:
        # dry_run=True — no OpenAI or Pinecone call
        # We need to patch _embed since dry_run check happens after embed call
        import unittest.mock as mock

        with mock.patch.object(builder, "_embed", return_value=[0.1] * 3072):
            result = builder.build_profile("acc-001", _make_transactions(10))

        assert isinstance(result, ProfileUpsertResult)

    def test_dry_run_does_not_upsert(self, builder: ProfileBuilder) -> None:
        import unittest.mock as mock

        with mock.patch.object(builder, "_embed", return_value=[0.0] * 3072):
            result = builder.build_profile("acc-dry", _make_transactions(5))

        assert result.dry_run is True
        assert result.upserted is False

    def test_account_token_is_not_raw_id(self, builder: ProfileBuilder) -> None:
        import unittest.mock as mock

        with mock.patch.object(builder, "_embed", return_value=[0.0] * 3072):
            result = builder.build_profile("ACC-SENSITIVE", _make_transactions(5))

        assert result.account_token.startswith("tok_")
        assert "SENSITIVE" not in result.account_token

    def test_no_transactions_returns_error(self, builder: ProfileBuilder) -> None:
        result = builder.build_profile("acc-empty", [])
        assert result.upserted is False
        assert result.error is not None
        assert result.transaction_count == 0

    def test_label_is_legitimate(self, builder: ProfileBuilder) -> None:
        import unittest.mock as mock

        with mock.patch.object(builder, "_embed", return_value=[0.0] * 3072):
            result = builder.build_profile("acc-legit", _make_transactions(5))

        assert result.label == "legitimate"

    def test_transaction_count_in_result(self, builder: ProfileBuilder) -> None:
        import unittest.mock as mock

        with mock.patch.object(builder, "_embed", return_value=[0.0] * 3072):
            result = builder.build_profile("acc-count", _make_transactions(30))

        assert result.transaction_count == 30


class TestBuildProfilesBatch:
    def test_returns_result_per_account(self, builder: ProfileBuilder) -> None:
        import unittest.mock as mock

        accounts = [
            ("acc-a", _make_transactions(5)),
            ("acc-b", _make_transactions(5)),
            ("acc-c", _make_transactions(5)),
        ]

        with mock.patch.object(builder, "_embed", return_value=[0.0] * 3072):
            results = builder.build_profiles_batch(accounts)

        assert len(results) == 3

    def test_all_results_are_upsert_results(self, builder: ProfileBuilder) -> None:
        import unittest.mock as mock

        accounts = [("acc-x", _make_transactions(3))]

        with mock.patch.object(builder, "_embed", return_value=[0.0] * 3072):
            results = builder.build_profiles_batch(accounts)

        assert all(isinstance(r, ProfileUpsertResult) for r in results)

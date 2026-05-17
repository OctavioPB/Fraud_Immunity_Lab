"""
Unit tests for the SyntheticProducer.

All tests run in dry-run mode (SYNTHETIC_INJECTION_DRY_RUN=true) so no
real Kafka connection is needed. Hard Rule #3 compliance is verified on
every event type.
"""

import pytest

from ingestion.producers.synthetic_producer import SyntheticProducer
from ingestion.schemas.models import DeviceEvent, LoginEvent, TransactionEvent


@pytest.fixture
def producer(monkeypatch: pytest.MonkeyPatch) -> SyntheticProducer:
    """SyntheticProducer in dry-run mode — no Kafka, no Schema Registry."""
    monkeypatch.setenv("SYNTHETIC_INJECTION_DRY_RUN", "true")
    monkeypatch.setenv("KAFKA_BOOTSTRAP_SERVERS", "localhost:9092")
    return SyntheticProducer()


class TestSyntheticTag:
    """Hard Rule #3: every built event must carry synthetic=true."""

    def test_transaction_has_synthetic_tag(self, producer: SyntheticProducer) -> None:
        record = producer.build_transaction()
        assert record["metadata"]["synthetic"] == "true"
        assert record["metadata"]["origin"] == "red_team"

    def test_login_has_synthetic_tag(self, producer: SyntheticProducer) -> None:
        record = producer.build_login()
        assert record["metadata"]["synthetic"] == "true"
        assert record["metadata"]["origin"] == "red_team"

    def test_device_has_synthetic_tag(self, producer: SyntheticProducer) -> None:
        record = producer.build_device()
        assert record["metadata"]["synthetic"] == "true"
        assert record["metadata"]["origin"] == "red_team"

    def test_extra_metadata_merged_but_tag_preserved(
        self, producer: SyntheticProducer
    ) -> None:
        record = producer.build_transaction(extra_metadata={"scenario": "phishing"})
        assert record["metadata"]["synthetic"] == "true"
        assert record["metadata"]["scenario"] == "phishing"


class TestDryRunMode:
    def test_dry_run_skips_kafka(self, producer: SyntheticProducer) -> None:
        assert producer._dry_run is True

    def test_dry_run_increments_skipped_counter(
        self, producer: SyntheticProducer
    ) -> None:
        producer.produce_transaction()
        assert producer.stats.skipped_dry_run == 1
        assert producer.stats.produced == 0

    def test_mixed_burst_in_dry_run(self, producer: SyntheticProducer) -> None:
        stats = producer.produce_mixed_burst(transactions=10, logins=3, devices=2)
        assert stats.skipped_dry_run == 15
        assert stats.produced == 0
        assert stats.errors == 0


class TestEventStructure:
    def test_transaction_passes_pydantic_validation(
        self, producer: SyntheticProducer
    ) -> None:
        record = producer.build_transaction()
        event = TransactionEvent(**record)
        assert event.is_synthetic is True
        assert event.amount > 0

    def test_login_passes_pydantic_validation(
        self, producer: SyntheticProducer
    ) -> None:
        record = producer.build_login()
        event = LoginEvent(**record)
        assert event.is_synthetic is True

    def test_device_passes_pydantic_validation(
        self, producer: SyntheticProducer
    ) -> None:
        record = producer.build_device()
        event = DeviceEvent(**record)
        assert event.is_synthetic is True

    def test_transaction_currency_is_uppercase(
        self, producer: SyntheticProducer
    ) -> None:
        for _ in range(20):
            record = producer.build_transaction()
            assert record["currency"] == record["currency"].upper()

    def test_login_ip_is_hashed(self, producer: SyntheticProducer) -> None:
        """Raw IPs must not appear — the producer hashes them."""
        record = producer.build_login()
        ip = record["ip_address"]
        # Hashed form: no dots (hex string), not a raw quad-dotted IP
        assert "." not in ip

    def test_device_id_is_deterministic_from_fingerprint(
        self, producer: SyntheticProducer
    ) -> None:
        """device_id is derived from fingerprint — reproducible for the same input."""
        import uuid
        record = producer.build_device()
        expected = str(uuid.uuid5(uuid.NAMESPACE_DNS, record["fingerprint"]))
        assert record["device_id"] == expected

    def test_account_id_is_valid_uuid(self, producer: SyntheticProducer) -> None:
        import uuid
        record = producer.build_transaction()
        uuid.UUID(record["account_id"])  # raises ValueError if not valid


class TestBurstProduction:
    def test_transaction_burst_count(self, producer: SyntheticProducer) -> None:
        stats = producer.produce_transaction_burst(count=50)
        assert stats.skipped_dry_run == 50

    def test_unique_transaction_ids(self, producer: SyntheticProducer) -> None:
        ids = [producer.build_transaction()["transaction_id"] for _ in range(100)]
        assert len(set(ids)) == 100

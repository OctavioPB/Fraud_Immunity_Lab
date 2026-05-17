"""Unit tests for Pydantic event models — validation, synthetic flag, property accessors."""

import time

import pytest

from ingestion.schemas.models import DeviceEvent, GeoLocation, LoginEvent, TransactionEvent


class TestTransactionEvent:
    def _valid(self, **overrides):  # type: ignore[no-untyped-def]
        base = {
            "transaction_id": "tx-001",
            "account_id": "acct-001",
            "amount": 99.99,
            "currency": "USD",
            "merchant_id": "merch-001",
            "timestamp": int(time.time() * 1000),
            "channel": "card_not_present",
            "metadata": {},
        }
        return TransactionEvent(**{**base, **overrides})

    def test_valid_event_parses(self) -> None:
        event = self._valid()
        assert event.transaction_id == "tx-001"
        assert event.currency == "USD"

    def test_currency_uppercased(self) -> None:
        event = self._valid(currency="usd")
        assert event.currency == "USD"

    def test_amount_must_be_positive(self) -> None:
        with pytest.raises(Exception):
            self._valid(amount=-1.00)

    def test_amount_zero_rejected(self) -> None:
        with pytest.raises(Exception):
            self._valid(amount=0)

    def test_is_synthetic_true(self) -> None:
        event = self._valid(metadata={"synthetic": "true", "origin": "red_team"})
        assert event.is_synthetic is True

    def test_is_synthetic_false_when_not_tagged(self) -> None:
        event = self._valid(metadata={})
        assert event.is_synthetic is False

    def test_event_time_returns_datetime(self) -> None:
        ts = int(time.time() * 1000)
        event = self._valid(timestamp=ts)
        assert event.event_time is not None


class TestLoginEvent:
    def _valid(self, **overrides):  # type: ignore[no-untyped-def]
        base = {
            "session_id": "sess-001",
            "account_id": "acct-001",
            "ip_address": "abc123hash",
            "user_agent": "Mozilla/5.0",
            "geo": {"country": "MX", "city": "CDMX", "lat": 19.43, "lon": -99.13},
            "timestamp": int(time.time() * 1000),
            "success": True,
            "failure_reason": None,
            "metadata": {},
        }
        return LoginEvent(**{**base, **overrides})

    def test_valid_event_parses(self) -> None:
        event = self._valid()
        assert event.session_id == "sess-001"
        assert event.geo.country == "MX"

    def test_failure_reason_null_on_success(self) -> None:
        event = self._valid(success=True, failure_reason=None)
        assert event.failure_reason is None

    def test_failure_reason_set_on_failed_login(self) -> None:
        event = self._valid(success=False, failure_reason="bad_password")
        assert event.failure_reason == "bad_password"

    def test_is_synthetic_from_metadata(self) -> None:
        event = self._valid(metadata={"synthetic": "true", "origin": "red_team"})
        assert event.is_synthetic is True

    def test_geo_nested_model(self) -> None:
        event = self._valid()
        assert isinstance(event.geo, GeoLocation)
        assert event.geo.lat == 19.43


class TestDeviceEvent:
    def _valid(self, **overrides):  # type: ignore[no-untyped-def]
        base = {
            "device_id": "dev-001",
            "account_id": "acct-001",
            "fingerprint": "abc" * 20,
            "os": "iOS 17.2",
            "app_version": "4.2.1",
            "event_type": "registered",
            "timestamp": int(time.time() * 1000),
            "metadata": {},
        }
        return DeviceEvent(**{**base, **overrides})

    def test_valid_event_parses(self) -> None:
        event = self._valid()
        assert event.device_id == "dev-001"
        assert event.event_type == "registered"

    def test_is_synthetic_from_metadata(self) -> None:
        event = self._valid(metadata={"synthetic": "true", "origin": "red_team"})
        assert event.is_synthetic is True

    def test_is_synthetic_false_without_tag(self) -> None:
        event = self._valid(metadata={})
        assert event.is_synthetic is False

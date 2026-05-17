"""
Pydantic event models for internal validation after Avro deserialization.
These are the canonical in-process representations of each event type.
"""

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field, field_validator


class GeoLocation(BaseModel):
    country: str
    city: str
    lat: float
    lon: float


class TransactionEvent(BaseModel):
    """Validated in-process representation of a TransactionEvent."""

    transaction_id: str
    account_id: str
    amount: float = Field(gt=0)
    currency: str = Field(min_length=3, max_length=3)
    merchant_id: str
    timestamp: int = Field(description="Unix epoch milliseconds")
    channel: str
    metadata: dict[str, str] = Field(default_factory=dict)

    @field_validator("currency")
    @classmethod
    def currency_uppercase(cls, v: str) -> str:
        return v.upper()

    @property
    def is_synthetic(self) -> bool:
        return self.metadata.get("synthetic") == "true"

    @property
    def event_time(self) -> datetime:
        return datetime.utcfromtimestamp(self.timestamp / 1000)


class LoginEvent(BaseModel):
    """Validated in-process representation of a LoginEvent."""

    session_id: str
    account_id: str
    ip_address: str
    user_agent: str
    geo: GeoLocation
    timestamp: int = Field(description="Unix epoch milliseconds")
    success: bool
    failure_reason: str | None = None
    metadata: dict[str, str] = Field(default_factory=dict)

    @property
    def is_synthetic(self) -> bool:
        return self.metadata.get("synthetic") == "true"

    @property
    def event_time(self) -> datetime:
        return datetime.utcfromtimestamp(self.timestamp / 1000)


class DeviceEvent(BaseModel):
    """Validated in-process representation of a DeviceEvent."""

    device_id: str
    account_id: str
    fingerprint: str
    os: str
    app_version: str
    event_type: str
    timestamp: int = Field(description="Unix epoch milliseconds")
    metadata: dict[str, str] = Field(default_factory=dict)

    @property
    def is_synthetic(self) -> bool:
        return self.metadata.get("synthetic") == "true"

    @property
    def event_time(self) -> datetime:
        return datetime.utcfromtimestamp(self.timestamp / 1000)

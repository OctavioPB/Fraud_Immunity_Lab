"""
pii_tokenizer — PII Tokenization Middleware
============================================

Hard Rule #4 enforcement: raw account numbers, names, government IDs, and other
PII must never appear in Pinecone vectors or Neo4j properties.

This module provides deterministic, reversible tokenization via HMAC-SHA256.
The token preserves the semantic identity (same input → same token) without
exposing the raw value, enabling Pinecone metadata lookups without PII.

Usage:
    tokenizer = PIITokenizer()
    safe_record = tokenizer.tokenize_record(raw_record)
    # safe_record["account_id"] is now a deterministic token like "tok_a3f8..."
"""

import hashlib
import hmac
import os
import re
from dataclasses import dataclass, field
from typing import Any


# ── PII Detection Patterns ─────────────────────────────────────────────────────

_PII_FIELD_NAMES: frozenset[str] = frozenset(
    {
        "account_id",
        "account_number",
        "card_number",
        "pan",
        "ssn",
        "tax_id",
        "name",
        "full_name",
        "first_name",
        "last_name",
        "email",
        "phone",
        "phone_number",
        "iban",
        "routing_number",
        "dob",
        "date_of_birth",
        "passport_number",
        "drivers_license",
    }
)

_PII_VALUE_PATTERNS: dict[str, re.Pattern] = {
    "ssn": re.compile(r"\b\d{3}-\d{2}-\d{4}\b"),
    "credit_card": re.compile(r"\b(?:\d{4}[\s\-]?){3}\d{4}\b"),
    "iban": re.compile(r"\b[A-Z]{2}\d{2}[A-Z0-9]{4}\d{7}(?:[A-Z0-9]?){0,16}\b"),
    "email": re.compile(r"\b[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}\b"),
    "phone_us": re.compile(r"\b(?:\+1[\s\-]?)?\(?\d{3}\)?[\s\-]?\d{3}[\s\-]?\d{4}\b"),
    "account_number": re.compile(r"\b\d{8,17}\b"),
}


@dataclass
class TokenizationReport:
    """Summary of what was tokenized and what PII patterns were detected."""

    tokenized_fields: list[str] = field(default_factory=list)
    detected_patterns: dict[str, list[str]] = field(default_factory=dict)

    @property
    def pii_found(self) -> bool:
        return bool(self.tokenized_fields or self.detected_patterns)


class PIITokenizer:
    """
    Deterministic HMAC-SHA256 tokenizer for PII fields.

    Tokens are prefixed with `tok_` and derived from HMAC-SHA256(secret, value),
    so the same raw value always produces the same token — enabling consistent
    Pinecone metadata queries without storing raw PII.

    Args:
        secret: HMAC secret key. Defaults to `PII_TOKEN_SECRET` env var.
                Falls back to a fixed dev-only string with a logged warning.
    """

    _DEV_SECRET = b"dev-only-secret-not-for-production"

    def __init__(self, secret: bytes | None = None) -> None:
        env_secret = os.getenv("PII_TOKEN_SECRET", "")
        if secret is not None:
            self._secret = secret
        elif env_secret:
            self._secret = env_secret.encode()
        else:
            import structlog
            structlog.get_logger(__name__).warning(
                "pii_token_secret_missing",
                note="Using dev-only secret — set PII_TOKEN_SECRET in production",
            )
            self._secret = self._DEV_SECRET

    # ── Public API ─────────────────────────────────────────────────────────────

    def tokenize(self, value: str) -> str:
        """Return a deterministic `tok_<hex>` token for the given raw value."""
        digest = hmac.new(self._secret, value.encode(), hashlib.sha256).hexdigest()
        return f"tok_{digest[:32]}"

    def is_pii_field(self, field_name: str) -> bool:
        """Return True if the field name is a known PII field."""
        return field_name.lower() in _PII_FIELD_NAMES

    def scan_value(self, value: str) -> dict[str, list[str]]:
        """Scan a string value for PII patterns. Returns {pattern_name: [matches]}."""
        found: dict[str, list[str]] = {}
        for name, pattern in _PII_VALUE_PATTERNS.items():
            matches = pattern.findall(str(value))
            if matches:
                found[name] = matches
        return found

    def tokenize_record(
        self,
        record: dict[str, Any],
        *,
        extra_pii_fields: set[str] | None = None,
    ) -> tuple[dict[str, Any], TokenizationReport]:
        """
        Tokenize all PII fields in a record dict (shallow, non-mutating).

        Args:
            record: Input dict (e.g., Pydantic model dict).
            extra_pii_fields: Additional field names to treat as PII beyond defaults.

        Returns:
            (safe_record, report) — safe_record has tokens in place of PII values,
            report summarizes what was tokenized and any pattern-detected PII.
        """
        pii_fields = _PII_FIELD_NAMES
        if extra_pii_fields:
            pii_fields = _PII_FIELD_NAMES | {f.lower() for f in extra_pii_fields}

        report = TokenizationReport()
        safe: dict[str, Any] = {}

        for key, val in record.items():
            if key.lower() in pii_fields and isinstance(val, str) and val:
                safe[key] = self.tokenize(val)
                report.tokenized_fields.append(key)
            elif isinstance(val, str):
                patterns = self.scan_value(val)
                if patterns:
                    report.detected_patterns[key] = list(patterns.keys())
                    # Redact the value — tokenizing free-text is lossy, so redact
                    safe[key] = "[REDACTED]"
                else:
                    safe[key] = val
            elif isinstance(val, dict):
                nested_safe, nested_report = self.tokenize_record(
                    val, extra_pii_fields=extra_pii_fields
                )
                safe[key] = nested_safe
                report.tokenized_fields.extend(
                    f"{key}.{f}" for f in nested_report.tokenized_fields
                )
                report.detected_patterns.update(
                    {f"{key}.{k}": v for k, v in nested_report.detected_patterns.items()}
                )
            else:
                safe[key] = val

        return safe, report

    def build_embedding_text(
        self,
        account_token: str,
        stats: dict[str, Any],
    ) -> str:
        """
        Serialize a user's behavioral statistics into a text blob suitable for embedding.

        The text uses the token (not raw account_id) so Hard Rule #4 is enforced
        at the embedding boundary.

        Args:
            account_token: Tokenized account identifier (`tok_...`).
            stats: Dict of behavioral statistics (amounts, categories, time patterns, geo).

        Returns:
            Human-readable text describing the behavioral profile.
        """
        lines = [f"account: {account_token}"]

        if "avg_amount" in stats:
            lines.append(f"average transaction amount: {stats['avg_amount']:.2f}")
        if "median_amount" in stats:
            lines.append(f"median amount: {stats['median_amount']:.2f}")
        if "max_amount" in stats:
            lines.append(f"max single transaction: {stats['max_amount']:.2f}")
        if "transaction_count" in stats:
            lines.append(f"transaction count: {stats['transaction_count']}")
        if "merchant_categories" in stats:
            cats = ", ".join(str(c) for c in stats["merchant_categories"][:10])
            lines.append(f"top merchant categories: {cats}")
        if "channels" in stats:
            chans = ", ".join(f"{k}:{v}" for k, v in stats["channels"].items())
            lines.append(f"channel mix: {chans}")
        if "hour_distribution" in stats:
            peak_hours = sorted(
                stats["hour_distribution"].items(), key=lambda x: -x[1]
            )[:3]
            hours_str = ", ".join(f"{h}:00" for h, _ in peak_hours)
            lines.append(f"peak transaction hours: {hours_str}")
        if "geo_countries" in stats:
            countries = ", ".join(stats["geo_countries"][:5])
            lines.append(f"transaction countries: {countries}")
        if "currency" in stats:
            lines.append(f"primary currency: {stats['currency']}")

        return "\n".join(lines)

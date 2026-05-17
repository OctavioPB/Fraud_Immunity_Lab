"""
Output validators for attacker agents.

Two validation passes run on every LLM-generated scenario:
  1. JSON Schema structural validation — rejects malformed output immediately.
  2. PII scan — flags and strips any raw PII patterns before the scenario
     is accepted. Hard Rule #4: PII must never cross the embedding boundary,
     and it must never appear in scenario configs stored in Kafka.
"""

import json
import re
from dataclasses import dataclass
from typing import Any

import structlog

logger = structlog.get_logger(__name__)

# ── PII detection patterns ────────────────────────────────────────────────────
# Ordered from most-specific to least-specific to avoid false-positive cascades.
_PII_PATTERNS: dict[str, re.Pattern[str]] = {
    "ssn": re.compile(r"\b\d{3}-\d{2}-\d{4}\b"),
    "credit_card": re.compile(
        r"\b(?:\d{4}[\s\-]?){3}\d{4}\b"
    ),
    "iban": re.compile(r"\b[A-Z]{2}\d{2}[A-Z0-9]{11,30}\b"),
    "email": re.compile(
        r"\b[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}\b"
    ),
    "phone_us": re.compile(
        r"\b(\+?1[\s.\-]?)?\(?\d{3}\)?[\s.\-]?\d{3}[\s.\-]?\d{4}\b"
    ),
    "account_number": re.compile(r"\b\d{8,17}\b"),  # bank account-length numerics
}

# JSON Schema for ScenarioConfig — validated before Pydantic parsing.
# Kept in sync with ScenarioConfig manually; any new field must appear here.
SCENARIO_JSON_SCHEMA: dict[str, Any] = {
    "$schema": "https://json-schema.org/draft/2020-12",
    "title": "ScenarioConfig",
    "type": "object",
    "required": [
        "attack_type",
        "complexity",
        "target_segment",
        "evasion_tactics",
        "transaction_pattern",
        "expected_detection_signals",
    ],
    "properties": {
        "attack_type": {"type": "string", "minLength": 1},
        "complexity": {
            "type": "string",
            "enum": ["low", "medium", "high", "critical"],
        },
        "target_segment": {"type": "string", "minLength": 1},
        "evasion_tactics": {
            "type": "array",
            "items": {"type": "string"},
            "minItems": 1,
        },
        "transaction_pattern": {"type": "object"},
        "expected_detection_signals": {
            "type": "array",
            "items": {"type": "string"},
            "minItems": 1,
        },
        "synthetic": {"type": "boolean"},
        "origin": {"type": "string"},
    },
    "additionalProperties": True,
}


@dataclass
class ValidationResult:
    valid: bool
    errors: list[str]
    pii_found: dict[str, list[str]]

    @property
    def has_pii(self) -> bool:
        return bool(self.pii_found)


def validate_schema(data: dict[str, Any]) -> ValidationResult:
    """
    Validate a raw LLM output dict against SCENARIO_JSON_SCHEMA.
    Uses jsonschema for validation — no Pydantic involved at this layer.
    """
    try:
        import jsonschema

        jsonschema.validate(instance=data, schema=SCENARIO_JSON_SCHEMA)
        return ValidationResult(valid=True, errors=[], pii_found={})
    except ImportError:
        # Fallback: manual required-field check when jsonschema is unavailable
        missing = [
            f for f in SCENARIO_JSON_SCHEMA["required"] if f not in data
        ]
        if missing:
            return ValidationResult(
                valid=False,
                errors=[f"Missing required fields: {missing}"],
                pii_found={},
            )
        return ValidationResult(valid=True, errors=[], pii_found={})
    except Exception as exc:
        return ValidationResult(valid=False, errors=[str(exc)], pii_found={})


def scan_for_pii(data: dict[str, Any]) -> dict[str, list[str]]:
    """
    Recursively scan every string value in the scenario dict for PII patterns.
    Returns {pii_type: [matched_values]} — empty dict means clean.
    """
    text = json.dumps(data)
    found: dict[str, list[str]] = {}
    for pii_type, pattern in _PII_PATTERNS.items():
        matches = pattern.findall(text)
        if matches:
            found[pii_type] = list(set(matches))
    return found


def strip_pii(data: dict[str, Any]) -> dict[str, Any]:
    """
    Recursively replace PII matches with a [REDACTED] placeholder.
    Returns a new dict — does not mutate the original.
    """
    text = json.dumps(data)
    for pattern in _PII_PATTERNS.values():
        text = pattern.sub("[REDACTED]", text)
    return json.loads(text)  # type: ignore[return-value]


def validate_and_sanitize(
    data: dict[str, Any],
) -> tuple[ValidationResult, dict[str, Any]]:
    """
    Full validation pipeline for one LLM-generated scenario:
      1. JSON Schema structural check
      2. PII scan on the raw output
      3. If PII found: strip it, log, then re-validate the sanitized copy

    Returns (result, sanitized_data).
    If structural validation fails, returns (result, original_data) — do not use the data.
    """
    schema_result = validate_schema(data)
    if not schema_result.valid:
        logger.error(
            "scenario_schema_invalid",
            errors=schema_result.errors,
        )
        return schema_result, data

    pii = scan_for_pii(data)
    if pii:
        logger.warning(
            "scenario_pii_detected",
            pii_types=list(pii.keys()),
            # Never log the matched values themselves — they are PII
        )
        data = strip_pii(data)
        pii = {}  # clean after strip

    return ValidationResult(valid=True, errors=[], pii_found=pii), data

"""
Schema registry client — loads Avro schemas from disk and registers them
with the Confluent Schema Registry. Provides serializer/deserializer helpers
used by all consumers and producers.
"""

import io
import json
import os
import struct
from pathlib import Path
from typing import Any

import fastavro
import requests
import structlog

logger = structlog.get_logger(__name__)

_SCHEMA_DIR = Path(__file__).parent
_MAGIC_BYTE = b"\x00"

# Confluent wire format: [magic_byte(1)] [schema_id(4, big-endian)] [avro_payload]
_HEADER_SIZE = 5


def load_schema(name: str) -> dict[str, Any]:
    """Load and parse an Avro schema from the schemas/ directory."""
    path = _SCHEMA_DIR / f"{name}.avsc"
    with open(path, encoding="utf-8") as f:
        raw = json.load(f)
    # fastavro needs the schema parsed
    return fastavro.parse_schema(raw)


class SchemaRegistry:
    """
    Thin wrapper around the Confluent Schema Registry REST API.
    Handles schema registration and ID lookup with a local cache.
    """

    def __init__(self, url: str | None = None) -> None:
        self._url = (url or os.getenv("SCHEMA_REGISTRY_URL", "http://localhost:8081")).rstrip("/")
        self._id_cache: dict[str, int] = {}

    def register(self, subject: str, schema: dict[str, Any]) -> int:
        """Register schema under subject. Returns schema ID."""
        if subject in self._id_cache:
            return self._id_cache[subject]

        payload = {"schema": json.dumps(schema)}
        resp = requests.post(
            f"{self._url}/subjects/{subject}/versions",
            json=payload,
            timeout=10,
        )
        resp.raise_for_status()
        schema_id: int = resp.json()["id"]
        self._id_cache[subject] = schema_id
        logger.info("schema_registered", subject=subject, schema_id=schema_id)
        return schema_id

    def get_schema_id(self, subject: str) -> int:
        """Fetch the latest schema ID for a subject (cached)."""
        if subject in self._id_cache:
            return self._id_cache[subject]

        resp = requests.get(
            f"{self._url}/subjects/{subject}/versions/latest",
            timeout=10,
        )
        resp.raise_for_status()
        schema_id: int = resp.json()["id"]
        self._id_cache[subject] = schema_id
        return schema_id


def serialize(record: dict[str, Any], schema: dict[str, Any], schema_id: int) -> bytes:
    """
    Serialize a Python dict to Confluent wire-format Avro bytes:
    [0x00] [schema_id: 4 bytes big-endian] [avro binary]
    """
    buf = io.BytesIO()
    buf.write(_MAGIC_BYTE)
    buf.write(struct.pack(">I", schema_id))
    fastavro.schemaless_writer(buf, schema, record)
    return buf.getvalue()


def deserialize(raw: bytes, schema: dict[str, Any]) -> dict[str, Any]:
    """
    Deserialize Confluent wire-format Avro bytes back to a Python dict.
    Strips the 5-byte header before parsing.
    """
    if len(raw) < _HEADER_SIZE or raw[0:1] != _MAGIC_BYTE:
        raise ValueError("Invalid Confluent Avro wire format — missing magic byte")

    payload = io.BytesIO(raw[_HEADER_SIZE:])
    return fastavro.schemaless_reader(payload, schema)  # type: ignore[return-value]

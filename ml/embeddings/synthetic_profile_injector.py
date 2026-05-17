"""
synthetic_profile_injector — Synthetic Fraud Profile Injector
==============================================================

Takes attacker agent output (ScenarioConfig dicts) and embeds the fraud pattern
into the Pinecone `suspicious-profiles` index with `label: synthetic_fraud`.

This gives the drift detector a reference corpus of known attack embeddings for
nearest-neighbor classification (in addition to cosine distance from clean profiles).

Hard Rule #3: Every vector upserted here carries `synthetic: true` in metadata.
Hard Rule #4: No raw PII in any Pinecone metadata — account IDs are tokenized.

Usage:
    injector = SyntheticProfileInjector()
    result = injector.inject_scenario_profile(scenario_dict)
"""

import os
import time
from dataclasses import dataclass, field
from typing import Any

import structlog

from ml.embeddings.pii_tokenizer import PIITokenizer

log = structlog.get_logger(__name__)

_EMBEDDING_MODEL: str = os.getenv("OPENAI_EMBEDDING_MODEL", "text-embedding-3-large")
_PINECONE_INDEX_SUSPICIOUS: str = os.getenv(
    "PINECONE_INDEX_SUSPICIOUS", "suspicious-profiles"
)


@dataclass
class InjectionResult:
    """Result of a synthetic profile injection into Pinecone."""

    scenario_id: str
    attack_type: str
    profile_vector_id: str
    upserted: bool
    dry_run: bool
    injected_at_ms: int = field(default_factory=lambda: int(time.time() * 1000))
    error: str | None = None


class SyntheticProfileInjector:
    """
    Embeds synthetic fraud patterns and upserts them to the `suspicious-profiles` index.

    Each upserted vector represents one attacker agent scenario. The drift detector
    queries this index when evaluating whether an incoming transaction resembles
    a known synthetic fraud pattern.

    Args:
        openai_api_key: OpenAI API key. Falls back to `OPENAI_API_KEY` env var.
        pinecone_api_key: Pinecone API key. Falls back to `PINECONE_API_KEY` env var.
        dry_run: If True, computes embeddings but does not upsert to Pinecone.
        tokenizer: PIITokenizer instance for account ID tokenization.
    """

    def __init__(
        self,
        openai_api_key: str | None = None,
        pinecone_api_key: str | None = None,
        *,
        dry_run: bool | None = None,
        tokenizer: PIITokenizer | None = None,
    ) -> None:
        self._openai_key = openai_api_key or os.getenv("OPENAI_API_KEY", "")
        self._pc_key = pinecone_api_key or os.getenv("PINECONE_API_KEY", "")
        self._dry_run = (
            dry_run
            if dry_run is not None
            else os.getenv("SYNTHETIC_INJECTION_DRY_RUN", "false").strip().lower() == "true"
        )
        self._tokenizer = tokenizer or PIITokenizer()
        self._index: Any | None = None

    # ── Pinecone connection (lazy) ─────────────────────────────────────────────

    def _get_index(self) -> Any:
        if self._index is not None:
            return self._index
        try:
            from pinecone import Pinecone  # type: ignore[import]

            pc = Pinecone(api_key=self._pc_key)
            self._index = pc.Index(_PINECONE_INDEX_SUSPICIOUS)
        except ImportError:
            raise RuntimeError(
                "pinecone-client not installed. Run: pip install pinecone-client"
            )
        return self._index

    # ── Embedding ──────────────────────────────────────────────────────────────

    def _embed(self, text: str) -> list[float]:
        try:
            from openai import OpenAI  # type: ignore[import]

            client = OpenAI(api_key=self._openai_key)
            response = client.embeddings.create(
                model=_EMBEDDING_MODEL,
                input=text,
            )
            return response.data[0].embedding
        except ImportError:
            raise RuntimeError(
                "openai package not installed. Run: pip install openai"
            )

    # ── Scenario → embedding text ──────────────────────────────────────────────

    @staticmethod
    def _scenario_to_text(scenario: dict[str, Any]) -> str:
        """
        Serialize a scenario dict into a text blob for embedding.

        The text describes the attack pattern at a behavioral level — what
        kind of transactions are involved, what evasion tactics are used, and
        what detection signals are expected.
        """
        lines: list[str] = []

        attack_type = scenario.get("attack_type", "unknown")
        complexity = scenario.get("complexity", "medium")
        segment = scenario.get("target_segment", "retail_banking")

        lines.append(f"fraud type: {attack_type}")
        lines.append(f"complexity: {complexity}")
        lines.append(f"target segment: {segment}")

        evasion = scenario.get("evasion_tactics") or []
        if evasion:
            lines.append(f"evasion tactics: {', '.join(str(e) for e in evasion)}")

        signals = scenario.get("expected_detection_signals") or []
        if signals:
            lines.append(f"expected detection signals: {', '.join(str(s) for s in signals)}")

        tx_pattern = scenario.get("transaction_pattern") or {}
        if isinstance(tx_pattern, dict):
            if "amount_range" in tx_pattern:
                lines.append(f"transaction amount range: {tx_pattern['amount_range']}")
            if "frequency" in tx_pattern:
                lines.append(f"transaction frequency: {tx_pattern['frequency']}")
            if "channels" in tx_pattern:
                lines.append(f"channels used: {tx_pattern['channels']}")
            if "structuring" in tx_pattern:
                lines.append(f"structuring pattern: {tx_pattern['structuring']}")
            if "layering_hops" in tx_pattern:
                lines.append(f"layering hops: {tx_pattern['layering_hops']}")

        # Stringify any remaining keys
        for key, val in tx_pattern.items():
            if key not in {
                "amount_range", "frequency", "channels", "structuring", "layering_hops"
            }:
                lines.append(f"{key}: {val}")

        return "\n".join(lines)

    # ── Public API ─────────────────────────────────────────────────────────────

    def inject_scenario_profile(
        self,
        scenario: dict[str, Any],
        *,
        dag_run_id: str | None = None,
    ) -> InjectionResult:
        """
        Embed a synthetic fraud scenario and upsert it to the suspicious-profiles index.

        Args:
            scenario: Scenario dict from the attacker agent (ScenarioConfig.model_dump()).
            dag_run_id: Optional DAG run ID for traceability.

        Returns:
            InjectionResult with upsert outcome.
        """
        scenario_id = scenario.get("scenario_id", "unknown")
        attack_type = scenario.get("attack_type", "unknown")
        profile_vector_id = f"synthetic_{scenario_id}"

        embedding_text = self._scenario_to_text(scenario)
        vector = self._embed(embedding_text)

        # Hard Rule #3: synthetic=true is mandatory
        # Hard Rule #4: no raw account IDs; scenario_id is a UUID (not PII)
        metadata: dict[str, Any] = {
            "scenario_id": scenario_id,
            "attack_type": attack_type,
            "complexity": scenario.get("complexity", "medium"),
            "target_segment": scenario.get("target_segment", "retail_banking"),
            "label": "synthetic_fraud",
            "synthetic": "true",   # Hard Rule #3
            "origin": "red_team",
            "injected_at_ms": int(time.time() * 1000),
        }
        if dag_run_id:
            metadata["dag_run_id"] = dag_run_id

        if self._dry_run:
            log.info(
                "synthetic_profile_injection_dry_run",
                scenario_id=scenario_id,
                attack_type=attack_type,
                embedding_dim=len(vector),
                synthetic=True,
            )
            return InjectionResult(
                scenario_id=scenario_id,
                attack_type=attack_type,
                profile_vector_id=profile_vector_id,
                upserted=False,
                dry_run=True,
            )

        try:
            index = self._get_index()
            index.upsert(vectors=[(profile_vector_id, vector, metadata)])
            log.info(
                "synthetic_profile_upserted",
                scenario_id=scenario_id,
                attack_type=attack_type,
                index=_PINECONE_INDEX_SUSPICIOUS,
                synthetic=True,
            )
            return InjectionResult(
                scenario_id=scenario_id,
                attack_type=attack_type,
                profile_vector_id=profile_vector_id,
                upserted=True,
                dry_run=False,
            )
        except Exception as exc:
            log.error(
                "synthetic_profile_upsert_failed",
                scenario_id=scenario_id,
                error=str(exc),
            )
            return InjectionResult(
                scenario_id=scenario_id,
                attack_type=attack_type,
                profile_vector_id=profile_vector_id,
                upserted=False,
                dry_run=False,
                error=str(exc),
            )

    def inject_batch(
        self,
        scenarios: list[dict[str, Any]],
        *,
        dag_run_id: str | None = None,
    ) -> list[InjectionResult]:
        """
        Inject multiple synthetic scenario profiles.

        Args:
            scenarios: List of scenario dicts.
            dag_run_id: Optional DAG run ID for traceability.

        Returns:
            List of InjectionResult, one per scenario.
        """
        results: list[InjectionResult] = []
        for scenario in scenarios:
            result = self.inject_scenario_profile(scenario, dag_run_id=dag_run_id)
            results.append(result)
        return results

    def delete_scenario_profile(self, scenario_id: str) -> bool:
        """
        Remove a synthetic profile from the index (e.g., for test cleanup).

        Hard Rule #7 note: This only removes from Pinecone (mutable vector store).
        The immutable audit record in `synthetic_audit` Kafka topic is never deleted.

        Returns:
            True if deletion was attempted (not in dry-run).
        """
        profile_vector_id = f"synthetic_{scenario_id}"
        if self._dry_run:
            log.info(
                "synthetic_profile_delete_dry_run",
                profile_vector_id=profile_vector_id,
            )
            return False

        try:
            index = self._get_index()
            index.delete(ids=[profile_vector_id])
            log.info("synthetic_profile_deleted", profile_vector_id=profile_vector_id)
            return True
        except Exception as exc:
            log.error(
                "synthetic_profile_delete_failed",
                profile_vector_id=profile_vector_id,
                error=str(exc),
            )
            return False

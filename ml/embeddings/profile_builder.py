"""
profile_builder — Behavioral Profile Builder
=============================================

Generates per-user behavioral embeddings from clean transaction history and
upserts them to the Pinecone `clean-profiles` index.

Embedding model: OpenAI `text-embedding-3-large` (3072 dimensions).
Pinecone metadata: {account_id (tokenized), label, last_updated, transaction_count}.

Staleness policy:
  - Profiles older than PROFILE_STALENESS_DAYS (default 30) emit a warning.
  - Nightly profile_refresh_dag triggers rebuilds for stale or high-volume accounts.

Multi-tenancy: all Pinecone calls pass `namespace=_pinecone_namespace(tenant_id)`.
  - "default" tenant maps to namespace="" (Pinecone default namespace, legacy compat).
  - All other tenants use the tenant_id string as the Pinecone namespace.

Hard Rule #4: All account identifiers are tokenized by PIITokenizer before
any call to OpenAI or Pinecone.
"""

import os
import time
from dataclasses import dataclass, field
from typing import Any

import structlog

from ml.embeddings.pii_tokenizer import PIITokenizer

log = structlog.get_logger(__name__)

PROFILE_STALENESS_DAYS: int = int(os.getenv("PROFILE_STALENESS_DAYS", "30"))
_STALENESS_MS: int = PROFILE_STALENESS_DAYS * 86_400 * 1_000
_EMBEDDING_MODEL: str = os.getenv("OPENAI_EMBEDDING_MODEL", "text-embedding-3-large")
_PINECONE_INDEX_CLEAN: str = os.getenv("PINECONE_INDEX_CLEAN", "clean-profiles")
_EMBEDDING_DIM: int = 3072  # text-embedding-3-large fixed dimension


@dataclass
class ProfileUpsertResult:
    """Result of a single profile upsert operation."""

    account_token: str
    label: str
    upserted: bool
    dry_run: bool
    transaction_count: int
    upserted_at_ms: int = field(default_factory=lambda: int(time.time() * 1000))
    error: str | None = None


class ProfileBuilder:
    """
    Builds behavioral embeddings for clean (legitimate) user profiles.

    Args:
        openai_api_key: OpenAI API key. Falls back to `OPENAI_API_KEY` env var.
        pinecone_api_key: Pinecone API key. Falls back to `PINECONE_API_KEY` env var.
        pinecone_environment: Pinecone environment. Falls back to env var.
        dry_run: If True, computes embeddings but does not upsert to Pinecone.
        tokenizer: PIITokenizer instance. A default instance is created if not provided.
    """

    def __init__(
        self,
        openai_api_key: str | None = None,
        pinecone_api_key: str | None = None,
        pinecone_environment: str | None = None,
        *,
        dry_run: bool | None = None,
        tokenizer: PIITokenizer | None = None,
    ) -> None:
        self._openai_key = openai_api_key or os.getenv("OPENAI_API_KEY", "")
        self._pc_key = pinecone_api_key or os.getenv("PINECONE_API_KEY", "")
        self._pc_env = pinecone_environment or os.getenv("PINECONE_ENVIRONMENT", "")
        self._dry_run = (
            dry_run
            if dry_run is not None
            else os.getenv("SYNTHETIC_INJECTION_DRY_RUN", "false").strip().lower() == "true"
        )
        self._tokenizer = tokenizer or PIITokenizer()
        self._index: Any | None = None  # lazy Pinecone index handle

    # ── Pinecone connection (lazy) ─────────────────────────────────────────────

    def _get_index(self) -> Any:
        if self._index is not None:
            return self._index
        try:
            from pinecone import Pinecone  # type: ignore[import]

            pc = Pinecone(api_key=self._pc_key)
            self._index = pc.Index(_PINECONE_INDEX_CLEAN)
        except ImportError:
            raise RuntimeError(
                "pinecone-client not installed. Run: pip install pinecone-client"
            )
        return self._index

    # ── Embedding ──────────────────────────────────────────────────────────────

    def _embed(self, text: str) -> list[float]:
        """Call OpenAI text-embedding-3-large and return the embedding vector."""
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

    # ── Profile statistics computation ────────────────────────────────────────

    @staticmethod
    def compute_behavioral_stats(
        transactions: list[dict[str, Any]],
    ) -> dict[str, Any]:
        """
        Compute a statistical summary of a user's transaction history.

        Args:
            transactions: List of transaction dicts with at minimum:
                {amount, currency, merchant_id, timestamp (ms), channel, metadata}.

        Returns:
            Statistical summary suitable for embedding text generation.
        """
        if not transactions:
            return {"transaction_count": 0}

        amounts = [float(t.get("amount", 0)) for t in transactions]
        amounts.sort()
        n = len(amounts)

        avg_amount = sum(amounts) / n
        median_amount = amounts[n // 2] if n % 2 else (amounts[n // 2 - 1] + amounts[n // 2]) / 2
        max_amount = amounts[-1]

        # Channel distribution
        channels: dict[str, int] = {}
        for t in transactions:
            ch = t.get("channel", "unknown")
            channels[ch] = channels.get(ch, 0) + 1

        # Hour of day distribution (from timestamp_ms)
        hour_dist: dict[int, int] = {}
        for t in transactions:
            ts_ms = t.get("timestamp", 0)
            if ts_ms:
                hour = (ts_ms // 3_600_000) % 24
                hour_dist[hour] = hour_dist.get(hour, 0) + 1

        # Currency (most common)
        currency_counts: dict[str, int] = {}
        for t in transactions:
            cur = t.get("currency", "USD")
            currency_counts[cur] = currency_counts.get(cur, 0) + 1
        primary_currency = max(currency_counts, key=lambda k: currency_counts[k])

        # Merchant category hints from metadata
        merchant_categories: list[str] = []
        seen_merchants: set[str] = set()
        for t in transactions:
            mid = t.get("merchant_id", "")
            if mid and mid not in seen_merchants:
                seen_merchants.add(mid)
                category = (t.get("metadata") or {}).get("category", "")
                if category:
                    merchant_categories.append(category)

        # Geo patterns from metadata
        geo_countries: list[str] = []
        seen_countries: set[str] = set()
        for t in transactions:
            country = (t.get("metadata") or {}).get("geo_country", "")
            if country and country not in seen_countries:
                seen_countries.add(country)
                geo_countries.append(country)

        return {
            "transaction_count": n,
            "avg_amount": round(avg_amount, 2),
            "median_amount": round(median_amount, 2),
            "max_amount": round(max_amount, 2),
            "channels": channels,
            "hour_distribution": hour_dist,
            "currency": primary_currency,
            "merchant_categories": merchant_categories[:20],
            "geo_countries": geo_countries[:10],
        }

    # ── Public API ─────────────────────────────────────────────────────────────

    def build_profile(
        self,
        account_id: str,
        transactions: list[dict[str, Any]],
        *,
        tenant_id: str = "default",
    ) -> ProfileUpsertResult:
        """
        Build and upsert a behavioral profile for the given account.

        Args:
            account_id: Raw account identifier (will be tokenized before use).
            transactions: List of clean transaction dicts from the account history.
            tenant_id: Tenant namespace for Pinecone isolation. Defaults to "default".

        Returns:
            ProfileUpsertResult with upsert outcome and metadata.
        """
        account_token = self._tokenizer.tokenize(account_id)
        stats = self.compute_behavioral_stats(transactions)
        transaction_count = stats.get("transaction_count", 0)

        if transaction_count == 0:
            log.warning(
                "profile_build_skipped_no_transactions",
                account_token=account_token,
                tenant_id=tenant_id,
            )
            return ProfileUpsertResult(
                account_token=account_token,
                label="legitimate",
                upserted=False,
                dry_run=self._dry_run,
                transaction_count=0,
                error="no transactions provided",
            )

        embedding_text = self._tokenizer.build_embedding_text(account_token, stats)
        vector = self._embed(embedding_text)

        metadata: dict[str, Any] = {
            "account_id": account_token,  # tokenized — Hard Rule #4
            "label": "legitimate",
            "last_updated": int(time.time() * 1000),
            "transaction_count": transaction_count,
            "tenant_id": tenant_id,
        }

        if self._dry_run:
            log.info(
                "profile_build_dry_run",
                account_token=account_token,
                tenant_id=tenant_id,
                transaction_count=transaction_count,
                embedding_dim=len(vector),
            )
            return ProfileUpsertResult(
                account_token=account_token,
                label="legitimate",
                upserted=False,
                dry_run=True,
                transaction_count=transaction_count,
            )

        namespace = _pinecone_namespace(tenant_id)
        try:
            index = self._get_index()
            index.upsert(vectors=[(account_token, vector, metadata)], namespace=namespace)
            log.info(
                "profile_upserted",
                account_token=account_token,
                index=_PINECONE_INDEX_CLEAN,
                namespace=namespace,
                tenant_id=tenant_id,
                transaction_count=transaction_count,
            )
            return ProfileUpsertResult(
                account_token=account_token,
                label="legitimate",
                upserted=True,
                dry_run=False,
                transaction_count=transaction_count,
            )
        except Exception as exc:
            log.error(
                "profile_upsert_failed",
                account_token=account_token,
                tenant_id=tenant_id,
                error=str(exc),
            )
            return ProfileUpsertResult(
                account_token=account_token,
                label="legitimate",
                upserted=False,
                dry_run=False,
                transaction_count=transaction_count,
                error=str(exc),
            )

    def build_profiles_batch(
        self,
        accounts: list[tuple[str, list[dict[str, Any]]]],
        *,
        tenant_id: str = "default",
    ) -> list[ProfileUpsertResult]:
        """
        Build and upsert profiles for multiple accounts.

        Args:
            accounts: List of (account_id, transactions) tuples.
            tenant_id: Tenant namespace for Pinecone isolation.

        Returns:
            List of ProfileUpsertResult, one per account.
        """
        results: list[ProfileUpsertResult] = []
        for account_id, transactions in accounts:
            result = self.build_profile(account_id, transactions, tenant_id=tenant_id)
            results.append(result)
        return results

    def check_staleness(
        self,
        account_id: str,
        *,
        tenant_id: str = "default",
    ) -> dict[str, Any]:
        """
        Query Pinecone to check if a profile exists and whether it is stale.

        Args:
            account_id: Raw account identifier (will be tokenized).
            tenant_id: Tenant namespace for Pinecone isolation.

        Returns:
            {exists, stale, last_updated_ms, age_days, account_token}
        """
        account_token = self._tokenizer.tokenize(account_id)
        namespace = _pinecone_namespace(tenant_id)

        if self._dry_run:
            return {
                "exists": False,
                "stale": True,
                "last_updated_ms": None,
                "age_days": None,
                "account_token": account_token,
            }

        try:
            index = self._get_index()
            result = index.fetch(ids=[account_token], namespace=namespace)
            vectors = result.get("vectors", {})

            if account_token not in vectors:
                return {
                    "exists": False,
                    "stale": True,
                    "last_updated_ms": None,
                    "age_days": None,
                    "account_token": account_token,
                }

            metadata = vectors[account_token].get("metadata", {})
            last_updated_ms = metadata.get("last_updated", 0)
            now_ms = int(time.time() * 1000)
            age_ms = now_ms - last_updated_ms
            stale = age_ms > _STALENESS_MS

            if stale:
                log.warning(
                    "profile_stale",
                    account_token=account_token,
                    age_days=age_ms // 86_400_000,
                    staleness_threshold_days=PROFILE_STALENESS_DAYS,
                )

            return {
                "exists": True,
                "stale": stale,
                "last_updated_ms": last_updated_ms,
                "age_days": age_ms // 86_400_000,
                "account_token": account_token,
            }
        except Exception as exc:
            log.error(
                "staleness_check_failed",
                account_token=account_token,
                error=str(exc),
            )
            return {
                "exists": False,
                "stale": True,
                "last_updated_ms": None,
                "age_days": None,
                "account_token": account_token,
                "error": str(exc),
            }


def _pinecone_namespace(tenant_id: str) -> str:
    """Return the Pinecone namespace for a tenant. 'default' maps to '' for legacy compat."""
    return "" if tenant_id == "default" else tenant_id

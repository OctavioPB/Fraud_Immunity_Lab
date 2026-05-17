"""
profile_refresh_dag — Nightly Behavioral Profile Refresh
========================================================

Runs nightly to:
  1. Identify accounts with > 100 new transactions since last profile update.
  2. Identify profiles that are stale (> PROFILE_STALENESS_DAYS old).
  3. Rebuild and upsert refreshed embeddings for eligible accounts.
  4. Alert on any account whose profile remains stale after refresh.

Tasks:
  identify_refresh_candidates   ← query Pinecone + transaction counts for staleness
      ↓
  rebuild_stale_profiles        ← call ProfileBuilder for each candidate account
      ↓
  inject_new_synthetic_profiles ← upsert attacker agent outputs from last 24h
      ↓
  report_profile_health         ← log coverage metrics; alert on persistent staleness

Schedule: Daily at 01:00 UTC (before model_retraining_trigger at 03:00).

Tags: ["ml"] — runs independently of red_team DAGs.

Hard Rules enforced: #3, #4
"""

import os
from typing import Any

from airflow.decorators import dag, task
from airflow.utils.dates import days_ago

from red_team.dags.shared.dag_utils import get_detection_recall_threshold

_STALENESS_DAYS: int = int(os.getenv("PROFILE_STALENESS_DAYS", "30"))
_HIGH_ACTIVITY_THRESHOLD: int = int(
    os.getenv("PROFILE_HIGH_ACTIVITY_TX_THRESHOLD", "100")
)

doc_md = """
## profile_refresh_dag

**Purpose**: Keep behavioral profiles fresh in the Pinecone `clean-profiles` index.
Stale profiles degrade drift detection recall (Hard Rule #6 dependency).

**Schedule**: Daily at 01:00 UTC.

**Staleness threshold**: `PROFILE_STALENESS_DAYS` (default 30).
High-activity threshold: `PROFILE_HIGH_ACTIVITY_TX_THRESHOLD` (default 100 new txns).

**Hard Rules enforced**:
- #3: All synthetic profiles carry `synthetic: true`.
- #4: Account IDs are tokenized via PIITokenizer before any Pinecone call.

**Dependencies**:
- Airflow Variables: `PROFILE_STALENESS_DAYS`, `PROFILE_HIGH_ACTIVITY_TX_THRESHOLD`
- Airflow Connections: `openai_default`, Pinecone (via env vars in Sprint 5)
- Sprint 6+: Neo4j connection for account activity counts
"""


@dag(
    dag_id="profile_refresh_dag",
    schedule_interval="0 1 * * *",  # daily 01:00 UTC
    start_date=days_ago(1),
    catchup=False,
    max_active_runs=1,
    tags=["ml"],
    doc_md=doc_md,
    default_args={"retries": 2, "retry_delay": 120},
)
def profile_refresh_dag() -> None:

    @task(task_id="identify_refresh_candidates")
    def identify_refresh_candidates() -> dict[str, Any]:
        """
        Identify accounts that need profile refresh:
          - Stale profiles (last_updated > PROFILE_STALENESS_DAYS ago).
          - High-activity accounts (> PROFILE_HIGH_ACTIVITY_TX_THRESHOLD new transactions).

        Sprint 5: uses stub account list from env/config.
        Sprint 6: queries Neo4j for transaction counts per account.
        Sprint 7: integrates with Immunity Score ModelFreshness component.

        Returns:
            {stale_count, high_activity_count, candidate_tokens, total_profiles_checked}
        """
        import structlog
        from ml.embeddings.pii_tokenizer import PIITokenizer

        log = structlog.get_logger(__name__)
        tokenizer = PIITokenizer()

        # Sprint 5 stub — in production this queries the Pinecone index stats
        # and Neo4j transaction counts per account.
        stub_account_ids: list[str] = [
            os.getenv(f"STUB_ACCOUNT_{i}", f"stub-account-{i:04d}")
            for i in range(int(os.getenv("STUB_PROFILE_REFRESH_ACCOUNTS", "10")))
        ]

        candidate_tokens: list[str] = []
        stale_count = 0
        high_activity_count = 0

        for account_id in stub_account_ids:
            account_token = tokenizer.tokenize(account_id)
            # Sprint 5 stub: treat all stub accounts as stale for demonstration
            # Sprint 6: replace with real staleness/activity checks
            candidate_tokens.append(account_token)
            stale_count += 1

        log.info(
            "refresh_candidates_identified",
            stale_count=stale_count,
            high_activity_count=high_activity_count,
            total_candidates=len(candidate_tokens),
        )

        return {
            "stale_count": stale_count,
            "high_activity_count": high_activity_count,
            "candidate_tokens": candidate_tokens,
            "total_profiles_checked": len(stub_account_ids),
        }

    @task(task_id="rebuild_stale_profiles")
    def rebuild_stale_profiles(candidates: dict[str, Any]) -> dict[str, Any]:
        """
        Rebuild behavioral profiles for all candidate accounts.

        Sprint 5: generates synthetic transaction histories for stub accounts.
        Sprint 6: fetches real transaction histories from Kafka/PostgreSQL.

        Returns:
            {rebuilt_count, skipped_count, error_count, account_tokens_rebuilt}
        """
        import random
        import structlog
        from ml.embeddings.profile_builder import ProfileBuilder

        log = structlog.get_logger(__name__)
        builder = ProfileBuilder()
        candidate_tokens = candidates.get("candidate_tokens", [])

        rebuilt: list[str] = []
        skipped = 0
        errors = 0

        for account_token in candidate_tokens:
            try:
                # Sprint 5 stub: generate synthetic transaction history
                # Sprint 6: replace with real history from data warehouse
                transactions = _generate_stub_transactions(account_token)

                # Note: account_token is already a PIITokenizer-generated token;
                # ProfileBuilder.build_profile() calls tokenize() internally,
                # so we pass it as-is and it will double-hash (stable operation).
                result = builder.build_profile(account_token, transactions)

                if result.upserted or result.dry_run:
                    rebuilt.append(account_token)
                else:
                    skipped += 1

                log.info(
                    "profile_rebuilt",
                    account_token=account_token,
                    transaction_count=result.transaction_count,
                    upserted=result.upserted,
                )
            except Exception as exc:
                log.error(
                    "profile_rebuild_failed",
                    account_token=account_token,
                    error=str(exc),
                )
                errors += 1

        log.info(
            "profile_rebuild_summary",
            rebuilt_count=len(rebuilt),
            skipped_count=skipped,
            error_count=errors,
        )

        return {
            "rebuilt_count": len(rebuilt),
            "skipped_count": skipped,
            "error_count": errors,
            "account_tokens_rebuilt": rebuilt,
        }

    @task(task_id="inject_new_synthetic_profiles")
    def inject_new_synthetic_profiles() -> dict[str, Any]:
        """
        Upsert synthetic fraud profiles for attacker agent outputs generated
        in the last 24 hours.

        Sprint 5: reads from a stub scenario list.
        Sprint 6: queries the `synthetic_audit` Kafka topic for recent scenario IDs.

        Returns:
            {injected_count, failed_count}
        """
        import structlog
        from ml.embeddings.synthetic_profile_injector import SyntheticProfileInjector

        log = structlog.get_logger(__name__)
        injector = SyntheticProfileInjector()

        # Sprint 5 stub: generate representative scenarios for each attack type
        stub_scenarios = _generate_stub_scenarios()

        injected = 0
        failed = 0

        for scenario in stub_scenarios:
            result = injector.inject_scenario_profile(scenario)
            if result.upserted or result.dry_run:
                injected += 1
            else:
                failed += 1
                log.warning(
                    "synthetic_profile_injection_failed",
                    scenario_id=scenario.get("scenario_id", "unknown"),
                    error=result.error,
                )

        log.info(
            "synthetic_profile_injection_summary",
            injected_count=injected,
            failed_count=failed,
        )

        return {"injected_count": injected, "failed_count": failed}

    @task(task_id="report_profile_health")
    def report_profile_health(
        rebuild_result: dict[str, Any],
        injection_result: dict[str, Any],
        candidates: dict[str, Any],
    ) -> dict[str, Any]:
        """
        Log final profile health metrics.
        Alert (via structlog warning) on persistent staleness or injection failures.

        Returns:
            Health summary dict for monitoring.
        """
        import structlog

        log = structlog.get_logger(__name__)

        recall_threshold = get_detection_recall_threshold()
        error_count = rebuild_result.get("error_count", 0)
        rebuilt_count = rebuild_result.get("rebuilt_count", 0)
        failed_injections = injection_result.get("failed_count", 0)
        stale_count = candidates.get("stale_count", 0)

        if error_count > 0:
            log.warning(
                "profile_rebuild_errors_detected",
                error_count=error_count,
                action_required=(
                    "Investigate failed profile rebuilds. Stale profiles reduce "
                    "detection recall, violating Hard Rule #6 (recall >= threshold)."
                ),
            )

        if failed_injections > 0:
            log.warning(
                "synthetic_profile_injection_failures",
                failed_count=failed_injections,
                action_required=(
                    "Failed synthetic profile injections reduce suspicious-profile "
                    "coverage, degrading drift detector recall."
                ),
            )

        health = {
            "stale_profiles_found": stale_count,
            "profiles_rebuilt": rebuilt_count,
            "rebuild_errors": error_count,
            "synthetic_profiles_injected": injection_result.get("injected_count", 0),
            "synthetic_injection_failures": failed_injections,
            "detection_recall_threshold": recall_threshold,
            "health_status": (
                "degraded"
                if (error_count > 0 or failed_injections > 0)
                else "healthy"
            ),
        }

        log.info("profile_health_report", **health)
        return health

    # ── Stub helpers (Sprint 5 — replaced by real data sources in Sprint 6) ────

    def _generate_stub_transactions(account_token: str) -> list[dict]:
        import random
        import time as t

        n = random.randint(50, 200)
        now_ms = int(t.time() * 1000)
        channels = ["card_present", "card_not_present", "ach", "p2p"]
        return [
            {
                "transaction_id": f"stub_{account_token[:8]}_{i}",
                "account_id": account_token,
                "amount": round(random.uniform(5.0, 2000.0), 2),
                "currency": "USD",
                "merchant_id": f"merchant_{random.randint(1, 500):04d}",
                "timestamp": now_ms - random.randint(0, 30 * 86_400_000),
                "channel": random.choice(channels),
                "metadata": {
                    "category": random.choice(
                        ["retail", "dining", "travel", "grocery", "utilities"]
                    ),
                    "geo_country": random.choice(["US", "CA", "GB", "MX"]),
                },
            }
            for i in range(n)
        ]

    def _generate_stub_scenarios() -> list[dict]:
        import uuid

        attack_types = [
            "phishing",
            "money_laundering",
            "account_takeover",
            "smurfing",
            "credential_stuffing",
        ]
        return [
            {
                "scenario_id": str(uuid.uuid4()),
                "attack_type": at,
                "complexity": "high",
                "target_segment": "retail_banking",
                "evasion_tactics": ["vpn", "timing_randomization"],
                "expected_detection_signals": ["behavioral_drift", "geo_anomaly"],
                "transaction_pattern": {
                    "avg_amount": 500.0,
                    "frequency": "burst",
                    "channels": ["card_not_present"],
                },
                "synthetic": True,
                "origin": "red_team",
            }
            for at in attack_types
        ]

    # ── Task wiring ────────────────────────────────────────────────────────────
    candidates = identify_refresh_candidates()
    rebuild_result = rebuild_stale_profiles(candidates)
    injection_result = inject_new_synthetic_profiles()
    report_profile_health(rebuild_result, injection_result, candidates)


profile_refresh_dag_instance = profile_refresh_dag()

"""
Kafka injector — translates a ScenarioConfig into concrete synthetic Kafka events.

Each attack type maps to a specific event mix:
  phishing / credential_stuffing → LoginEvents (failures + success) + TransactionEvents
  money_laundering / mule_account / smurfing → TransactionEvents (multi-hop chain)
  account_takeover → DeviceEvent (fingerprint_changed) + LoginEvent + TransactionEvents
  card_fraud → TransactionEvents (card-testing then escalation)
  Everything else → TransactionEvents

Hard Rule #3: the injector delegates to SyntheticProducer which always tags
every event with {"synthetic": "true", "origin": "red_team"}.
Hard Rule (dry-run): SyntheticProducer reads SYNTHETIC_INJECTION_DRY_RUN.
"""

import time
from dataclasses import dataclass
from typing import Any

import structlog

from ingestion.producers.synthetic_producer import SyntheticProducer

logger = structlog.get_logger(__name__)

_ATTACK_TYPE_TO_EVENTS: dict[str, dict[str, int]] = {
    "phishing": {"logins": 4, "transactions": 3, "devices": 1},
    "credential_stuffing": {"logins": 20, "transactions": 5, "devices": 2},
    "money_laundering": {"logins": 0, "transactions": 8, "devices": 0},
    "mule_account": {"logins": 2, "transactions": 6, "devices": 1},
    "smurfing": {"logins": 0, "transactions": 10, "devices": 0},
    "account_takeover": {"logins": 3, "transactions": 4, "devices": 2},
    "card_fraud": {"logins": 0, "transactions": 6, "devices": 1},
    "synthetic_identity": {"logins": 2, "transactions": 8, "devices": 1},
    "first_party_fraud": {"logins": 1, "transactions": 10, "devices": 0},
    "friendly_fraud": {"logins": 1, "transactions": 5, "devices": 0},
}

_DEFAULT_EVENT_MIX = {"logins": 2, "transactions": 5, "devices": 1}


@dataclass
class InjectionResult:
    scenario_id: str
    attack_type: str
    logins_produced: int
    transactions_produced: int
    devices_produced: int
    injected_at_ms: int
    dry_run: bool

    @property
    def total_events(self) -> int:
        return self.logins_produced + self.transactions_produced + self.devices_produced


def inject_scenario(
    scenario_id: str,
    scenario_dict: dict[str, Any],
    dag_run_id: str | None = None,
) -> InjectionResult:
    """
    Translate a ScenarioConfig dict into Kafka events for the three ingestion topics.

    Extra metadata added to every event:
      - scenario_id: links events back to the scenario that generated them
      - dag_run_id: traceability to the Airflow run
      - attack_type: for downstream detection labelling

    Full event payloads go to Kafka; only the InjectionResult summary is returned.
    """
    attack_type: str = scenario_dict.get("attack_type", "unknown")
    mix = _ATTACK_TYPE_TO_EVENTS.get(attack_type, _DEFAULT_EVENT_MIX)

    extra_meta: dict[str, str] = {
        "scenario_id": scenario_id,
        "attack_type": attack_type,
    }
    if dag_run_id:
        extra_meta["dag_run_id"] = dag_run_id

    producer = SyntheticProducer()

    # Use a shared account pool so events across types are linked
    import uuid
    account_pool = [str(uuid.uuid4()) for _ in range(max(3, mix["transactions"] // 2))]

    # ── Inject events by type ─────────────────────────────────────────────────

    logins_n = _inject_logins(producer, attack_type, mix["logins"], account_pool, extra_meta)
    txns_n = _inject_transactions(producer, attack_type, mix["transactions"], account_pool, extra_meta)
    devices_n = _inject_devices(producer, attack_type, mix["devices"], account_pool, extra_meta)

    injected_at_ms = int(time.time() * 1000)

    result = InjectionResult(
        scenario_id=scenario_id,
        attack_type=attack_type,
        logins_produced=logins_n,
        transactions_produced=txns_n,
        devices_produced=devices_n,
        injected_at_ms=injected_at_ms,
        dry_run=producer._dry_run,
    )

    logger.info(
        "scenario_injected",
        scenario_id=scenario_id,
        attack_type=attack_type,
        total_events=result.total_events,
        dry_run=result.dry_run,
        injected_at_ms=injected_at_ms,
    )
    return result


def _inject_logins(
    producer: SyntheticProducer,
    attack_type: str,
    count: int,
    account_pool: list[str],
    extra_meta: dict[str, str],
) -> int:
    import random

    if count == 0:
        return 0

    produced = 0
    for i in range(count):
        # Model attack-specific login patterns
        if attack_type in ("credential_stuffing", "phishing"):
            # Many failures before one success
            success = i == count - 1
        elif attack_type == "account_takeover":
            success = i > 0  # first attempt may fail MFA
        else:
            success = random.random() > 0.3

        producer.produce_login(
            account_id=random.choice(account_pool),
            success=success,
            extra_metadata=extra_meta,
        )
        produced += 1

    return produced


def _inject_transactions(
    producer: SyntheticProducer,
    attack_type: str,
    count: int,
    account_pool: list[str],
    extra_meta: dict[str, str],
) -> int:
    import random

    if count == 0:
        return 0

    produced = 0
    for i in range(count):
        # Attack-specific amount patterns
        if attack_type == "card_fraud" and i < 3:
            amount = round(random.uniform(0.01, 1.99), 2)  # card testing
        elif attack_type == "smurfing":
            amount = round(random.uniform(7500, 9800), 2)  # below CTR
        elif attack_type == "money_laundering":
            amount = round(random.uniform(50000, 200000), 2)  # large layering
        else:
            amount = None  # random

        channel = "card_not_present" if attack_type in ("card_fraud", "phishing") else None

        record = producer.build_transaction(
            account_id=random.choice(account_pool),
            amount=amount,
            extra_metadata=extra_meta,
        )
        if channel:
            record["channel"] = channel

        producer.produce_transaction(
            account_id=record["account_id"],
            amount=record["amount"],
            extra_metadata=extra_meta,
        )
        produced += 1

    return produced


def _inject_devices(
    producer: SyntheticProducer,
    attack_type: str,
    count: int,
    account_pool: list[str],
    extra_meta: dict[str, str],
) -> int:
    import random

    if count == 0:
        return 0

    produced = 0
    for i in range(count):
        if attack_type == "account_takeover":
            event_type = "fingerprint_changed" if i == 0 else "registered"
        elif attack_type == "credential_stuffing":
            event_type = "seen"  # many new devices seen
        else:
            event_type = None

        producer.produce_device(
            account_id=random.choice(account_pool),
            event_type=event_type,
            extra_metadata=extra_meta,
        )
        produced += 1

    return produced

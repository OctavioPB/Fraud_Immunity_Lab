"""
observability — Shared Prometheus Metrics Registry
===================================================

Single source of truth for all Prometheus metrics. Import and use these
objects from any api/ module to record observations.

Naming convention:  fil_{subsystem}_{metric}_{unit}
  fil = Fraud Immunity Lab prefix
  subsystem: detection, score, llm, kafka, api
  unit: seconds, total, usd

Usage:
    from api.observability import DETECTION_LATENCY, LLM_COST_USD_TOTAL
    DETECTION_LATENCY.labels(tenant_id="acme").observe(0.045)
    LLM_COST_USD_TOTAL.labels(tenant_id="acme", model="gpt-4o").inc(0.012)
"""

from prometheus_client import (
    CollectorRegistry,
    Counter,
    Gauge,
    Histogram,
)

# Shared registry — imported by api/routers/metrics.py for the /metrics endpoint
registry = CollectorRegistry()

# ── Detection latency ─────────────────────────────────────────────────────────

DETECTION_LATENCY = Histogram(
    "fil_detection_latency_seconds",
    "End-to-end drift detection latency in seconds (Pinecone query + cosine similarity)",
    ["tenant_id"],
    buckets=[0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0],
    registry=registry,
)

# ── Immunity score computation time ──────────────────────────────────────────

SCORE_COMPUTATION_SECONDS = Histogram(
    "fil_score_computation_seconds",
    "Time to compute the full Immunity Score (all components)",
    ["tenant_id"],
    buckets=[0.01, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5],
    registry=registry,
)

# ── LLM cost tracking ─────────────────────────────────────────────────────────

LLM_COST_USD_TOTAL = Counter(
    "fil_llm_cost_usd_total",
    "Cumulative OpenAI API cost in USD since process start",
    ["tenant_id", "model"],
    registry=registry,
)

LLM_TOKENS_TOTAL = Counter(
    "fil_llm_tokens_total",
    "Cumulative token count (prompt + completion) since process start",
    ["tenant_id", "model", "token_type"],
    registry=registry,
)

LLM_CALLS_TOTAL = Counter(
    "fil_llm_calls_total",
    "Total LLM API calls since process start",
    ["tenant_id", "model"],
    registry=registry,
)

# ── Budget alerting ───────────────────────────────────────────────────────────

LLM_BUDGET_FRACTION = Gauge(
    "fil_llm_budget_fraction",
    "Current monthly LLM spend as a fraction of the configured budget (0.0–1.0+)",
    ["tenant_id"],
    registry=registry,
)

# ── Kafka consumer lag ────────────────────────────────────────────────────────

CONSUMER_LAG = Gauge(
    "fil_consumer_lag_messages",
    "Consumer lag in messages per topic-partition",
    ["topic", "partition"],
    registry=registry,
)

CONSUMER_LAG_ALERT = Gauge(
    "fil_consumer_lag_alert",
    "1 if consumer lag exceeds alert threshold, 0 otherwise",
    ["topic"],
    registry=registry,
)

# ── Event processing ──────────────────────────────────────────────────────────

EVENTS_PROCESSED = Counter(
    "fil_events_processed_total",
    "Total events successfully processed per topic",
    ["topic"],
    registry=registry,
)

DLQ_EVENTS = Counter(
    "fil_dlq_events_total",
    "Total events routed to dead-letter topic",
    ["topic"],
    registry=registry,
)

# ── API rate limiting ─────────────────────────────────────────────────────────

RATE_LIMIT_EXCEEDED = Counter(
    "fil_rate_limit_exceeded_total",
    "Total requests rejected by the rate limiter",
    ["tenant_id", "bucket"],
    registry=registry,
)

# ── Scrape metadata ───────────────────────────────────────────────────────────

SCRAPE_TIMESTAMP = Gauge(
    "fil_metrics_last_scrape_timestamp_seconds",
    "Unix timestamp of the last successful metrics scrape",
    registry=registry,
)

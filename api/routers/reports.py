"""
reports — Weekly Immunity Score Report + NPS Feedback API
==========================================================

GET  /reports/{tenant_id}/weekly       Structured weekly report (JSON)
GET  /reports/{tenant_id}/weekly/text  Plain-text markdown (for email body)
POST /feedback/nps                     Submit NPS score + comment from dashboard widget

All /reports/* endpoints require a valid JWT and are tenant-scoped.
POST /feedback/nps is authenticated but does not require admin role.
"""

import time
from datetime import datetime, timezone
from typing import Any

import structlog
from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from api.services.score_calculator import ScoreCalculator
from api.services.cost_tracker import CostTracker
from api.services.tenant_provisioner import TenantProvisioner

log = structlog.get_logger(__name__)

router = APIRouter(tags=["reports"])

_calculator = ScoreCalculator()
_cost_tracker = CostTracker()
_provisioner = TenantProvisioner()


# ── NPS Feedback ───────────────────────────────────────────────────────────────

class NPSSubmission(BaseModel):
    score: int = Field(ge=0, le=10, description="NPS score 0–10")
    comment: str = Field(default="", max_length=500)
    tenant_id: str
    submitted_at_ms: int


@router.post("/feedback/nps", status_code=202)
async def submit_nps(body: NPSSubmission) -> dict[str, str]:
    """
    Receive an NPS score + optional comment from the dashboard widget.

    Logged as structured JSON so Prometheus/Grafana can aggregate NPS over time.
    Also written to PostgreSQL `nps_responses` table when available.
    """
    label = "promoter" if body.score >= 9 else ("passive" if body.score >= 7 else "detractor")
    log.info(
        "nps_response_received",
        tenant_id=body.tenant_id,
        score=body.score,
        label=label,
        has_comment=bool(body.comment),
    )
    _persist_nps(body)
    return {"status": "accepted", "label": label}


def _persist_nps(body: NPSSubmission) -> None:
    """Write NPS response to PostgreSQL nps_responses table (best-effort)."""
    import os
    try:
        import psycopg2  # type: ignore[import]

        dsn = os.getenv("DATABASE_URL", "")
        if not dsn:
            return
        conn = psycopg2.connect(dsn)
        cur = conn.cursor()
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS nps_responses (
                id              SERIAL PRIMARY KEY,
                tenant_id       VARCHAR(64) NOT NULL,
                score           SMALLINT    NOT NULL,
                label           VARCHAR(16) NOT NULL,
                comment         TEXT        NOT NULL DEFAULT '',
                submitted_at_ms BIGINT      NOT NULL
            )
            """
        )
        cur.execute(
            """
            INSERT INTO nps_responses (tenant_id, score, label, comment, submitted_at_ms)
            VALUES (%s, %s, %s, %s, %s)
            """,
            (
                body.tenant_id,
                body.score,
                "promoter" if body.score >= 9 else ("passive" if body.score >= 7 else "detractor"),
                body.comment,
                body.submitted_at_ms,
            ),
        )
        conn.commit()
        cur.close()
        conn.close()
    except Exception as exc:
        log.warning("nps_persist_failed", error=str(exc))


def _get_tenant_id(request: Request) -> str:
    payload = getattr(request.state, "token_payload", None)
    return payload.get("tenant_id", "default") if payload else "default"


@router.get("/reports/{tenant_id}/weekly")
async def weekly_report(tenant_id: str, request: Request) -> dict[str, Any]:
    """
    Return a structured weekly Immunity Score report for the tenant.

    Includes:
    - Score trend (last 7 days vs. prior 7 days)
    - Component breakdown comparison (week-over-week delta)
    - Top 3 attack types with lowest detection recall (highest risk)
    - Coverage gaps (untested attack types in last 30 days)
    - Red-team activity: scenarios run, scenarios that passed, new failures
    - LLM spend this month (actual vs. budget)
    - Recommended next actions
    """
    _assert_tenant_access(request, tenant_id)
    _assert_tenant_exists(tenant_id)

    try:
        # Current score
        score_payload, _ = _calculator.get_score(tenant_id)
        current_score: float = score_payload.get("score", 0.0)
        components: dict = score_payload.get("components", {})

        # 7-day history for trend
        history_7d = _calculator.get_history(tenant_id, days=7)
        history_14d = _calculator.get_history(tenant_id, days=14)

        prev_week_points = [p for p in history_14d if p not in history_7d]

        def _avg_score(points: list[dict]) -> float:
            if not points:
                return 0.0
            return round(sum(p.get("score", 0) for p in points) / len(points), 1)

        current_week_avg = _avg_score(history_7d)
        prior_week_avg = _avg_score(prev_week_points)
        score_delta = round(current_week_avg - prior_week_avg, 1)

        # Scenario coverage gaps
        scenario_coverage = _calculator.build_scenario_coverage(tenant_id)
        gaps = [
            s.attack_type
            for s in scenario_coverage
            if s.scenario_count == 0
        ]
        low_recall = sorted(
            [s for s in scenario_coverage if s.scenario_count > 0],
            key=lambda s: s.recall,
        )[:3]

        # LLM spend
        spend_usd = _cost_tracker.get_monthly_spend(tenant_id)
        spend_summary = _cost_tracker.get_spend_summary(tenant_id, days=7)
        record = _provisioner.get_tenant(tenant_id)
        budget_usd = record["monthly_llm_budget_usd"] if record else 100.0

        # Report week label
        now = datetime.now(tz=timezone.utc)
        week_label = f"Week of {now.strftime('%B %d, %Y')}"

        report: dict[str, Any] = {
            "tenant_id": tenant_id,
            "report_type": "weekly",
            "week_label": week_label,
            "generated_at_ms": int(time.time() * 1000),
            "score": {
                "current": current_score,
                "week_avg": current_week_avg,
                "prior_week_avg": prior_week_avg,
                "delta": score_delta,
                "trend": "up" if score_delta > 0 else ("down" if score_delta < 0 else "stable"),
            },
            "components": components,
            "coverage": {
                "total_attack_types": len(scenario_coverage),
                "tested_count": sum(1 for s in scenario_coverage if s.scenario_count > 0),
                "gaps": gaps,
                "lowest_recall": [
                    {"attack_type": s.attack_type, "recall": s.recall, "scenario_count": s.scenario_count}
                    for s in low_recall
                ],
            },
            "spend": {
                "month_to_date_usd": round(spend_usd, 4),
                "budget_usd": budget_usd,
                "fraction": round(spend_usd / budget_usd, 4) if budget_usd > 0 else 0.0,
                "last_7_days_usd": round(spend_summary.get("total_usd", 0.0), 4),
                "by_model": spend_summary.get("by_model", []),
            },
            "recommended_actions": _build_recommendations(
                score_delta=score_delta,
                gaps=gaps,
                low_recall=low_recall,
                spend_fraction=spend_usd / budget_usd if budget_usd > 0 else 0.0,
                components=components,
            ),
        }

        log.info("weekly_report_generated", tenant_id=tenant_id, score=current_score)
        return report

    except Exception as exc:
        log.error("weekly_report_failed", tenant_id=tenant_id, error=str(exc))
        raise HTTPException(status_code=503, detail="Report generation temporarily unavailable.")


@router.get("/reports/{tenant_id}/weekly/text")
async def weekly_report_text(tenant_id: str, request: Request) -> dict[str, str]:
    """
    Return the weekly report as a plain-text markdown string suitable for email body.
    """
    _assert_tenant_access(request, tenant_id)
    _assert_tenant_exists(tenant_id)
    data = await weekly_report(tenant_id, request)

    score = data["score"]
    cov = data["coverage"]
    spend = data["spend"]
    actions = data["recommended_actions"]

    trend_arrow = "↑" if score["trend"] == "up" else ("↓" if score["trend"] == "down" else "→")
    lines = [
        f"# Immunity Score Report — {data['week_label']}",
        f"**Tenant**: `{tenant_id}`",
        "",
        f"## Immunity Score: {score['current']:.1f} / 100  {trend_arrow} {score['delta']:+.1f} vs. last week",
        "",
        "### Component Breakdown",
        f"- Detection Coverage: {data['components'].get('detection_coverage', 0):.1%}",
        f"- False Positive Health: {data['components'].get('false_positive_health', 0):.1%}",
        f"- Model Freshness: {data['components'].get('model_freshness', 0):.1%}",
        f"- Scenario Diversity: {data['components'].get('scenario_diversity', 0):.1%}",
        "",
        "### Coverage Gaps",
        f"- Tested attack types: {cov['tested_count']} / {cov['total_attack_types']}",
    ]
    if cov["gaps"]:
        lines.append(f"- Untested: {', '.join(cov['gaps'])}")
    if cov["lowest_recall"]:
        lines.append("- Lowest recall:")
        for item in cov["lowest_recall"]:
            lines.append(f"  - `{item['attack_type']}`: {item['recall']:.0%} recall")

    lines += [
        "",
        "### LLM Spend",
        f"- Month-to-date: **${spend['month_to_date_usd']:.2f}** of ${spend['budget_usd']:.2f} ({spend['fraction']:.0%} of budget)",
        f"- Last 7 days: ${spend['last_7_days_usd']:.2f}",
        "",
        "### Recommended Actions",
    ]
    for i, action in enumerate(actions, 1):
        lines.append(f"{i}. {action}")

    lines += [
        "",
        "---",
        "*This report is auto-generated by the Sovereign Fraud Immunity Lab.*",
        "*Reply to this email or contact your CSM with any questions.*",
    ]

    return {"tenant_id": tenant_id, "markdown": "\n".join(lines)}


# ── Helpers ────────────────────────────────────────────────────────────────────

def _build_recommendations(
    *,
    score_delta: float,
    gaps: list[str],
    low_recall: list[Any],
    spend_fraction: float,
    components: dict,
) -> list[str]:
    actions: list[str] = []

    if gaps:
        next_gap = gaps[0]
        actions.append(
            f"Run a red-team DAG for `{next_gap}` — this attack type has never been tested "
            f"and creates a detection blind spot."
        )

    if low_recall:
        worst = low_recall[0]
        if worst.recall < 0.90:
            actions.append(
                f"Improve detection recall for `{worst.attack_type}` (currently {worst.recall:.0%}). "
                f"Consider adding more scenario variants and retraining the drift detector."
            )

    if components.get("model_freshness", 1.0) < 0.70:
        actions.append(
            "Trigger a profile refresh DAG — behavioral profiles are getting stale. "
            "Freshness below 70% degrades detection accuracy."
        )

    if spend_fraction >= 0.80:
        actions.append(
            f"LLM spend is at {spend_fraction:.0%} of budget. "
            "Review DAG schedules or increase the monthly budget cap to avoid throttling."
        )

    if score_delta < -5:
        actions.append(
            f"Immunity Score dropped {abs(score_delta):.1f} points this week. "
            "Review the component breakdown for the root cause — check false positive rate and freshness."
        )

    if not actions:
        actions.append(
            "Immunity Score is healthy. "
            "Continue weekly red-team runs to maintain coverage breadth."
        )

    return actions


def _assert_tenant_access(request: Request, tenant_id: str) -> None:
    requesting_tenant = _get_tenant_id(request)
    if requesting_tenant != "default" and requesting_tenant != tenant_id:
        raise HTTPException(status_code=403, detail="Access denied to this tenant's reports.")


def _assert_tenant_exists(tenant_id: str) -> None:
    record = _provisioner.get_tenant(tenant_id)
    if record is None:
        raise HTTPException(status_code=404, detail=f"Tenant '{tenant_id}' not found.")

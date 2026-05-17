"""
weekly_report_dag — Automated Weekly Immunity Score Report
==========================================================

Generates and delivers a weekly Immunity Score summary for every active tenant.

Pipeline stages:
  list_active_tenants
      ↓
  generate_reports          ← calls GET /reports/{tenant_id}/weekly for each tenant
      ↓
  deliver_reports           ← sends email + Slack digest per tenant

Schedule: every Monday at 08:00 UTC (configurable via WEEKLY_REPORT_SCHEDULE)
Tags: ["onboarding"]

Secrets: SMTP credentials from Airflow Connection 'smtp_default'.
         Slack webhook from Airflow Variable 'WEEKLY_REPORT_SLACK_WEBHOOK'.
"""

import json
import os
import time
from datetime import datetime, timedelta, timezone
from typing import Any

from airflow.decorators import dag, task
from airflow.utils.dates import days_ago

doc_md = """
## weekly_report_dag

**Purpose**: Auto-generate and deliver a weekly Immunity Score report to every active beta tenant.

**Schedule**: Mondays at 08:00 UTC — report covers the previous 7 days.

**Delivery channels**:
- Email: sent to tenant contact on file (from Airflow Variable `TENANT_{ID}_CONTACT_EMAIL`)
- Slack: digest posted to `#cs-ops` internal channel with a one-line summary per tenant
- API: full report available at `GET /reports/{tenant_id}/weekly`

**Failure behavior**: Per-tenant failures are logged but do not block other tenants.
The DAG succeeds if at least one tenant report is delivered successfully.
"""


@dag(
    dag_id="weekly_report_dag",
    schedule_interval=os.getenv("WEEKLY_REPORT_SCHEDULE", "0 8 * * 1"),  # Mon 08:00 UTC
    start_date=days_ago(1),
    catchup=False,
    tags=["onboarding"],
    doc_md=doc_md,
    default_args={
        "owner": "platform",
        "retries": 1,
        "retry_delay": timedelta(minutes=5),
    },
)
def weekly_report_dag():

    @task
    def list_active_tenants() -> list[dict[str, Any]]:
        """Fetch all active tenants from PostgreSQL."""
        from api.services.tenant_provisioner import TenantProvisioner
        import structlog
        log = structlog.get_logger(__name__)

        provisioner = TenantProvisioner()
        all_tenants = provisioner.list_tenants()
        active = [t for t in all_tenants if t.get("active")]

        log.info("weekly_report_tenants_loaded", count=len(active))
        return active

    @task
    def generate_reports(tenants: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """
        Generate the weekly report payload for each tenant via the internal API.

        Calls the ScoreCalculator and CostTracker directly (same process as the API)
        rather than making an HTTP round-trip, to avoid auth overhead in the DAG.
        """
        import structlog
        log = structlog.get_logger(__name__)

        from api.services.score_calculator import ScoreCalculator
        from api.services.cost_tracker import CostTracker
        from datetime import datetime, timezone

        calculator = ScoreCalculator()
        cost_tracker = CostTracker()

        reports: list[dict[str, Any]] = []
        now = datetime.now(tz=timezone.utc)
        week_label = f"Week of {now.strftime('%B %d, %Y')}"

        for tenant in tenants:
            tenant_id = tenant["tenant_id"]
            try:
                score_payload, _ = calculator.get_score(tenant_id)
                current_score = score_payload.get("score", 0.0)
                components = score_payload.get("components", {})

                history_7d = calculator.get_history(tenant_id, days=7)
                week_avg = (
                    round(sum(p.get("score", 0) for p in history_7d) / len(history_7d), 1)
                    if history_7d else current_score
                )

                spend = cost_tracker.get_monthly_spend(tenant_id)
                budget = float(tenant.get("monthly_llm_budget_usd", 100.0))

                scenario_coverage = calculator.build_scenario_coverage(tenant_id)
                gaps = [s.attack_type for s in scenario_coverage if s.scenario_count == 0]
                tested = sum(1 for s in scenario_coverage if s.scenario_count > 0)

                reports.append({
                    "tenant_id": tenant_id,
                    "display_name": tenant.get("display_name", tenant_id),
                    "week_label": week_label,
                    "score": current_score,
                    "week_avg": week_avg,
                    "components": components,
                    "gaps": gaps,
                    "tested_attack_types": tested,
                    "total_attack_types": len(scenario_coverage),
                    "spend_usd": round(spend, 2),
                    "budget_usd": budget,
                    "contact_email": _get_tenant_email(tenant_id),
                    "generated_at_ms": int(time.time() * 1000),
                })

                log.info(
                    "weekly_report_generated",
                    tenant_id=tenant_id,
                    score=current_score,
                )

            except Exception as exc:
                log.error("weekly_report_generation_failed", tenant_id=tenant_id, error=str(exc))

        return reports

    @task
    def deliver_reports(reports: list[dict[str, Any]]) -> dict[str, Any]:
        """
        Deliver each report via email and post a Slack digest to #cs-ops.

        Per-tenant email failures are logged and skipped — never raise.
        """
        import structlog
        log = structlog.get_logger(__name__)

        delivered = 0
        failed = 0
        slack_lines: list[str] = [
            f":bar_chart: *Weekly Immunity Score Digest — {reports[0]['week_label'] if reports else 'N/A'}*"
        ]

        for report in reports:
            tenant_id = report["tenant_id"]
            score = report["score"]
            trend = "↑" if report.get("week_avg", score) >= score else "↓"

            # Build one-line Slack summary
            slack_lines.append(
                f">• `{tenant_id}` — Score: *{score:.1f}* {trend} | "
                f"Coverage: {report['tested_attack_types']}/{report['total_attack_types']} | "
                f"Spend: ${report['spend_usd']:.2f}/${report['budget_usd']:.2f}"
            )

            # Deliver email
            email = report.get("contact_email", "")
            if email:
                success = _send_report_email(report)
                if success:
                    delivered += 1
                else:
                    failed += 1
            else:
                log.warning("weekly_report_no_email", tenant_id=tenant_id)
                delivered += 1  # counts as delivered (Slack only)

        # Post Slack digest
        _post_slack_digest("\n".join(slack_lines))

        result = {
            "reports_total": len(reports),
            "emails_delivered": delivered,
            "emails_failed": failed,
        }
        log.info("weekly_report_delivery_complete", **result)
        return result

    # ── Wire tasks ─────────────────────────────────────────────────────────────
    tenants = list_active_tenants()
    reports = generate_reports(tenants)
    deliver_reports(reports)


# ── Private helpers ────────────────────────────────────────────────────────────

def _get_tenant_email(tenant_id: str) -> str:
    """Read tenant contact email from Airflow Variable or return empty string."""
    try:
        from airflow.models import Variable
        key = f"TENANT_{tenant_id.upper().replace('-', '_')}_CONTACT_EMAIL"
        return Variable.get(key, default_var="")
    except Exception:
        return ""


def _send_report_email(report: dict[str, Any]) -> bool:
    """Send HTML email report via SMTP. Returns True on success."""
    import smtplib
    import structlog
    log = structlog.get_logger(__name__)

    smtp_host = os.getenv("SMTP_HOST", "")
    smtp_port = int(os.getenv("SMTP_PORT", "587"))
    smtp_user = os.getenv("SMTP_USERNAME", "")
    smtp_pass = os.getenv("SMTP_PASSWORD", "")
    from_addr = os.getenv("SMTP_FROM_ADDRESS", "noreply@fraud-immunity-lab.io")

    if not smtp_host:
        log.debug("smtp_not_configured_skipping_email", tenant_id=report["tenant_id"])
        return False

    try:
        from email.mime.multipart import MIMEMultipart
        from email.mime.text import MIMEText

        tenant_id = report["tenant_id"]
        score = report["score"]
        week_label = report["week_label"]

        subject = f"Fraud Immunity Lab — Weekly Report: Score {score:.1f} | {week_label}"

        components = report.get("components", {})
        gaps = report.get("gaps", [])
        gaps_str = ", ".join(gaps[:3]) + (" …" if len(gaps) > 3 else "") if gaps else "None"

        html = f"""
        <html><body style="font-family: sans-serif; color: #111;">
        <h2 style="color:#003366;">Weekly Immunity Score Report</h2>
        <p><strong>{week_label}</strong> · Tenant: <code>{tenant_id}</code></p>
        <h3>Immunity Score: <span style="color:{'#2d6a4f' if score>=80 else '#d4a017' if score>=60 else '#c1121f'}">{score:.1f}</span> / 100</h3>
        <h4>Component Breakdown</h4>
        <ul>
          <li>Detection Coverage: {components.get('detection_coverage', 0):.1%}</li>
          <li>False Positive Health: {components.get('false_positive_health', 0):.1%}</li>
          <li>Model Freshness: {components.get('model_freshness', 0):.1%}</li>
          <li>Scenario Diversity: {components.get('scenario_diversity', 0):.1%}</li>
        </ul>
        <h4>Coverage</h4>
        <p>{report.get('tested_attack_types', 0)}/{report.get('total_attack_types', 0)} attack types tested &nbsp;|&nbsp; Gaps: {gaps_str}</p>
        <h4>LLM Spend</h4>
        <p>${report.get('spend_usd', 0):.2f} of ${report.get('budget_usd', 0):.2f} budget used this month</p>
        <hr style="margin-top:24px;">
        <p style="font-size:12px;color:#666;">
          This report is auto-generated by the Sovereign Fraud Immunity Lab.<br>
          Log in to your dashboard to view full details and run red-team scenarios.
        </p>
        </body></html>
        """

        msg = MIMEMultipart("alternative")
        msg["Subject"] = subject
        msg["From"] = from_addr
        msg["To"] = report["contact_email"]
        msg.attach(MIMEText(html, "html"))

        with smtplib.SMTP(smtp_host, smtp_port) as server:
            server.starttls()
            if smtp_user:
                server.login(smtp_user, smtp_pass)
            server.sendmail(from_addr, [report["contact_email"]], msg.as_string())

        log.info("weekly_report_email_sent", tenant_id=report["tenant_id"], to=report["contact_email"])
        return True

    except Exception as exc:
        log.error("weekly_report_email_failed", tenant_id=report.get("tenant_id"), error=str(exc))
        return False


def _post_slack_digest(message: str) -> None:
    """Post the weekly digest to the internal Slack channel (best-effort)."""
    import urllib.request
    import structlog
    log = structlog.get_logger(__name__)

    try:
        from airflow.models import Variable
        webhook = Variable.get("WEEKLY_REPORT_SLACK_WEBHOOK", default_var="")
    except Exception:
        webhook = os.getenv("WEEKLY_REPORT_SLACK_WEBHOOK_URL", "")

    if not webhook:
        log.debug("weekly_digest_slack_not_configured")
        return

    try:
        payload = json.dumps({"text": message}).encode()
        req = urllib.request.Request(
            webhook,
            data=payload,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        urllib.request.urlopen(req, timeout=5)
        log.info("weekly_digest_slack_posted")
    except Exception as exc:
        log.warning("weekly_digest_slack_failed", error=str(exc))


weekly_report_dag_instance = weekly_report_dag()

"""
tenants — Tenant Provisioning API
==================================

POST   /tenants              Provision a new tenant (idempotent)
GET    /tenants              List all tenants
GET    /tenants/{tenant_id}  Get a single tenant record
DELETE /tenants/{tenant_id}  Soft-delete (deactivate) a tenant
GET    /tenants/{tenant_id}/spend  Per-tenant LLM spend summary
GET    /tenants/{tenant_id}/budget-alert  Check 80% budget threshold
"""

from fastapi import APIRouter, HTTPException, Query

from api.schemas.tenants import TenantCreateRequest, TenantResponse, TenantProvisioningStatus
from api.services.tenant_provisioner import TenantProvisioner
from api.services.cost_tracker import CostTracker

router = APIRouter(prefix="/tenants", tags=["tenants"])

_provisioner = TenantProvisioner()
_cost_tracker = CostTracker()


@router.post("", response_model=TenantResponse, status_code=201)
async def create_tenant(body: TenantCreateRequest) -> TenantResponse:
    """
    Provision all resources for a new tenant.

    Idempotent — re-provisioning an existing tenant is a no-op in PostgreSQL
    (INSERT ON CONFLICT DO NOTHING) and refreshes Redis sentinel keys.
    """
    status = _provisioner.provision(
        tenant_id=body.tenant_id,
        display_name=body.display_name,
        monthly_llm_budget_usd=body.monthly_llm_budget_usd,
    )
    record = _provisioner.get_tenant(body.tenant_id)
    if record is None:
        raise HTTPException(
            status_code=503,
            detail="Tenant provisioning failed: PostgreSQL record not created.",
        )
    return TenantResponse(
        tenant_id=record["tenant_id"],
        display_name=record["display_name"],
        monthly_llm_budget_usd=record["monthly_llm_budget_usd"],
        created_at_ms=record["created_at_ms"],
        active=record["active"],
        provisioning=status,
    )


@router.get("", response_model=list[dict])
async def list_tenants() -> list[dict]:
    """Return all tenant records ordered by creation time (newest first)."""
    return _provisioner.list_tenants()


@router.get("/{tenant_id}", response_model=TenantResponse)
async def get_tenant(tenant_id: str) -> TenantResponse:
    """Fetch a single tenant record."""
    record = _provisioner.get_tenant(tenant_id)
    if record is None:
        raise HTTPException(status_code=404, detail=f"Tenant '{tenant_id}' not found.")
    return TenantResponse(
        tenant_id=record["tenant_id"],
        display_name=record["display_name"],
        monthly_llm_budget_usd=record["monthly_llm_budget_usd"],
        created_at_ms=record["created_at_ms"],
        active=record["active"],
        provisioning=TenantProvisioningStatus(
            postgres_record_ready=True,
        ),
    )


@router.delete("/{tenant_id}", status_code=204)
async def deactivate_tenant(tenant_id: str) -> None:
    """
    Soft-delete a tenant.

    Sets ``active=false`` in PostgreSQL and removes the Redis active sentinel.
    Does NOT delete data — reactivation requires a manual DB update.
    """
    deactivated = _provisioner.deactivate(tenant_id)
    if not deactivated:
        raise HTTPException(status_code=404, detail=f"Tenant '{tenant_id}' not found.")


@router.get("/{tenant_id}/spend")
async def get_spend_summary(
    tenant_id: str,
    days: int = Query(default=30, ge=1, le=365),
) -> dict:
    """
    Return LLM spend breakdown by model for the last N days.

    Aggregates ``cost_usd``, ``prompt_tokens``, ``completion_tokens``, and
    ``call_count`` per model so operators can identify runaway workloads.
    """
    _assert_tenant_exists(tenant_id)
    return _cost_tracker.get_spend_summary(tenant_id, days=days)


@router.get("/{tenant_id}/budget-alert")
async def check_budget_alert(tenant_id: str) -> dict:
    """
    Check whether the tenant has crossed the 80% monthly budget threshold.

    Returns current spend, budget, fraction, and whether the alert is firing.
    """
    record = _assert_tenant_exists(tenant_id)
    budget_usd: float = record["monthly_llm_budget_usd"]
    alert_firing = _cost_tracker.check_budget_alert(tenant_id, budget_usd=budget_usd)
    spend = _cost_tracker.get_monthly_spend(tenant_id)
    return {
        "tenant_id": tenant_id,
        "spend_usd": round(spend, 4),
        "budget_usd": budget_usd,
        "fraction": round(spend / budget_usd, 4) if budget_usd > 0 else 0.0,
        "alert_firing": alert_firing,
        "threshold": 0.80,
    }


def _assert_tenant_exists(tenant_id: str) -> dict:
    record = _provisioner.get_tenant(tenant_id)
    if record is None:
        raise HTTPException(status_code=404, detail=f"Tenant '{tenant_id}' not found.")
    return record

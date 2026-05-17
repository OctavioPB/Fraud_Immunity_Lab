"""
tenants — Pydantic schemas for the Tenant Provisioning API.
"""

from __future__ import annotations

from pydantic import BaseModel, Field, field_validator, model_config


class TenantCreateRequest(BaseModel):
    model_config = model_config(extra="forbid")

    tenant_id: str = Field(
        description="Unique slug identifier for this tenant (lowercase alphanumeric + hyphens).",
        min_length=2,
        max_length=64,
    )
    display_name: str = Field(
        description="Human-readable tenant name.", min_length=1, max_length=128
    )
    monthly_llm_budget_usd: float = Field(
        default=100.0,
        ge=0.0,
        description="Monthly OpenAI API budget cap in USD. Alert fires at 80%.",
    )

    @field_validator("tenant_id")
    @classmethod
    def validate_slug(cls, v: str) -> str:
        import re

        if not re.fullmatch(r"[a-z0-9][a-z0-9\-]*[a-z0-9]", v):
            raise ValueError(
                "tenant_id must be lowercase alphanumeric with hyphens, "
                "no leading/trailing hyphens."
            )
        return v


class TenantProvisioningStatus(BaseModel):
    model_config = model_config(extra="forbid")

    postgres_record_ready: bool = False
    redis_namespace_ready: bool = False
    neo4j_constraints_ready: bool = False
    pinecone_namespace_ready: bool = False
    airflow_variable_set: bool = False
    errors: list[str] = Field(default_factory=list)

    @property
    def fully_provisioned(self) -> bool:
        return (
            self.postgres_record_ready
            and self.redis_namespace_ready
            and not self.errors
        )


class TenantResponse(BaseModel):
    model_config = model_config(extra="forbid")

    tenant_id: str
    display_name: str
    monthly_llm_budget_usd: float
    created_at_ms: int
    active: bool
    provisioning: TenantProvisioningStatus

# Launch Readiness Checklist
## Sovereign Fraud Immunity Lab — Beta Launch Gate
### Sprint 10 / Five-Customer Beta

> **Owner**: Platform Engineering + Customer Success  
> **Required**: All items checked before any beta customer receives dashboard access.  
> **Blocker**: Any unchecked Critical item is a hard stop — do not launch.

---

## 1. Hard Rule Production Verification

These map directly to CLAUDE.md §10. Each requires sign-off from a second engineer.

| # | Rule | Check | Verified By | Date |
|---|---|---|---|---|
| HR-1 | No codebase reference to "attack tool," "fraud generator," or "hacking system" | `grep -r "attack tool\|fraud generator\|hacking system" . --include="*.py" --include="*.ts" --include="*.md"` returns empty | | |
| HR-2 | All UI/design decisions live in BRAND.md only | No hex colors, font names, or component library references in CLAUDE.md | | |
| HR-3 | Every synthetic record carries `{"synthetic": true}` | Run `tests/red_team/test_synthetic_tag_integrity.py`; all assertions pass | | |
| HR-4 | PII never in Pinecone or Neo4j | Run `tests/integration/test_pii_boundary.py`; zero raw PII in vector metadata | | |
| HR-5 | `RED_TEAM_ENABLED=false` in production env | `echo $RED_TEAM_ENABLED` on prod returns `false`; Helm values confirm | | |
| HR-6 | All deployed scenario types have ≥90% recall in staging | All rows in `scenario_coverage` table show `recall >= 0.90`; CI gate passed | | |
| HR-7 | `synthetic_audit` Kafka topic is append-only, no delete permissions | Topic ACLs: no WRITE permission for non-producer principals; no DELETE permission for any principal | | |

---

## 2. Kill-Switch State Verification

```bash
# Check all kill-switches in production
echo "RED_TEAM_ENABLED       = $(printenv RED_TEAM_ENABLED)"
echo "SYNTHETIC_INJECTION_DRY_RUN = $(printenv SYNTHETIC_INJECTION_DRY_RUN)"
```

| Variable | Required Value | Actual Value | Pass? |
|---|---|---|---|
| `RED_TEAM_ENABLED` | `false` | | |
| `SYNTHETIC_INJECTION_DRY_RUN` | `true` | | |

> **Note**: `RED_TEAM_ENABLED` is set to `true` only after the security lead provides written authorization per customer, stored in the `cs-ops` Slack channel and the customer's Notion page.

---

## 3. Infrastructure Health

### 3a. Core Services

```bash
# Run from platform engineer workstation — all must return 200
curl -sf http://api:8000/health | jq .status
curl -sf http://airflow:8080/health | jq .status
redis-cli -u $REDIS_URL PING
psql $DATABASE_URL -c "SELECT 1" -t
```

| Service | Health Check Command | Expected | Pass? |
|---|---|---|---|
| FastAPI | `GET /health` → `{"status":"ok"}` | 200 | |
| Airflow | `GET /health` → `{"status":"healthy"}` | healthy | |
| Redis | `PING` | PONG | |
| PostgreSQL | `SELECT 1` | 1 | |
| Pinecone | `index.describe_index_stats()` | non-zero | |
| Neo4j | `RETURN 1` | 1 | |
| Kafka | `kafka-topics.sh --list` | exits 0 | |

### 3b. Kafka Topics Provisioned

| Topic | Required | Exists? |
|---|---|---|
| `transactions` | yes | |
| `login_events` | yes | |
| `device_events` | yes | |
| `synthetic_audit` | yes | |
| `dlq.transactions` | yes | |
| `dlq.login_events` | yes | |

### 3c. Airflow DAGs Active

| DAG | Schedule | Status |
|---|---|---|
| `attack_orchestrator` | Manual | Paused (kill-switch off) |
| `scenario_coverage_dag` | `0 */6 * * *` | Active |
| `community_detection_dag` | `0 2 * * *` | Active |
| `profile_refresh_dag` | `0 3 * * *` | Active |
| `onboarding_dag` | Manual | Active |
| `weekly_report_dag` | `0 8 * * 1` | Active |

---

## 4. Security Controls

### 4a. Authentication & Authorization

- [ ] `JWT_AUTH_ENABLED=true` in production environment
- [ ] `JWT_ALGORITHM=HS256` — signing key is ≥32 bytes, stored in secret manager, not in `.env` file
- [ ] `API_SECRET_KEY` rotated within the last 90 days
- [ ] `POST /auth/token` rate-limited to 10 req/60s per IP (verified via pentest)
- [ ] All `/reports/*` endpoints return 403 when requesting tenant ≠ target tenant (verified via `tests/integration/test_tenant_isolation.py`)
- [ ] `access_token` cookie has `httpOnly=true`, `SameSite=Strict` (verify in browser dev tools)

### 4b. API Security Headers

```bash
curl -I http://api:8000/health
```

Required headers present:
- [ ] `X-Content-Type-Options: nosniff`
- [ ] `X-Frame-Options: DENY`
- [ ] `Strict-Transport-Security` (HTTPS only)
- [ ] `Content-Security-Policy` set on dashboard responses

### 4c. CORS Configuration

- [ ] `API_ALLOWED_ORIGINS` lists only the production dashboard domain — not `*`
- [ ] OPTIONS preflight returns correct `Access-Control-Allow-Origin`

### 4d. Secrets Inventory

Confirm each secret is set in the production environment and NOT committed to git:

```bash
git log --all --full-history -- .env
# Must return empty — .env must never have been committed
```

| Secret | Env Var | In Secret Manager | Last Rotated |
|---|---|---|---|
| OpenAI API Key | `OPENAI_API_KEY` | | |
| Pinecone API Key | `PINECONE_API_KEY` | | |
| JWT Signing Key | `API_SECRET_KEY` | | |
| Neo4j Password | `NEO4J_PASSWORD` | | |
| PostgreSQL DSN | `DATABASE_URL` | | |
| Redis URL | `REDIS_URL` | | |
| Airflow Fernet Key | `AIRFLOW__CORE__FERNET_KEY` | | |
| Dashboard Admin Password | `DASHBOARD_ADMIN_PASSWORD` | | |

---

## 5. Tenant Isolation Verification

```bash
pytest tests/integration/test_tenant_isolation.py -v -m integration
```

All 9 tests must pass:
- [ ] `TestPineconeNamespaceIsolation::test_upsert_isolated_to_namespace`
- [ ] `TestPineconeNamespaceIsolation::test_cross_tenant_fetch_returns_nothing`
- [ ] `TestPineconeNamespaceIsolation::test_cross_tenant_query_returns_nothing`
- [ ] `TestNeo4jTenantIsolation::test_account_created_with_tenant_id`
- [ ] `TestNeo4jTenantIsolation::test_query_isolation`
- [ ] `TestCostTrackerTenantIsolation::test_cost_log_scoped_to_tenant`
- [ ] `TestCostTrackerTenantIsolation::test_cross_tenant_exclusion`
- [ ] `TestTenantProvisionerIsolation::test_independent_provisioning`
- [ ] `TestTenantProvisionerIsolation::test_deactivation_isolation`

---

## 6. Rate Limiting Verification

```bash
# Confirm rate limiter returns 429 after threshold
for i in $(seq 1 15); do
  STATUS=$(curl -s -o /dev/null -w "%{http_code}" -X POST http://api:8000/auth/token \
    -H "Content-Type: application/json" \
    -d '{"username":"test","password":"test","tenant_id":"test"}')
  echo "Request $i: $STATUS"
done
# Requests 11+ should return 429 with Retry-After header
```

- [ ] `POST /auth/token` returns 429 after 10 requests per 60s
- [ ] `POST /tenants` returns 429 after 5 requests per 60s
- [ ] 429 response includes `Retry-After` header
- [ ] Rate limit resets after window expires

---

## 7. Data Pipeline Verification

### 7a. Onboarding DAG Smoke Test

Run against the `beta-smoke-test` tenant (pre-provisioned):

```bash
airflow dags trigger onboarding_dag \
  --conf '{"tenant_id": "beta-smoke-test", "history_days": 30}'
```

Expected outcome within 20 minutes:
- [ ] All 6 stages complete (no red tasks in Airflow UI)
- [ ] Baseline Immunity Score: 40–60 (verify via `GET /immunity-score`)
- [ ] `model_freshness` component: ≥ 0.90
- [ ] Airflow Variable `TENANT_BETA_SMOKE_TEST_ONBOARDED=true`
- [ ] Slack welcome message received in `#cs-ops`

### 7b. Weekly Report DAG Smoke Test

```bash
airflow dags trigger weekly_report_dag
```

- [ ] DAG completes without error
- [ ] At least one report email received at the configured contact address
- [ ] Slack digest posted to `#cs-ops`

---

## 8. Observability

### 8a. Prometheus Metrics Reachable

```bash
curl -s http://api:8000/metrics | grep immunity_score_computation_seconds
```

- [ ] `immunity_score_computation_seconds` histogram exported
- [ ] `llm_cost_usd_total` counter exported
- [ ] `rate_limit_exceeded_total` counter exported
- [ ] `behavioral_drift_detection_latency_seconds` histogram exported

### 8b. Alerting Rules

Confirm the following Prometheus alert rules are active in Grafana/Alertmanager:

| Alert | Condition | Severity |
|---|---|---|
| `LLMBudgetNearLimit` | `llm_budget_fraction > 0.8` | warning |
| `HighFalsePositiveRate` | FP rate > 5% | critical |
| `ImmunityScoreDrop` | Score drops >10 pts in 24h | warning |
| `KafkaConsumerLag` | Lag > 10,000 events | critical |
| `APIHighLatency` | p99 > 2s for 5m | warning |

---

## 9. GDPR / Compliance

- [ ] Data Processing Agreement (DPA) signed with all 5 beta customers
- [ ] Privacy notice reviewed by legal and approved
- [ ] PII tokenization confirmed (no raw PII in Pinecone, Neo4j, or Redis)
- [ ] Data residency requirements met for all beta customers
- [ ] Retention policy configured: transaction embeddings retained for ≤ 90 days unless customer extends
- [ ] Right-to-erasure procedure documented and tested (see `infra/RUNBOOK.md`)
- [ ] Sub-processor list current and disclosed in DPA

---

## 10. Rollback Plan

### Rollback Decision Authority
- Platform Engineer on-call makes the call for infrastructure rollbacks.
- Product lead approval required for tenant deactivation.

### Rollback Procedure

**API rollback** (Kubernetes):
```bash
kubectl rollout undo deployment/fraud-immunity-api -n production
kubectl rollout status deployment/fraud-immunity-api -n production
```

**Dashboard rollback**:
```bash
# Vercel / equivalent
vercel rollback --scope fraud-immunity-lab
```

**Airflow DAG rollback**:
```bash
# Pause all active DAGs
airflow dags pause attack_orchestrator
airflow dags pause onboarding_dag
airflow dags pause weekly_report_dag
# Revert to previous DAG version via git checkout + redeploy
```

**Database rollback**:
- PostgreSQL: Use Alembic `alembic downgrade -1`; data is NOT automatically restored — assess per incident
- Pinecone: Namespace data is not versioned; restore from S3 backup if corrupted
- Neo4j: Restore from last consistent snapshot (taken nightly at 01:00 UTC)

### Rollback Communication
- [ ] Rollback triggers P1 incident in PagerDuty
- [ ] CSM notified within 15 minutes of rollback decision
- [ ] Status page (`status.fraud-immunity-lab.io`) updated within 5 minutes

---

## 11. Launch Sign-Off

All items above must be checked. Two engineers must sign below.

| Role | Name | Signature | Date |
|---|---|---|---|
| Platform Engineering Lead | | | |
| Security Lead | | | |
| Customer Success Lead | | | |

> **Post-launch**: Schedule a 48-hour retrospective. File any new issues in Linear under project `LAUNCH`.

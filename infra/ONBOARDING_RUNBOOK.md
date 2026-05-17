# ONBOARDING RUNBOOK
## Customer Success Team — New Tenant Provisioning Guide
### Sovereign Fraud Immunity Lab

> **Audience**: Customer Success Managers and Platform Engineers onboarding new beta customers.
> **Time to complete**: ~30 minutes for a standard onboarding with 90-day transaction history.
> **Prerequisites**: Customer transaction data staged, tenant slug agreed upon, API access confirmed.

---

## Overview

Each new customer (tenant) goes through a 6-step automated pipeline:

```
1. Pre-flight checks
2. Tenant provisioning (POST /tenants)
3. Stage customer data
4. Trigger onboarding DAG
5. Verify baseline Immunity Score
6. Grant dashboard access + send welcome
```

---

## Step 1 — Pre-Flight Checks

Before running any commands, confirm:

- [ ] **Tenant slug** agreed: lowercase alphanumeric + hyphens only, e.g. `acme-bank`
- [ ] **Display name** confirmed: e.g. `ACME Bank NA`
- [ ] **Monthly LLM budget** agreed (default: $100/month)
- [ ] **Contact email** for weekly reports on file
- [ ] Customer transaction data exported and staged (see Step 3)
- [ ] `DATABASE_URL`, `REDIS_URL`, `PINECONE_API_KEY`, `NEO4J_*` are set in the production environment
- [ ] Airflow is reachable and healthy (`curl http://airflow:8080/health`)

---

## Step 2 — Tenant Provisioning

### 2a. Provision via API

```bash
# Get an admin JWT first
TOKEN=$(curl -s -X POST http://localhost:8000/auth/token \
  -H "Content-Type: application/json" \
  -d '{"username":"admin","password":"<DASHBOARD_ADMIN_PASSWORD>","tenant_id":"default"}' \
  | jq -r .access_token)

# Provision the new tenant
curl -s -X POST http://localhost:8000/tenants \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "tenant_id": "acme-bank",
    "display_name": "ACME Bank NA",
    "monthly_llm_budget_usd": 150.0
  }' | jq .
```

### Expected response

```json
{
  "tenant_id": "acme-bank",
  "display_name": "ACME Bank NA",
  "monthly_llm_budget_usd": 150.0,
  "active": true,
  "provisioning": {
    "postgres_record_ready": true,
    "redis_namespace_ready": true,
    "neo4j_constraints_ready": true,
    "pinecone_namespace_ready": true,
    "airflow_variable_set": true,
    "errors": []
  }
}
```

**If `errors` is non-empty**: check the specific error message. Non-blocking errors (Pinecone, Airflow, Neo4j) do not stop provisioning — they are warnings only. The critical ones are `postgres_record_ready` and `redis_namespace_ready`.

### 2b. Set the contact email Airflow Variable

```bash
# In Airflow UI: Admin → Variables → +
# Or via CLI:
airflow variables set TENANT_ACME_BANK_CONTACT_EMAIL "cto@acmebank.example.com"
```

---

## Step 3 — Stage Customer Transaction Data

The onboarding DAG reads from a staged dataset. In production, place the customer's transaction export at the agreed path:

```
s3://<ONBOARDING_BUCKET>/<tenant_id>/transactions_90d.csv
```

**CSV format** (required columns):
| Column | Type | Notes |
|---|---|---|
| `transaction_id` | string | UUID |
| `account_id` | string | Will be tokenized automatically (Hard Rule #4) |
| `amount` | float | Transaction amount |
| `currency` | string | ISO-4217 (e.g. USD) |
| `merchant_id` | string | Merchant identifier |
| `timestamp` | int | Epoch milliseconds |
| `channel` | string | mobile / web / atm / pos / wire |

**Do not include**: names, email addresses, SSNs, card numbers, or any raw PII. The PIITokenizer will tokenize `account_id` but cannot detect PII embedded in other fields.

If the customer cannot provide a CSV export, the onboarding DAG generates a synthetic bootstrap dataset (see `_generate_bootstrap_events()` in `onboarding_dag.py`). This is acceptable for the first red-team run but should be replaced with real data as soon as possible for accurate Immunity Score computation.

---

## Step 4 — Trigger the Onboarding DAG

```bash
# Via Airflow CLI
airflow dags trigger onboarding_dag \
  --conf '{"tenant_id": "acme-bank", "history_days": 90}'

# Via Airflow REST API
curl -s -X POST http://airflow:8080/api/v1/dags/onboarding_dag/dagRuns \
  -H "Authorization: Basic $(echo -n 'admin:admin' | base64)" \
  -H "Content-Type: application/json" \
  -d '{
    "conf": {"tenant_id": "acme-bank", "history_days": 90}
  }' | jq .dag_run_id
```

### Monitor progress

```bash
# Watch DAG run status
watch -n 10 'airflow dags state onboarding_dag <dag_run_id> 2>/dev/null'

# Or via Airflow UI: DAGs → onboarding_dag → Graph view
```

### Expected DAG stages and times

| Stage | Typical Duration | Notes |
|---|---|---|
| `validate_tenant` | < 5s | Fails fast if tenant not provisioned |
| `historical_backfill` | 2–10 min | Depends on transaction volume |
| `build_behavioral_profiles` | 3–15 min | OpenAI embedding calls (rate-limited) |
| `compute_baseline_score` | < 30s | Redis cache write |
| `first_red_team_run` | < 5s | Triggers `attack_orchestrator` async |
| `send_welcome_notification` | < 5s | Slack + Airflow Variable |

---

## Step 5 — Verify Baseline Immunity Score

```bash
# Check baseline score via API
curl -s -H "Authorization: Bearer $TOKEN" \
  http://localhost:8000/immunity-score | jq '{score, components}'
```

**Expected range on first onboarding**:
- Score: 40–60 (before any red-team runs)
- `detection_coverage`: 0.0 (no attack types tested yet)
- `model_freshness`: ≥ 0.90 (profiles just built)
- `false_positive_health`: ≥ 0.95 (no false positives yet)
- `scenario_diversity`: 0.0 (no scenarios run yet)

Score will climb to 70–85 after the first successful red-team DAG run.

---

## Step 6 — Grant Dashboard Access

### 6a. Share dashboard URL

The dashboard URL is: `http://<DASHBOARD_HOST>` (or the configured HTTPS URL).

Credentials:
- Username: `admin`
- Password: see `DASHBOARD_ADMIN_PASSWORD` env var (share securely via password manager)
- Tenant: `acme-bank`

### 6b. Verify the welcome Slack message

The `send_welcome_notification` task posts to the Slack webhook configured in `SLACK_ONBOARDING_WEBHOOK_URL`. Check `#cs-ops` to confirm delivery.

### 6c. Confirm the Airflow Variable is set

```bash
airflow variables get TENANT_ACME_BANK_ONBOARDED
# Expected: true
```

---

## Troubleshooting

| Problem | Likely Cause | Fix |
|---|---|---|
| `validate_tenant` fails | Tenant not in PostgreSQL | Run Step 2 first |
| `build_behavioral_profiles` fails | OpenAI API key invalid | Check `OPENAI_API_KEY` env var |
| `build_behavioral_profiles` too slow | Embedding rate limit | Increase `OPENAI_EMBEDDING_REQUESTS_PER_MINUTE` or reduce batch size |
| `compute_baseline_score` returns 0 | Score calculator can't reach Redis | Check `REDIS_URL` and Redis health |
| `first_red_team_run` skipped | Kill-switch active | Set `RED_TEAM_ENABLED=true` in Airflow Variables if authorized |
| Slack notification missing | Webhook not configured | Set `SLACK_ONBOARDING_WEBHOOK_URL` in env |
| Pinecone namespace empty after DAG | `pinecone_namespace_ready: false` | Check Pinecone API key and index name |

---

## Offboarding (Tenant Deactivation)

```bash
# Soft-delete — preserves all data, deactivates access
curl -s -X DELETE http://localhost:8000/tenants/acme-bank \
  -H "Authorization: Bearer $TOKEN"

# Verify
curl -s http://localhost:8000/tenants/acme-bank | jq .active
# Expected: false
```

Data retention: all vectors, Neo4j nodes, and cost logs are retained after deactivation. Hard-delete requires a manual PostgreSQL + Pinecone + Neo4j cleanup — contact Platform Engineering.

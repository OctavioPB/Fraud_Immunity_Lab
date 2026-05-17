# RUNBOOK — Sovereign Fraud Immunity Lab
## Operations & Secrets Rotation Procedures

> **Audience**: On-call engineers, security leads, and platform operators.
> All commands assume access to the production environment with appropriate IAM/RBAC roles.

---

## 1. Secret Inventory

| Secret | Store | Rotation Frequency | Owner |
|---|---|---|---|
| `OPENAI_API_KEY` | `.env` / Vault | 90 days or on compromise | Security Lead |
| `PINECONE_API_KEY` | `.env` / Vault | 90 days or on compromise | Security Lead |
| `API_SECRET_KEY` (JWT signing) | `.env` / Vault | 30 days or on token leak | Security Lead |
| `DASHBOARD_ADMIN_PASSWORD` | `.env` / Vault | 30 days | Platform Ops |
| `NEO4J_PASSWORD` | `.env` / Vault | 90 days | Platform Ops |
| `POSTGRES_PASSWORD` | `.env` / Vault | 90 days | Platform Ops |
| `AIRFLOW__CORE__FERNET_KEY` | `.env` / Vault | 180 days | Platform Ops |
| `AIRFLOW__WEBSERVER__SECRET_KEY` | `.env` / Vault | 90 days | Platform Ops |

---

## 2. Secrets Rotation Procedures

### 2.1 OpenAI API Key

**Impact**: All attacker agent LLM calls and embedding generation will fail until the new key is live.

```bash
# 1. Generate new key at platform.openai.com → API Keys
# 2. Update in Vault / secret store
vault kv put secret/fraud-lab/openai OPENAI_API_KEY=<new-key>

# 3. Rolling restart (zero-downtime)
docker compose up -d --no-deps api

# 4. Verify
curl -s http://localhost:8000/health | jq .openai_reachable

# 5. Revoke old key in OpenAI dashboard
```

**Hard Rule compliance**: `RED_TEAM_ENABLED` must be `false` on prod during key rotation window to prevent attacker agents from erroring mid-run and emitting partial synthetic events without audit tags.

---

### 2.2 JWT Signing Key (`API_SECRET_KEY`)

**Impact**: All active sessions will be invalidated immediately on restart. Users must re-authenticate.

```bash
# 1. Generate a new 256-bit key
python3 -c "import secrets; print(secrets.token_hex(32))"

# 2. Update secret store
vault kv put secret/fraud-lab/api API_SECRET_KEY=<new-key>

# 3. Restart API (sessions invalidated)
docker compose up -d --no-deps api

# 4. Notify users of forced re-login via Slack #platform-ops
```

**Note**: Consider a grace period by temporarily running dual verification (old + new key) if session continuity is required. Contact Security Lead before implementing.

---

### 2.3 Pinecone API Key

**Impact**: Vector upsert and query operations will fail. Drift detection falls back to flagging all unknown profiles.

```bash
# 1. Generate new key at app.pinecone.io → API Keys
# 2. Update secret store
vault kv put secret/fraud-lab/pinecone PINECONE_API_KEY=<new-key>

# 3. Restart services that use Pinecone
docker compose up -d --no-deps api

# 4. Validate Pinecone connectivity
curl -s http://localhost:8000/health | jq .pinecone_reachable

# 5. Revoke old key in Pinecone console
```

---

### 2.4 Neo4j Password

**Impact**: Graph ingestion and fraud ring queries fail. Dashboard falls back to stub ring data.

```bash
# 1. Set new password in Neo4j Browser or via cypher-shell
cypher-shell -u neo4j -p <old-password> \
  "ALTER CURRENT USER SET PASSWORD FROM '<old-password>' TO '<new-password>'"

# 2. Update secret store
vault kv put secret/fraud-lab/neo4j NEO4J_PASSWORD=<new-password>

# 3. Restart consumers
docker compose up -d --no-deps api

# 4. Verify graph connectivity
curl -s http://localhost:8000/health | jq .neo4j_reachable
```

---

### 2.5 PostgreSQL Password

**Impact**: Cost tracking, tenant provisioning, and Airflow metadata DB unavailable.

```bash
# 1. Connect as superuser and alter role
psql -U postgres -c "ALTER USER airflow WITH PASSWORD '<new-password>';"

# 2. Update DATABASE_URL in secret store
vault kv put secret/fraud-lab/postgres \
  DATABASE_URL="postgresql://airflow:<new-password>@localhost:5432/airflow"

# 3. Restart all services with DB dependency
docker compose up -d --no-deps api

# 4. Verify
psql "$DATABASE_URL" -c "SELECT 1;"
```

---

### 2.6 Airflow Fernet Key

**Impact**: Encrypted Airflow connection credentials become unreadable. Must re-enter all connections.

**This is a breaking change** — coordinate with the Airflow admin before rotating.

```bash
# 1. Generate new Fernet key
python3 -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"

# 2. Re-encrypt all existing connections with the new key (Airflow CLI)
airflow connections export /tmp/connections_backup.json  # backup first
airflow config get-value core fernet_key  # note old key

# 3. Update secret store
vault kv put secret/fraud-lab/airflow \
  AIRFLOW__CORE__FERNET_KEY=<new-key>

# 4. Restart Airflow
docker compose up -d --no-deps airflow-webserver airflow-scheduler

# 5. Re-enter all connections via Airflow UI or CLI
```

---

## 3. Emergency: Kill-Switch Activation

If synthetic fraud injection must stop immediately (Hard Rule #5):

```bash
# Immediate: set env var and restart
vault kv put secret/fraud-lab/feature-flags RED_TEAM_ENABLED=false
docker compose up -d --no-deps api

# Verify kill-switch is active
curl -s http://localhost:8000/health | jq .red_team_enabled
# Expected: false

# All attacker agent DAGs will refuse to execute on next trigger.
# In-flight DAG runs: pause via Airflow UI → DAGs → attack_orchestrator → Pause
```

---

## 4. Incident Response: Suspected Credential Leak

1. **Assess scope**: Which secret? When was it last rotated? Are there anomalous API calls in logs?
2. **Rotate immediately**: Follow the appropriate section above.
3. **Audit**: Query `llm_cost_log` for unexpected spend spikes:
   ```sql
   SELECT tenant_id, model, SUM(cost_usd), COUNT(*)
   FROM llm_cost_log
   WHERE recorded_at_ms > extract(epoch from now() - interval '24 hours') * 1000
   GROUP BY tenant_id, model
   ORDER BY SUM(cost_usd) DESC;
   ```
4. **Check audit trail**: The `synthetic_audit` Kafka topic is append-only (Hard Rule #7). Any unexpected records indicate unauthorized injection.
5. **Notify**: Security Lead within 1 hour; post-mortem within 48 hours.

---

## 5. Health Check Endpoints

```bash
# Full service health
curl http://localhost:8000/health

# Prometheus metrics (for PagerDuty/Grafana)
curl http://localhost:8000/metrics

# Per-tenant budget alert check
curl -H "Authorization: Bearer $TOKEN" \
  http://localhost:8000/tenants/{tenant_id}/budget-alert
```

---

## 6. Dependency Audit

Run quarterly or before any dependency upgrade:

```bash
# Python dependency audit
pip-audit --requirement requirements.txt

# Node dependency audit
cd dashboard && npm audit --audit-level=high

# Check for known CVEs in Docker base images
docker scout cves fraud-immunity-lab-api:latest
```

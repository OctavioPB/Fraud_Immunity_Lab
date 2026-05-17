# Incident Response Playbook
## Sovereign Fraud Immunity Lab — Beta Operations
### Version 1.0 — Sprint 10

> **Audience**: Platform Engineering on-call, Customer Success Managers  
> **Purpose**: Standardized response procedures for production incidents during and after the 5-customer beta.  
> **Last reviewed**: See git blame on this file.

---

## Severity Definitions

| Level | Criteria | Response SLA | Examples |
|---|---|---|---|
| **P1 — Critical** | Customer data at risk, complete service outage, kill-switch failure, PII breach | Acknowledge < 15 min, resolve or mitigate < 2 hours | API returning 500 for all tenants, synthetic tag stripped, RED_TEAM_ENABLED=true in prod without authorization |
| **P2 — High** | Single tenant affected, degraded score accuracy, missed weekly report | Acknowledge < 30 min, resolve < 8 hours | Pinecone namespace confusion, onboarding DAG failure, Immunity Score stale > 30 min |
| **P3 — Medium** | Non-blocking degradation, delayed alerts | Acknowledge < 2 hours, resolve < 48 hours | Slack notification failure, NPS persistence error, slow dashboard load |
| **P4 — Low** | Cosmetic or informational | Next sprint | Typo in weekly report, Prometheus label mismatch |

---

## On-Call Contacts

| Role | Contact | Backup |
|---|---|---|
| Platform Engineering | PagerDuty rotation `fraud-immunity-platform` | Platform Engineering Lead direct |
| Customer Success | CSM on-call (Slack `#cs-ops`) | Customer Success Lead |
| Security Lead | `security@fraud-immunity-lab.io` | CTO |
| Legal / Compliance | `legal@fraud-immunity-lab.io` | — |

---

## General Response Protocol

### For every incident:

1. **Declare** — Post in `#incidents` Slack channel: severity, one-line description, your name as IC (Incident Commander)
2. **Assess** — Determine blast radius: which tenants affected, what data at risk, is kill-switch needed
3. **Contain** — Stop the bleeding before diagnosing root cause
4. **Communicate** — Notify affected customers via CSM within SLA window
5. **Resolve** — Fix or roll back
6. **Post-mortem** — File within 5 business days using the template at the bottom of this file

---

## Runbook 1 — Complete API Outage

**Symptoms**: `GET /health` returns non-200, dashboard shows no data for all tenants, Prometheus scrape failing.

**Step 1 — Confirm scope**
```bash
curl -sf http://api:8000/health
kubectl get pods -n production -l app=fraud-immunity-api
kubectl logs -n production deployment/fraud-immunity-api --tail=100
```

**Step 2 — Check dependency health**
```bash
redis-cli -u $REDIS_URL PING          # Should return PONG
psql $DATABASE_URL -c "SELECT 1" -t   # Should return 1
```

**Step 3a — If crash loop (OOMKilled, CrashLoopBackOff)**
```bash
kubectl rollout undo deployment/fraud-immunity-api -n production
kubectl rollout status deployment/fraud-immunity-api -n production
```

**Step 3b — If Redis unreachable**
- API middleware gracefully degrades (rate limiting and caching no-op)
- Root cause: Redis eviction policy or connectivity — check `REDIS_URL` and Redis cluster health
- API will continue serving without Redis, but Immunity Score will not be cached

**Step 3c — If PostgreSQL unreachable**
```bash
# Check connection pool exhaustion
psql $DATABASE_URL -c "SELECT count(*) FROM pg_stat_activity WHERE state = 'active'"
# If > 90, restart the connection pool:
kubectl rollout restart deployment/fraud-immunity-api -n production
```

**Escalation**: If not resolved in 30 minutes → P1, page Platform Engineering Lead.

---

## Runbook 2 — Kill-Switch Failure (`RED_TEAM_ENABLED=true` in Production Unauthorized)

**This is a P1 incident. Activate immediately.**

**Step 1 — Halt all attacker agent DAGs**
```bash
airflow dags pause attack_orchestrator
airflow dags pause scenario_coverage_dag
```

**Step 2 — Set kill-switch in Airflow Variables (fastest path)**
```bash
airflow variables set RED_TEAM_ENABLED false
```

**Step 3 — Set kill-switch in environment (durable)**
```bash
# Update Kubernetes secret / Helm values
kubectl set env deployment/fraud-immunity-api RED_TEAM_ENABLED=false -n production
kubectl set env deployment/airflow-scheduler RED_TEAM_ENABLED=false -n production
kubectl rollout restart deployment/fraud-immunity-api -n production
```

**Step 4 — Audit what ran**
```bash
# Check synthetic_audit Kafka topic for records since unauthorized activation
kafka-console-consumer.sh \
  --bootstrap-server $KAFKA_BOOTSTRAP_SERVERS \
  --topic synthetic_audit \
  --from-beginning \
  --property print.timestamp=true \
  | grep '"synthetic":true' | tail -100
```

**Step 5 — Notify**
- Security Lead: immediate
- Affected tenant CSMs: within 15 minutes
- Legal: within 1 hour (potential regulatory notification obligation)

**Step 6 — Root cause investigation**
- Who changed `RED_TEAM_ENABLED`? Check Kubernetes audit logs and Airflow Variable change history
- Was any synthetic fraud injected into a live stream? Check `synthetic_audit` records with `dry_run: false`
- If live injection occurred: activate Runbook 5 (Synthetic Data Contamination)

---

## Runbook 3 — Tenant Data Isolation Breach (Cross-Tenant Data Leakage)

**Symptoms**: Tenant A sees Tenant B's alerts, fraud rings, or score data in their dashboard.

**Step 1 — Identify the scope**
```bash
# Check which API calls are returning wrong tenant data
# Look at structured logs for tenant_id mismatches
grep '"tenant_id"' /var/log/fraud-immunity/api.log | \
  python3 -c "import sys,json; [print(json.loads(l)) for l in sys.stdin if json.loads(l).get('tenant_id') != json.loads(l).get('request_tenant_id')]" \
  | head -50
```

**Step 2 — Emergency containment: pause all API traffic for affected endpoints**
```bash
# Rate limit all tenants to 0 (emergency, reverting quickly)
airflow variables set EMERGENCY_LOCKDOWN true
# The API middleware checks this variable — implement if not already present
```

**Step 3 — Pinecone namespace check**
```bash
# Verify namespace isolation is in place
python3 - <<'EOF'
from ml.embeddings.profile_builder import _pinecone_namespace
print(_pinecone_namespace("tenant-a"))
print(_pinecone_namespace("tenant-b"))
# Must return different, non-empty strings
EOF
```

**Step 4 — Neo4j isolation check**
```bash
# Confirm tenant_id is on all Account nodes
cypher-shell -u $NEO4J_USERNAME -p $NEO4J_PASSWORD \
  "MATCH (a:Account) WHERE a.tenant_id IS NULL RETURN count(a) as untagged_accounts"
# Must return 0
```

**Step 5 — Notify**
- Both tenants affected: within 30 minutes via CSM
- Legal and DPO: within 1 hour (potential GDPR Art. 33 notification requirement — 72-hour window begins now)
- Document exact data exposed (which records, which tenants, time window)

---

## Runbook 4 — PII Breach (Raw PII in Pinecone or Neo4j)

**This is a P1 incident and a potential GDPR Art. 33 notifiable breach.**

**Step 1 — Halt ingestion immediately**
```bash
airflow dags pause onboarding_dag
# Stop Kafka consumers
kubectl scale deployment/kafka-consumer --replicas=0 -n production
```

**Step 2 — Identify the vectors at risk**
```bash
# Query Pinecone for any vector where metadata contains known PII fields
python3 - <<'EOF'
import pinecone, os
pinecone.init(api_key=os.environ["PINECONE_API_KEY"], environment=os.environ["PINECONE_ENVIRONMENT"])
index = pinecone.Index(os.environ["PINECONE_INDEX_CLEAN"])
# Fetch stats per namespace and sample vectors to inspect metadata
stats = index.describe_index_stats()
print(stats)
# Manually inspect samples — look for email, SSN, name fields in metadata
EOF
```

**Step 3 — Purge contaminated vectors**
- Only Platform Engineering Lead can authorize a bulk delete
- Document every vector ID deleted and the tenant namespace before deletion
- After purge, re-run `tests/integration/test_pii_boundary.py` to confirm clean

**Step 4 — Root cause**
- Which ingestion path bypassed PIITokenizer?
- Was it the CSV onboarding flow or a Kafka consumer?
- Check `onboarding_dag.py` → `historical_backfill` task — confirm tokenizer was applied

**Step 5 — Regulatory notification**
- DPO assesses whether breach meets GDPR Art. 33 threshold (>72h internal notification clock starts at detection)
- Affected customers notified per contractual DPA terms

---

## Runbook 5 — Synthetic Data Contamination in Production Stream

**Symptoms**: Real production alerts tagged `synthetic: true`, or synthetic fraud records visible in customer dashboards without the "SYNTHETIC" tag in the UI.

**Step 1 — Halt synthetic injection**
```bash
airflow variables set SYNTHETIC_INJECTION_DRY_RUN true
airflow dags pause attack_orchestrator
```

**Step 2 — Identify contaminated records**
```bash
kafka-console-consumer.sh \
  --bootstrap-server $KAFKA_BOOTSTRAP_SERVERS \
  --topic transactions \
  --from-beginning \
  --property print.timestamp=true \
  | python3 -c "
import sys, json
for line in sys.stdin:
    try:
        rec = json.loads(line.split('\t', 1)[1])
        if rec.get('synthetic') is True and not rec.get('dry_run'):
            print(rec)
    except: pass
" | head -100
```

**Step 3 — Remove contaminated records from Pinecone**
```python
# In a Python shell — delete vectors tagged synthetic from clean namespace
from ml.embeddings.profile_builder import _pinecone_namespace
import pinecone, os
pinecone.init(api_key=os.environ["PINECONE_API_KEY"], environment=os.environ["PINECONE_ENVIRONMENT"])
index = pinecone.Index(os.environ["PINECONE_INDEX_CLEAN"])
# Fetch and delete vectors where metadata["synthetic"] == "true" in wrong namespace
```

**Step 4 — Rebuild affected behavioral profiles**
```bash
airflow dags trigger profile_refresh_dag \
  --conf '{"tenant_id": "<affected_tenant>", "force_rebuild": true}'
```

**Step 5 — Audit trail check**
- All synthetic records should appear in `synthetic_audit` Kafka topic
- Confirm the contaminated records ARE in the audit trail (Hard Rule #7 compliance)

---

## Runbook 6 — Immunity Score Stuck / Stale

**Symptoms**: Score hasn't updated in >30 minutes, score shows as 0 unexpectedly.

**Step 1 — Check Redis cache**
```bash
redis-cli -u $REDIS_URL KEYS "immunity_score:*"
redis-cli -u $REDIS_URL TTL "immunity_score:<tenant_id>"
```

**Step 2 — Force cache invalidation**
```bash
curl -s -X POST http://api:8000/immunity-score/refresh \
  -H "Authorization: Bearer $ADMIN_TOKEN"
# Or directly:
redis-cli -u $REDIS_URL DEL "immunity_score:<tenant_id>"
```

**Step 3 — Check ScoreCalculator dependencies**
```bash
# Verify Pinecone and Neo4j are reachable
curl -s http://api:8000/health | jq .dependencies
```

**Step 4 — If score returns 0**
- Check `detection_coverage`: 0 means no attack scenarios have been tested — trigger `attack_orchestrator`
- Check `model_freshness`: if profiles are empty, re-run `profile_refresh_dag`

---

## Runbook 7 — LLM Cost Overrun

**Symptoms**: `LLM_BUDGET_FRACTION` gauge > 1.0, cost alert triggered, customer at risk of throttling.

**Step 1 — Check spend**
```bash
curl -s http://api:8000/tenants/<tenant_id>/spend?days=7 | jq .
curl -s http://api:8000/tenants/<tenant_id>/budget-alert | jq .
```

**Step 2 — Pause the most expensive DAG**
```bash
# attack_orchestrator is typically the largest cost driver
airflow dags pause attack_orchestrator
```

**Step 3 — Reduce embedding batch size**
```bash
# Lower the requests-per-minute for the affected tenant
airflow variables set OPENAI_EMBEDDING_REQUESTS_PER_MINUTE 30
```

**Step 4 — Notify customer**
- CSM contacts the customer within 24 hours
- Discuss budget increase or red-team schedule adjustment

---

## Tabletop Exercise Guide

Run this exercise quarterly with the on-call rotation. Pick one scenario at random and work through it as a team.

### Scenario A — "The Unauthorized Red-Team"
*Setup*: Someone accidentally sets `RED_TEAM_ENABLED=true` in the production Helm chart during a routine deploy.  
*Question*: How quickly can you detect it? What's the blast radius? Who do you notify first?  
*Expected detection time*: < 5 minutes (Airflow DAG activation alert + Prometheus metric spike)

### Scenario B — "The Leaky Namespace"
*Setup*: A code change removes the `namespace=` parameter from a Pinecone query, causing all queries to default to the empty namespace (shared across tenants).  
*Question*: Which tenant sees which data? How do you identify the contaminated time window?  
*Expected detection time*: Next red-team run (could be hours) — discuss how to add a continuous isolation check

### Scenario C — "The Stale Beta Customer"
*Setup*: Tenant `beta-customer-3`'s onboarding DAG fails silently at stage 3. They log into the dashboard and see an Immunity Score of 0.  
*Question*: What's your first communication to the customer? How do you re-trigger the DAG without duplicating data?

### Scenario D — "The Missing Synthetic Tag"
*Setup*: A code change introduces a bug that strips the `synthetic: true` flag from 10% of records before Pinecone upsert.  
*Question*: How do you detect this? How do you identify which records are affected? Is this a GDPR incident?

---

## Post-Mortem Template

File within 5 business days of incident resolution. Store in `docs/post-mortems/YYYY-MM-DD-<slug>.md`.

```markdown
# Post-Mortem: <Incident Title>
**Date**: YYYY-MM-DD  
**Severity**: P<N>  
**Duration**: HH:MM from detection to resolution  
**Incident Commander**: <name>  
**Participating Engineers**: <names>

## Timeline (UTC)
| Time | Event |
|---|---|
| HH:MM | First signal (alert, customer report, etc.) |
| HH:MM | Incident declared |
| HH:MM | Root cause identified |
| HH:MM | Mitigation applied |
| HH:MM | Incident resolved |

## Root Cause
<Single paragraph — what actually went wrong, not what triggered it>

## Customer Impact
- Which tenants were affected
- Duration of impact
- Data exposed (if any)

## What Went Well
<3 bullets — detection speed, escalation, communication>

## What Went Wrong
<3 bullets — gaps in monitoring, runbook gaps, communication delays>

## Action Items
| Item | Owner | Due Date | Done? |
|---|---|---|---|
| | | | |

## Hard Rule Check
Did this incident involve any Hard Rule violation or near-miss?
- [ ] HR-3 (synthetic tag) — [ ] HR-4 (PII boundary) — [ ] HR-5 (kill-switch) — [ ] HR-6 (recall gate) — [ ] HR-7 (audit trail)
If yes, describe below and notify Security Lead.
```

---

## Quick Reference Card

Print and keep at engineer desk.

```
P1 RESPONSE:
1. Post in #incidents — severity, description, your name
2. Assess: what's at risk, which tenants
3. Kill-switch if synthetic fraud involved:
   airflow variables set RED_TEAM_ENABLED false
4. Notify CSM lead within 15 min
5. Page Security Lead if data breach suspected

USEFUL COMMANDS:
  API health:       curl http://api:8000/health
  Score:            curl http://api:8000/immunity-score -H "Authorization: Bearer $TOKEN"
  Force score refresh:  redis-cli DEL "immunity_score:<tenant_id>"
  Pause all DAGs:   airflow dags pause attack_orchestrator && airflow dags pause onboarding_dag
  Kill-switch:      airflow variables set RED_TEAM_ENABLED false
  Check audit trail: kafka-console-consumer.sh --topic synthetic_audit --from-beginning

ESCALATION:
  Platform Eng on-call → PagerDuty "fraud-immunity-platform"
  Security Lead → security@fraud-immunity-lab.io
  DPO (PII breach) → legal@fraud-immunity-lab.io
```

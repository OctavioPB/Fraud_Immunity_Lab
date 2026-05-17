# PLAN.md — Sprint Roadmap
## Sovereign Fraud Immunity Lab (`inmunidad-sintetica`)

> **Source of truth for delivery.** Update task status inline (`[ ]` → `[x]`).
> All UI/design deliverables reference `BRAND.md`. All architectural decisions reference `CLAUDE.md`.

---

## Timeline at a Glance

| Sprint | Name | Weeks | Goal |
|---|---|---|---|
| 1 | Foundation & Infrastructure | 1–2 | Repo, local stack, CI/CD skeleton |
| 2 | Kafka Ingestion Pipeline | 3–4 | Real-time event streams flowing |
| 3 | Attacker Agent Framework | 5–6 | LLM agents generating valid scenarios |
| 4 | Red-Team Orchestration (Airflow) | 7–8 | End-to-end DAG: generate → inject → audit |
| 5 | Vector Intelligence (Pinecone) | 9–10 | Behavioral profiles + drift detection live |
| 6 | Graph Intelligence (Neo4j) | 11–12 | Fraud ring detection operational |
| 7 | Immunity Score Engine | 13–14 | Composite metric computed + API exposed |
| 8 | Dashboard (Next.js) | 15–16 | CMO-facing Immunity Score dashboard |
| 9 | Hardening & Multi-Tenancy | 17–18 | Auth, rate limits, cost controls, perf |
| 10 | Beta Launch | 19–20 | 5 paying customers onboarded |

---

## Sprint 1 — Foundation & Infrastructure
**Weeks 1–2 | Goal: Every engineer can clone, run, and contribute from day one**

### Infrastructure
- [x] Initialize Git repository with branch protection on `main`; require PR reviews
- [x] Create `CLAUDE.md`, `PLAN.md`, `BRAND.md` (stub) in root
- [x] Scaffold directory structure per `CLAUDE.md §2`
- [x] Add `.env.example` with all variables documented in `CLAUDE.md §5`
- [x] Add `.gitignore` (Python, Node, `.env`, `__pycache__`, `.next`)

### Local Dev Stack (Docker Compose)
- [x] `docker-compose.yml` with services: Kafka + Zookeeper, Airflow (webserver + scheduler + worker), Pinecone local emulator (or mock), Neo4j, Redis, FastAPI, Next.js
- [x] Health checks on all services; `make up` / `make down` convenience targets
- [x] Seed script: creates Kafka topics, Pinecone indexes, Neo4j constraints on startup

### CI/CD
- [x] GitHub Actions pipeline: lint (Ruff + ESLint), format check (Black + Prettier), unit tests
- [x] Pre-commit hooks: Black, Ruff, `detect-secrets` (blocks `.env` commits)
- [x] `Makefile` targets: `test`, `lint`, `format`, `up`, `down`, `seed`

### Definition of Done
- `make up && make seed` produces a fully operational local stack with no manual steps
- CI passes on an empty `main` branch
- All seven hard rules from `CLAUDE.md` are codified as lint rules or pre-commit checks where automatable

---

## Sprint 2 — Kafka Ingestion Pipeline
**Weeks 3–4 | Goal: Real-time transactional, login, and device events flow into consumable streams**

### Kafka Schema Design
- [x] Define Avro schemas for three event types:
  - `TransactionEvent`: `{transaction_id, account_id, amount, currency, merchant_id, timestamp, metadata}`
  - `LoginEvent`: `{session_id, account_id, ip_address, user_agent, geo, timestamp, success}`
  - `DeviceEvent`: `{device_id, account_id, fingerprint, os, app_version, timestamp}`
- [x] Register schemas in Schema Registry; version-lock in `ingestion/schemas/`
- [x] Document all fields with `doc` attributes in Avro schema files

### Kafka Consumers (`ingestion/consumers/`)
- [x] `transaction_consumer.py` — consumes `KAFKA_TOPIC_TRANSACTIONS`; validates schema; emits to internal processing queue
- [x] `login_consumer.py` — consumes `KAFKA_TOPIC_LOGINS`
- [x] `device_consumer.py` — consumes `KAFKA_TOPIC_DEVICES`
- [x] Base consumer class with: auto-offset reset, dead-letter topic on schema failure, structured logging (JSON)
- [x] Consumer group config ensures exactly-once processing semantics

### Synthetic Event Producer (Testing & Red-Team)
- [x] `ingestion/producers/synthetic_producer.py` — generates realistic fake events for load testing and red-team injection
- [x] **Always tags synthetic events**: `{"synthetic": true, "origin": "red_team"}` in event metadata
- [x] Respects `SYNTHETIC_INJECTION_DRY_RUN` env flag — logs instead of publishing when `true`

### Monitoring
- [x] Consumer lag metric exposed via `/metrics` endpoint (Prometheus-compatible)
- [x] Alert threshold config for consumer lag > 1000 messages

### Definition of Done
- 10,000 synthetic events/minute sustained throughput with < 500ms end-to-end latency
- Dead-letter topic captures 100% of malformed events with error metadata
- Consumer lag metric visible in local Prometheus

---

## Sprint 3 — Attacker Agent Framework
**Weeks 5–6 | Goal: LLM-powered agents generate structurally valid, diverse fraud scenarios**

### Base Agent Architecture (`red_team/agents/`)
- [x] `base_agent.py` — abstract class: `generate_scenario() -> ScenarioConfig`; enforces rate limiting, cost tracking, output validation
- [x] `ScenarioConfig` Pydantic model: `{attack_type, complexity, target_segment, evasion_tactics, transaction_pattern, expected_detection_signals}`
- [x] JSON Schema validation on every agent output; invalid outputs are logged and retried (max 3 attempts)
- [x] All agent calls append to `synthetic_audit` Kafka topic immediately (before injection)

### Attacker Agents
- [x] `phishing_agent.py` — generates phishing email + credential stuffing scenarios
  - Inputs: target segment config, sophistication level
  - Outputs: login event sequence + transaction pattern that follows a successful phishing attack
- [x] `laundering_agent.py` — generates money-laundering chain scenarios
  - Outputs: multi-hop transaction graph (structured for Neo4j ingestion) designed to look legitimate
- [x] `account_takeover_agent.py` — generates ATO patterns: device fingerprint changes, login anomalies, rapid payee additions
- [x] Prompt templates stored in `red_team/agents/prompts/` as versioned `.j2` (Jinja2) files — never hardcoded

### Scenario Config Library (`red_team/scenarios/`)
- [x] At least 10 seed scenario YAML configs covering: card fraud, synthetic identity, first-party fraud, mule accounts, smurfing
- [x] YAML schema enforced via `pydantic-settings`

### Safety Controls
- [x] `RED_TEAM_ENABLED` check as a decorator (`@require_red_team_enabled`) applied to all agent entry points
- [x] LLM cost budget cap per DAG run (configurable via Airflow Variable)
- [x] No agent may output raw PII — output validator strips and flags any detected PII patterns

### Definition of Done
- Each agent generates ≥ 20 unique, schema-valid scenarios without repetition in a single run
- Output validator rejects 100% of structurally invalid or PII-containing outputs
- Cost per 100 scenarios < $2.00 (tracked in agent logs)

---

## Sprint 4 — Red-Team Orchestration (Airflow)
**Weeks 7–8 | Goal: Full automated attack cycle — generate, inject, audit — runs on schedule**

### DAG Architecture (`red_team/dags/`)
- [x] `attack_orchestrator.py` — master DAG; tags: `["red_team"]`
  - Tasks: `select_scenario` → `generate_synthetic_fraud` → `validate_output` → `inject_to_kafka` → `log_to_audit` → `trigger_detection_eval`
  - Schedule: configurable (default: every 6 hours in staging, manual-trigger in prod)
  - Respects `RED_TEAM_ENABLED` at DAG level — skips all tasks if `false`
- [x] `scenario_generator.py` — DAG that maintains scenario library freshness; generates new scenario variants weekly
- [x] `model_retraining_trigger.py` — DAG that triggers ML retraining when detection recall drops below threshold

### TaskFlow Implementation
- [x] All tasks use `@task` decorator
- [x] Secrets via Airflow Connections — no env var interpolation in DAG files
- [x] XCom usage minimized; pass only scenario IDs between tasks (full payloads go through Kafka)
- [x] Every DAG has `doc_md` string with: purpose, trigger conditions, dependencies, kill-switch behavior

### Audit Trail
- [x] `log_to_audit` task appends to `synthetic_audit` topic: `{scenario_id, attack_type, generated_at, injected_at, dry_run, agent_version, cost_usd}`
- [x] Audit records include DAG run ID for traceability

### Definition of Done
- End-to-end DAG run completes in < 5 minutes for a batch of 50 scenarios
- Kill-switch test: setting `RED_TEAM_ENABLED=false` stops all tasks within one DAG evaluation cycle
- Audit topic receives exactly one record per scenario, always

---

## Sprint 5 — Vector Intelligence (Pinecone)
**Weeks 9–10 | Goal: Behavioral profiles stored; drift detection flags anomalies in real time**

### Behavioral Profile Builder (`ml/embeddings/`)
- [x] `profile_builder.py` — ingests clean transaction history; generates per-user behavioral embedding
  - Embedding input: transaction amount distribution, merchant category mix, time-of-day patterns, geo patterns (serialized as text + structured fields)
  - Model: `text-embedding-3-large`
  - Upsert to Pinecone with metadata: `{account_id, label, last_updated, transaction_count}`
- [x] `synthetic_profile_injector.py` — takes attacker agent output; embeds synthetic fraud pattern; upserts with `label: synthetic_fraud`
- [x] PII tokenizer middleware: strips/tokenizes account numbers and names before any embedding call

### Drift Detection (`ml/anomaly/`)
- [x] `drift_detector.py`:
  - Query Pinecone for top-k nearest neighbors to incoming transaction embedding
  - Compute weighted cosine similarity score
  - Return `DriftResult(score, flagged, nearest_neighbors, drift_type)`
  - Threshold configurable per account segment (conservative for high-value accounts)
- [x] `anomaly_pipeline.py` — Celery task that runs drift detection on every `TransactionEvent` from Kafka
- [x] Results published to `KAFKA_TOPIC_DETECTION_RESULTS` for downstream consumption

### Index Management
- [x] Two Pinecone indexes: `clean-profiles` + `suspicious-profiles` (per `CLAUDE.md §5`)
- [x] Nightly job: refresh clean profiles for accounts with > 100 new transactions (`profile_refresh_dag.py`)
- [x] Staleness detection: alert if any profile is > 30 days old

### Definition of Done
- Drift detection latency < 200ms p99 on a cold query
- Synthetic fraud profiles (injected by red-team DAG) are correctly classified as `flagged: true` with ≥ 90% recall
- Zero raw PII in any Pinecone vector or metadata field

---

## Sprint 6 — Graph Intelligence (Neo4j)
**Weeks 11–12 | Goal: Fraud ring detection via account relationship graph**

### Graph Schema (`ml/graph/`)
- [x] Node types: `Account`, `Transaction`, `Device`, `Merchant`, `IPAddress`
- [x] Relationships:
  - `(Account)-[:SENT_TO]->(Account)` (with `amount`, `timestamp` properties)
  - `(Account)-[:LOGGED_IN_FROM]->(IPAddress)`
  - `(Account)-[:USED_DEVICE]->(Device)`
  - `(Account)-[:TRANSACTED_AT]->(Merchant)`
- [x] Cypher constraints: `UNIQUE` on `Account.account_id`, `Transaction.transaction_id`
- [x] All Cypher queries parameterized; stored in `ml/graph/queries/` as `.cypher` files

### Graph Ingestion
- [x] `graph_ingestion.py` — Kafka consumer that writes `TransactionEvent` and `LoginEvent` to Neo4j in real time
- [x] Batch loader for historical data backfill (parallelized by account segment)
- [x] Synthetic fraud transactions tagged with `synthetic: true` property on nodes and relationships

### Community Detection (`ml/graph/community_detection.py`)
- [x] Run Louvain algorithm via Neo4j GDS on `SENT_TO` relationship graph
- [x] Flag clusters where:
  - Cluster size > configurable threshold AND
  - Money flow is predominantly unidirectional (laundering signal) AND
  - Accounts share `IPAddress` or `Device` nodes (collusion signal)
- [x] Output: `FraudRing(ring_id, member_account_ids, risk_score, signals[])`
- [x] Results stored back in Neo4j as `FraudRing` nodes linked to member `Account` nodes

### Airflow Integration
- [x] Add `community_detection_dag.py` — runs Louvain daily + on-demand trigger from red-team DAG
- [x] Alert task: if new fraud ring detected with risk_score > 0.85, publish to `KAFKA_TOPIC_ALERTS`

### Definition of Done
- Graph ingestion sustains 5,000 transaction edges/minute
- Louvain detects synthetic laundering rings (injected by `laundering_agent.py`) with ≥ 85% precision
- All Cypher queries return in < 500ms on a 1M-node test graph

---

## Sprint 7 — Immunity Score Engine
**Weeks 13–14 | Goal: Composite Immunity Score computed continuously; exposed via API**

### Score Definition
```
ImmunityScore (0–100) =
  (0.40 × DetectionCoverage)     # % of known synthetic attack types flagged
+ (0.30 × FalsePositiveHealth)   # 1 - false_positive_rate (legitimate txns flagged)
+ (0.20 × ModelFreshness)        # Based on profile age and retraining recency
+ (0.10 × ScenarioDiversity)     # Breadth of attack types tested in last 30 days
```

### Score Engine (`api/routers/immunity_score.py`)
- [x] `ScoreCalculator` service class — pulls inputs from Pinecone stats, Neo4j query, Airflow DAG history
- [x] Score computed per tenant; cached in Redis with 5-minute TTL
- [x] Historical score time series stored in PostgreSQL (new service addition — see infra)
- [x] `GET /immunity-score` — returns current score + component breakdown
- [x] `GET /immunity-score/history?days=30` — returns time series
- [x] `GET /immunity-score/scenarios` — lists attack types tested + detection rate per type

### Scenario Coverage Report
- [x] `ScenarioCoverageReport` — generated daily by Airflow (`scenario_coverage_dag.py`); lists:
  - Tested attack types (last 30 days)
  - Detection recall per type
  - Attack types NOT yet tested (coverage gaps)
  - Recommended scenarios to run next

### FastAPI Foundations
- [x] JWT authentication middleware (algorithm: HS256 per `CLAUDE.md §5`)
- [x] Tenant isolation: all queries scoped by `tenant_id` from JWT claims
- [x] Request/response logging with correlation IDs
- [x] OpenAPI docs auto-generated at `/docs`

### Definition of Done
- Immunity Score updates within 30 seconds of a completed red-team DAG run
- API responds in < 100ms p99 (Redis cache hit path)
- Score components are explainable — every point change has a traceable cause

---

## Sprint 8 — Dashboard (Next.js)
**Weeks 15–16 | Goal: CMO-facing Immunity Score dashboard — functional, designed per BRAND.md**

> ⚠️ All visual decisions (colors, typography, component choices, chart library, animation) are defined in `BRAND.md`. This sprint implements those decisions. Do not design here.

### Core Dashboard Views
- [ ] **Immunity Score Hero** — large score display, trend sparkline, last-updated timestamp
- [ ] **Component Breakdown** — four sub-scores (Detection Coverage, FP Health, Freshness, Diversity) with drill-down
- [ ] **Attack Scenario Map** — table of all tested attack types; detection rate per type; highlight untested gaps
- [ ] **Fraud Ring Visualizer** — graph visualization of detected fraud rings (integrate with Neo4j query via API)
- [ ] **Alert Feed** — real-time feed of high-risk detections (WebSocket from FastAPI)
- [ ] **Red-Team Status** — current DAG run status, last run time, scenarios generated this week

### Technical Implementation
- [ ] Next.js 14 App Router; all data fetching via React Server Components where possible
- [ ] `lib/api.ts` — typed API client (auto-generated from OpenAPI spec)
- [ ] WebSocket hook for real-time alert feed
- [ ] Authentication: JWT stored in httpOnly cookie; middleware protects all dashboard routes
- [ ] Multi-tenant: tenant switcher in nav (for admin users); all API calls scoped to active tenant
- [ ] Chart/visualization library: per `BRAND.md`
- [ ] Accessibility: WCAG 2.1 AA compliance

### Definition of Done
- Lighthouse score ≥ 90 (Performance, Accessibility, Best Practices)
- Dashboard reflects Immunity Score changes within 60 seconds of a DAG run completing
- Fraud Ring Visualizer renders a 500-node ring without jank
- All views defined in `BRAND.md` are implemented with zero visual deviations

---

## Sprint 9 — Hardening & Multi-Tenancy
**Weeks 17–18 | Goal: Production-safe, multi-tenant, cost-controlled, observable**

### Multi-Tenancy
- [ ] All Pinecone vectors namespaced by `tenant_id`
- [ ] All Neo4j queries filtered by `tenant_id` property on all nodes
- [ ] Kafka consumer groups isolated per tenant in managed deployments
- [ ] Tenant provisioning API: `POST /tenants` creates indexes, graph constraints, Airflow Variables

### Security Hardening
- [ ] Rotate all secrets via env; document rotation procedure in `infra/RUNBOOK.md`
- [ ] API rate limiting: per-tenant, per-endpoint (FastAPI middleware + Redis)
- [ ] Input sanitization: all user-supplied strings validated before Cypher or Pinecone metadata insertion
- [ ] Penetration test checklist: SQL injection, Cypher injection, prompt injection into agent prompts
- [ ] Dependency audit: `pip-audit` + `npm audit` in CI

### Cost Controls
- [ ] OpenAI API cost tracker: per-tenant spend logged to PostgreSQL; alert at 80% of monthly budget
- [ ] Pinecone query cache: Redis layer reduces redundant vector queries
- [ ] Airflow DAG cost estimation task runs before agent invocations; aborts if projected cost > budget cap

### Observability
- [ ] Structured JSON logging across all services (correlation ID threaded through)
- [ ] Prometheus metrics: detection latency, score computation time, Kafka lag, LLM cost per run
- [ ] Grafana dashboard (infra-level, not product dashboard): system health at a glance
- [ ] Distributed tracing: OpenTelemetry spans for Kafka → detection → score update path

### Performance
- [ ] Load test: 1,000 concurrent transactions/second with detection latency < 200ms p99
- [ ] Pinecone index optimization: tune `pods` and `replicas` for target throughput
- [ ] Neo4j GDS memory config tuned for Louvain on 10M+ node graphs

### Definition of Done
- Two tenants running simultaneously with zero data bleed between them (verified by integration test)
- Load test passes at 1,000 TPS
- Monthly cost per tenant is projected and within acceptable margin at target volume

---

## Sprint 10 — Beta Launch
**Weeks 19–20 | Goal: 5 paying customers onboarded; system stable under real load**

### Onboarding
- [ ] Tenant provisioning runbook: end-to-end steps for customer success team
- [ ] Historical data backfill pipeline: ingest customer's 90-day transaction history on onboarding
- [ ] Onboarding Airflow DAG: backfill → profile build → baseline score → first red-team run → dashboard access
- [ ] Customer-facing documentation: what is the Immunity Score, how to read the dashboard, what triggers an alert

### Beta Customer Operations
- [ ] Dedicated Slack channel per beta customer (internal) for issue triage
- [ ] Weekly Immunity Score report: auto-generated PDF/email summary per tenant
- [ ] Feedback collection: in-dashboard NPS widget + structured interview guide for CSM calls
- [ ] SLA definition: 99.5% API uptime, < 30-second score refresh, < 5-minute alert delivery

### Launch Readiness Checklist
- [ ] All seven hard rules from `CLAUDE.md` verified in production config
- [ ] `RED_TEAM_ENABLED=false` confirmed default in production Terraform/Helm values
- [ ] `SYNTHETIC_INJECTION_DRY_RUN=true` confirmed default in production
- [ ] Audit trail verified: `synthetic_audit` topic is append-only, retention = forever
- [ ] GDPR/compliance review: PII tokenization verified end-to-end by data protection officer
- [ ] Incident response playbook written and tested (tabletop exercise)
- [ ] Rollback plan for each service documented in `infra/RUNBOOK.md`

### Success Metrics (Beta)
| Metric | Target |
|---|---|
| Paying customers onboarded | ≥ 5 |
| Immunity Score baseline established | All 5 tenants |
| Synthetic attack types in library | ≥ 15 |
| Detection recall on synthetic fraud | ≥ 90% |
| False positive rate on legitimate txns | ≤ 2% |
| Customer NPS (end of sprint) | ≥ 40 |
| P1 incidents | 0 |

### Definition of Done
- 5 customers have an active Immunity Score visible in their dashboard
- First red-team DAG run completed for each customer
- No P1 or P2 incidents in final 5 days of sprint
- Beta retrospective completed; Sprint 11 backlog seeded with customer feedback

---

## Appendix: Risk Register

| Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|
| **Framing risk**: product perceived as attack tool | Medium | Critical | Hard-code "Fraud Immunity" framing in all copy; legal review before any public materials; see CLAUDE.md Rule 1 |
| **OpenAI cost overrun** | High | High | Budget caps per DAG run, per tenant, per month; Celery task aborts if over budget |
| **Synthetic fraud escapes to prod** | Low | Critical | Dry-run flag, synthetic tagging, audit trail, kill-switch; see CLAUDE.md Rules 3 & 5 |
| **False positive rate degrades UX** | Medium | High | FP rate is a component of Immunity Score; automatic alert if FP > 2% |
| **Pinecone index staleness** | Medium | Medium | Nightly refresh job + staleness alert if profile > 30 days old |
| **Neo4j performance on large graphs** | Medium | Medium | GDS memory tuning; Louvain scoped to active accounts only (last 90 days) |
| **Regulatory scrutiny on AI-generated fraud data** | Low | High | Legal review; data never leaves tenant's logical boundary; all synthetic data labeled |

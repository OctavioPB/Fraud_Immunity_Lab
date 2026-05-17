# Sovereign Fraud Immunity Lab

**Proactive fraud prevention through synthetic red-teaming.**  
Know your detection gaps before attackers find them.

---

## The Problem

Financial institutions learn about fraud detection failures the expensive way — after real attacks succeed. Reactive metrics (chargeback rate, transaction loss) tell you what already went wrong. They give you no signal on the attacks that are coming next week.

Security teams run red-team exercises once a quarter. Fraud teams rarely run them at all. The result: unknown blind spots in detection infrastructure that sophisticated attackers can map and exploit faster than institutions can discover them.

## The Solution

The Sovereign Fraud Immunity Lab continuously stress-tests your fraud detection stack using AI-generated synthetic attacks — before real criminals do. It gives every institution a single, actionable number: the **Immunity Score**.

- LLM-powered attacker agents generate novel phishing, money-laundering, account-takeover, and smurfing scenarios on a schedule
- Synthetic attacks are injected into your detection pipeline and evaluated for recall
- A composite Immunity Score (0–100) reflects detection coverage, false positive rate, model freshness, and scenario breadth — updated in near real-time
- A Neo4j graph layer continuously maps account relationship clusters to surface emerging fraud rings
- Every synthetic record is immutably tagged and audited — never confused with real fraud

The result is a posture score that moves *before* an attack happens, not after.

---

## Immunity Score

```
ImmunityScore (0–100) =
  0.40 × Detection Coverage    — % of known synthetic attack types your systems catch
+ 0.30 × False Positive Health — 1 − false positive rate on legitimate transactions
+ 0.20 × Model Freshness       — recency of behavioral profiles (stale > 30 days penalized)
+ 0.10 × Scenario Diversity    — breadth of attack categories tested in the last 30 days
```

A score above **80** means your systems detect most known attack types. Below **60** signals gaps a real attacker could exploit today.

---

## Architecture

```
┌─────────────────────────────────────────────────────────┐
│                   Next.js Dashboard                      │
│   Immunity Score · Fraud Ring Graph · Real-time Alerts  │
└───────────────────────────┬─────────────────────────────┘
                            │ REST + WebSocket
┌───────────────────────────▼─────────────────────────────┐
│                    FastAPI (api/)                         │
│   /immunity-score · /fraud-rings · /alerts · /tenants   │
│   JWT auth · per-tenant rate limiting · Prometheus       │
└──┬──────────────┬─────────────────┬──────────────────────┘
   │              │                 │
┌──▼──┐      ┌───▼───┐        ┌────▼────┐
│Redis│      │Pinecone│        │  Neo4j  │
│Cache│      │Vectors │        │  Graph  │
└──┬──┘      └───┬───┘        └────┬────┘
   │              │                 │
┌──▼──────────────▼─────────────────▼──────────────────────┐
│                   Apache Kafka                             │
│  transactions · login_events · devices · synthetic_audit  │
└───────────────────────────┬───────────────────────────────┘
                            │
┌───────────────────────────▼─────────────────────────────┐
│                Apache Airflow (red_team/)                 │
│  attack_orchestrator · scenario_coverage_dag             │
│  community_detection_dag · profile_refresh_dag           │
│  onboarding_dag · weekly_report_dag                      │
└──────────┬──────────────────────────────────────────────┘
           │
┌──────────▼──────────────┐
│   LLM Attacker Agents   │
│  phishing · laundering  │
│  account_takeover       │
└─────────────────────────┘
```

---

## Tech Stack

| Layer | Technology | Version |
|---|---|---|
| **Event Streaming** | Apache Kafka + Zookeeper | Confluent 7.7.1 |
| **Orchestration** | Apache Airflow | 2.10.3 (Python 3.11) |
| **Vector Store** | Pinecone | `text-embedding-3-large` embeddings |
| **Graph Database** | Neo4j + GDS (Louvain) | Community / Enterprise |
| **API** | FastAPI | Python 3.11+ |
| **Task Queue** | Celery + Redis | — |
| **Database** | PostgreSQL | 15+ |
| **Dashboard** | Next.js 14 (App Router) | Node 20+ |
| **Attacker Agents** | OpenAI GPT-4o | via API |
| **Anomaly Detection** | Isolation Forest + cosine distance | scikit-learn |
| **Observability** | Prometheus + Grafana | — |
| **Container Runtime** | Docker Compose | v2 |

---

## Prerequisites

| Tool | Minimum Version |
|---|---|
| Docker + Docker Compose v2 | Docker 24+ |
| Python | 3.11+ |
| Node.js | 20+ |
| GNU Make | Any |
| OpenAI API key | — |
| Pinecone account + API key | — |

> Neo4j, Kafka, Airflow, Redis, and PostgreSQL all run in Docker — no local installation needed for those.

---

## Installation

### 1. Clone and configure environment

```bash
git clone https://github.com/your-org/fraud-immunity-lab.git
cd fraud-immunity-lab

cp .env.example .env
```

Open `.env` and fill in the required values:

```bash
# Required — the stack will not start without these
OPENAI_API_KEY=sk-...
PINECONE_API_KEY=...
PINECONE_ENVIRONMENT=us-east-1-aws    # or your region

# Required for JWT auth
API_SECRET_KEY=<generate: openssl rand -hex 32>

# Defaults work for local dev — change for staging/prod
NEO4J_USERNAME=neo4j
NEO4J_PASSWORD=password
DATABASE_URL=postgresql://airflow:airflow@localhost:5432/airflow
REDIS_URL=redis://localhost:6379/0

# Safety flags — leave as-is for local dev
RED_TEAM_ENABLED=true
SYNTHETIC_INJECTION_DRY_RUN=false
```

See `.env.example` for the full variable reference with documentation.

### 2. Install Python dependencies

```bash
python -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

### 3. Install dashboard dependencies

```bash
cd dashboard
npm install
cd ..
```

### 4. Start the local stack

```bash
make up
```

This starts all services (Kafka, Zookeeper, Airflow, Neo4j, Redis, PostgreSQL, FastAPI, Next.js) with health checks. First run takes 2–3 minutes to pull images.

### 5. Seed topics, indexes, and graph constraints

```bash
make seed
```

Creates Kafka topics, Pinecone index namespaces, and Neo4j uniqueness constraints.

---

## Quick Start

Once `make up && make seed` completes:

### View the dashboard

Open [http://localhost:3000](http://localhost:3000)

Login: `admin` / password from `DASHBOARD_ADMIN_PASSWORD` in your `.env`

### Get your Immunity Score via API

```bash
# Get a JWT
TOKEN=$(curl -s -X POST http://localhost:8000/auth/token \
  -H "Content-Type: application/json" \
  -d '{"username":"admin","password":"admin","tenant_id":"default"}' \
  | jq -r .access_token)

# Fetch the score
curl -s -H "Authorization: Bearer $TOKEN" \
  http://localhost:8000/immunity-score | jq '{score, components}'
```

Expected on a fresh install (no red-team runs yet):

```json
{
  "score": 47.5,
  "components": {
    "detection_coverage": 0.0,
    "false_positive_health": 0.95,
    "model_freshness": 0.9,
    "scenario_diversity": 0.0
  }
}
```

### Run your first red-team attack cycle

```bash
# Trigger the attack orchestrator DAG
airflow dags trigger attack_orchestrator \
  --conf '{"tenant_id": "default"}'

# Or via Airflow UI: http://localhost:8080
# Login: admin / admin
```

The DAG generates synthetic fraud scenarios, injects them, evaluates detection recall, and recomputes the Immunity Score. Watch the score climb as gaps are identified.

### Onboard a new tenant

```bash
# Provision
curl -s -X POST http://localhost:8000/tenants \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"tenant_id": "acme-bank", "display_name": "ACME Bank NA", "monthly_llm_budget_usd": 150.0}' \
  | jq .

# Trigger onboarding pipeline
airflow dags trigger onboarding_dag \
  --conf '{"tenant_id": "acme-bank", "history_days": 90}'
```

---

## Make Targets

```
make up       Start all Docker services
make down     Stop and remove all containers
make seed     Create Kafka topics, Pinecone namespaces, Neo4j constraints
make test     Run unit + integration test suite
make lint     Run Ruff (Python) + ESLint (TypeScript)
make format   Run Black + Prettier
```

---

## Project Structure

```
fraud-immunity-lab/
├── api/                    FastAPI — Immunity Score, alerts, fraud rings, tenants
│   ├── routers/            Route handlers (immunity_score, alerts, fraud_rings, ...)
│   ├── middleware/         JWT auth, rate limiting, request logging
│   └── services/           ScoreCalculator, CostTracker, TenantProvisioner
├── red_team/               Synthetic attack generation and orchestration
│   ├── dags/               Airflow DAGs (attack_orchestrator, onboarding_dag, ...)
│   ├── agents/             LLM attacker agents (phishing, laundering, account_takeover)
│   └── scenarios/          Parameterized YAML attack scenario library (10+ types)
├── ml/                     Detection and graph intelligence
│   ├── embeddings/         Pinecone profile builder + synthetic injector
│   ├── anomaly/            Behavioral drift detector
│   └── graph/              Neo4j ingestion + Louvain community detection
├── ingestion/              Kafka consumers (transactions, logins, devices)
├── dashboard/              Next.js 14 dashboard (App Router)
│   ├── app/                Pages and layouts
│   ├── components/         ImmunityScoreHero, FraudRingVisualizer, AlertFeed, ...
│   └── lib/                Typed API client
├── tests/
│   ├── unit/               Fast tests, all external calls mocked
│   ├── integration/        Hits real services — tag: @pytest.mark.integration
│   └── red_team/           Validates synthetic fraud is detectable (build gate)
├── infra/
│   ├── RUNBOOK.md          Secret rotation and emergency procedures
│   ├── PENTEST.md          Penetration test checklist
│   ├── LAUNCH_CHECKLIST.md Production launch gate
│   └── INCIDENT_RESPONSE.md On-call runbooks
├── docs/
│   └── CUSTOMER_GUIDE.md   Customer-facing guide: Immunity Score, dashboard, FAQ
├── docker-compose.yml
├── Makefile
├── CLAUDE.md               Agent constitution — seven non-negotiable hard rules
└── PLAN.md                 Sprint roadmap (source of truth for delivery)
```

---

## Attack Scenario Library

The lab ships with 10 seed scenario types:

| # | Attack Type | Detection Signal |
|---|---|---|
| 01 | Card fraud (CNP) | Merchant mismatch, geo anomaly |
| 02 | Card fraud (skimming) | Rapid-fire transactions, duplicate merchant |
| 03 | Synthetic identity | Profile-less account, velocity spike |
| 04 | First-party fraud | Self-initiated dispute pattern |
| 05 | Mule account | Inbound-then-rapid-outbound flow |
| 06 | Smurfing | Small split transactions across merchants |
| 07 | Spear phishing | Login anomaly + immediate payee change |
| 08 | Credential stuffing | Device fingerprint mismatch, geo hop |
| 09 | Money laundering (layering) | Multi-hop graph pattern in Neo4j |
| 10 | Friendly fraud | Purchase + dispute timing pattern |

New scenarios are generated continuously by LLM agents and added to the library weekly.

---

## Safety and Compliance

This system generates synthetic fraud data. Several safeguards are mandatory and non-negotiable:

- **Kill-switch**: `RED_TEAM_ENABLED=false` stops all attacker agent DAGs immediately. Default is `false` in production.
- **Dry-run mode**: `SYNTHETIC_INJECTION_DRY_RUN=true` generates scenarios without publishing to Kafka. Default is `true` in staging.
- **Immutable tagging**: every synthetic record carries `{"synthetic": true, "origin": "red_team"}`. These tags cannot be stripped.
- **PII boundary**: account IDs are tokenized before embedding. Raw names, SSNs, or card numbers never enter Pinecone or Neo4j.
- **Audit trail**: all generated scenarios are written to the append-only `synthetic_audit` Kafka topic before injection.
- **Detection gate**: a new attack scenario type cannot be deployed to production unless the detection layer demonstrates ≥90% recall in staging first.

See [CLAUDE.md](CLAUDE.md) for the full seven hard rules and [infra/RUNBOOK.md](infra/RUNBOOK.md) for operational procedures.

---

## API Reference

Interactive docs available at [http://localhost:8000/docs](http://localhost:8000/docs) once the stack is running.

| Endpoint | Description |
|---|---|
| `GET /immunity-score` | Current score + component breakdown |
| `GET /immunity-score/history?days=30` | Score time series |
| `GET /immunity-score/scenarios` | Attack scenario coverage report |
| `GET /fraud-rings` | Detected fraud ring clusters |
| `GET /alerts` | Real-time alert feed |
| `POST /tenants` | Provision a new tenant |
| `GET /tenants/{id}/spend` | LLM cost tracking |
| `GET /reports/{id}/weekly` | Structured weekly report |
| `POST /feedback/nps` | NPS score submission |
| `GET /health` | Service health check |
| `GET /metrics` | Prometheus metrics |

All endpoints (except `/health`, `/metrics`, `/auth/token`) require a valid JWT. Requests are rate-limited per tenant per endpoint via Redis.

---

## Testing

```bash
# Unit tests (fast, no external services)
pytest tests/unit/ -v

# Integration tests (requires running stack)
pytest tests/integration/ -v -m integration

# Red-team validation (critical build gate)
pytest tests/red_team/ -v -m red_team
```

The red-team test suite is a build gate: synthetic fraud injected in dry-run mode **must** be flagged by the detection layer. A failing red-team test means the system's core contract is broken.

---

## License

Proprietary — Sovereign Fraud Immunity Lab. All rights reserved.

---

*Questions? See [docs/CUSTOMER_GUIDE.md](docs/CUSTOMER_GUIDE.md) for customer-facing documentation or [infra/INCIDENT_RESPONSE.md](infra/INCIDENT_RESPONSE.md) for operational runbooks.*

# CLAUDE.md — Agent Constitution
## Sovereign Fraud Immunity Lab (`inmunidad-sintetica`)

> This file is the authoritative behavioral contract for all AI agents, code generation, and automated workflows in this repository.
> Read it fully before taking any action. All seven hard rules at the bottom are non-negotiable.

---

## 1. Project Identity

| Field | Value |
|---|---|
| **Codename** | `inmunidad-sintetica` |
| **Full Name** | The Sovereign Fraud Immunity Lab |
| **Domain** | Fintech — Proactive Fraud Prevention |
| **Core Value Prop** | Synthetic fraud generation + real-time detection hardens infrastructure *before* criminals invent the next attack vector |
| **Strategic Framing** | **Fraud Immunity & Synthetic Red-Teaming**, NOT "fraud simulation" or "attack tooling" |
| **UI/Design Decisions** | → See [`BRAND.md`](./BRAND.md). Never encode visual or brand choices in this file. |

---

## 2. Repository Structure

```
inmunidad-sintetica/
├── CLAUDE.md                  # This file — agent constitution
├── BRAND.md                   # UI, design system, color, typography (authoritative)
├── PLAN.md                    # Sprint roadmap (source of truth for delivery)
├── .env.example               # All required environment variables (never .env itself)
│
├── ingestion/                 # Kafka consumers — transactional & behavioral event ingestion
│   ├── consumers/
│   └── schemas/               # Avro/Protobuf event schemas
│
├── red_team/                  # Airflow DAGs — synthetic fraud orchestration
│   ├── dags/
│   │   ├── attack_orchestrator.py
│   │   └── scenario_generator.py
│   ├── agents/                # LLM-powered attacker agents
│   │   ├── phishing_agent.py
│   │   ├── laundering_agent.py
│   │   └── base_agent.py
│   └── scenarios/             # Parameterized fraud scenario configs (YAML)
│
├── ml/                        # Vector search, anomaly detection, community detection
│   ├── embeddings/            # Pinecone ingestion + profile builder
│   ├── anomaly/               # Behavioral drift detection
│   └── graph/                 # Neo4j community detection (fraud rings)
│
├── api/                       # FastAPI — internal services + external integrations
│   ├── routers/
│   ├── middleware/
│   └── schemas/               # Pydantic models
│
├── dashboard/                 # Next.js 14 — Immunity Score dashboard
│   ├── app/
│   ├── components/
│   └── lib/
│
├── infra/                     # Docker Compose, Helm charts, Terraform (if applicable)
│
└── tests/
    ├── unit/
    ├── integration/
    └── red_team/              # Validation: synthetic fraud MUST be detectable
```

---

## 3. Tech Stack

### Backend & Data Pipeline
| Layer | Technology | Purpose |
|---|---|---|
| Event Ingestion | **Apache Kafka** | Real-time stream of transactions, login events, device metadata |
| Orchestration | **Apache Airflow** | DAGs that trigger red-team agent cycles and ML retraining |
| Attacker Agents | **LLMs via OpenAI API** | Generate novel phishing strategies, money-laundering patterns |
| Vector Store | **Pinecone** | Behavioral profiles ("clean" vs. "suspicious") + nearest-neighbor search |
| Graph DB | **Neo4j** | Account relationship graphs; community detection for fraud rings |
| API Layer | **FastAPI** | Internal microservices + webhook endpoints |
| Task Queue | **Celery + Redis** | Async ML inference jobs |

### Frontend
| Layer | Technology |
|---|---|
| Framework | **Next.js 14** (App Router) |
| Styling | Per `BRAND.md` |
| State | Zustand or React Query (per `BRAND.md`) |
| Charts | Per `BRAND.md` |

### AI / ML
| Component | Technology |
|---|---|
| Embeddings | OpenAI `text-embedding-3-large` |
| LLM Agents | OpenAI `gpt-4o` (attacker agents) |
| Anomaly Detection | Isolation Forest + vector distance thresholding |
| Graph Algorithms | Neo4j GDS (Louvain community detection) |

---

## 4. Core Domain Concepts

Agents MUST use this vocabulary consistently across code, comments, API contracts, and documentation.

| Term | Definition |
|---|---|
| **Synthetic Fraud** | AI-generated attack scenarios that mimic real criminal behavior; used exclusively to train detection systems |
| **Red-Team DAG** | An Airflow DAG that orchestrates one full attack cycle: generate → inject → detect → evaluate |
| **Attacker Agent** | An LLM-powered agent that designs a fraud scenario (phishing email, laundering chain, credential stuffing pattern) |
| **Behavioral Profile** | A vector embedding representing a user's normal transactional and login behavior stored in Pinecone |
| **Behavioral Drift** | Cosine distance between a new transaction's embedding and the user's baseline profile exceeds threshold |
| **Fraud Ring** | A cluster of accounts detected via Louvain community detection in Neo4j with suspicious inter-account flow |
| **Immunity Score** | Composite metric (0–100) reflecting: % of known synthetic attack types detectable + false positive rate + model staleness |
| **Scenario Config** | YAML file parameterizing an attack type: `attack_type`, `complexity`, `target_segment`, `evasion_tactics` |
| **Clean Profile** | Pinecone vector tagged `label: legitimate` — baseline for anomaly distance |
| **Suspicious Profile** | Pinecone vector tagged `label: synthetic_fraud` — reference for known attack embeddings |

---

## 5. Environment Variables

All secrets live in `.env` (never committed). Document every variable in `.env.example`.

```bash
# Kafka
KAFKA_BOOTSTRAP_SERVERS=
KAFKA_TOPIC_TRANSACTIONS=
KAFKA_TOPIC_LOGINS=
KAFKA_TOPIC_DEVICES=
KAFKA_CONSUMER_GROUP=

# Airflow
AIRFLOW__CORE__SQL_ALCHEMY_CONN=
AIRFLOW__CORE__FERNET_KEY=

# Pinecone
PINECONE_API_KEY=
PINECONE_ENVIRONMENT=
PINECONE_INDEX_CLEAN=
PINECONE_INDEX_SUSPICIOUS=

# Neo4j
NEO4J_URI=
NEO4J_USERNAME=
NEO4J_PASSWORD=
NEO4J_DATABASE=

# OpenAI
OPENAI_API_KEY=
OPENAI_EMBEDDING_MODEL=text-embedding-3-large
OPENAI_AGENT_MODEL=gpt-4o

# FastAPI
API_SECRET_KEY=
API_ALLOWED_ORIGINS=
JWT_ALGORITHM=HS256

# Redis / Celery
REDIS_URL=

# Feature Flags
RED_TEAM_ENABLED=true          # Master kill-switch for attacker agent DAGs
SYNTHETIC_INJECTION_DRY_RUN=false  # If true, generates but does not inject synthetic fraud
```

---

## 6. Coding Standards

### Python (Backend, ML, Agents, DAGs)
- Python **3.11+**
- Formatter: **Black** (`line-length = 88`)
- Linter: **Ruff**
- Type hints: mandatory on all public functions
- Docstrings: Google-style for all public classes and functions
- Async: use `async/await` in FastAPI routes; Celery tasks are sync
- Tests: **pytest** with fixtures in `conftest.py`; mock all external API calls

```python
# ✅ Correct
async def compute_behavioral_drift(
    user_id: str,
    transaction_embedding: list[float],
    threshold: float = 0.85,
) -> DriftResult:
    """
    Compare incoming transaction embedding to the user's clean baseline profile.

    Args:
        user_id: UUID of the account under evaluation.
        transaction_embedding: OpenAI embedding of the current transaction.
        threshold: Cosine similarity below which drift is flagged.

    Returns:
        DriftResult with score, flagged status, and nearest neighbors.
    """
    ...

# ❌ Wrong — no types, no docstring, sync in async context
def check_drift(uid, emb):
    ...
```

### TypeScript (Next.js Dashboard)
- Strict mode: `"strict": true` in `tsconfig.json`
- Formatter: **Prettier**
- Linter: **ESLint** with `next/core-web-vitals`
- No `any` — use `unknown` + type guards
- Components: functional only; no class components
- All UI/design decisions: see `BRAND.md`

### Airflow DAGs
- All DAGs must declare `tags=["red_team"]` or `tags=["ml"]` or `tags=["ingestion"]`
- Use `@task` decorator (TaskFlow API) over legacy operators where possible
- No hardcoded secrets — use Airflow Connections and Variables
- Every DAG must have a `doc_md` string explaining its purpose

### Neo4j / Cypher
- Node labels: `PascalCase` (`Account`, `Transaction`, `Device`)
- Relationship types: `SCREAMING_SNAKE_CASE` (`SENT_TO`, `LOGGED_IN_FROM`, `BELONGS_TO`)
- Always use parameterized queries — never string-interpolate user data into Cypher

---

## 7. Architecture Decision Records (Key Choices)

| Decision | Choice | Rationale |
|---|---|---|
| Vector store | Pinecone over Qdrant | Managed service reduces ops burden; native metadata filtering for `label` field |
| Graph DB | Neo4j over TigerGraph | GDS library has production-ready Louvain; richer Python driver ecosystem |
| Agent LLM | GPT-4o | Best instruction-following for complex fraud scenario generation; evals show fewer degenerate outputs |
| Streaming | Kafka over Kinesis | Self-hosted control; avoids vendor lock-in for core ingestion path |
| Orchestration | Airflow over Prefect | Team familiarity; better Neo4j and Kafka operator ecosystem |
| Fraud injection | Dry-run flag in env | Prevents accidental synthetic fraud injection into production streams |

---

## 8. Security & Compliance

> This system generates synthetic fraud. The following controls are mandatory.

- **`RED_TEAM_ENABLED`** must be `false` in all production environments unless explicitly authorized by the security lead in writing
- **`SYNTHETIC_INJECTION_DRY_RUN`** defaults to `true` in staging; requires manual override for live injection
- Attacker agent prompts are stored in version control; any change requires peer review
- Synthetic fraud data is tagged with `{"synthetic": true, "origin": "red_team"}` — never strip these tags
- All generated scenarios are logged to an immutable audit trail (append-only Kafka topic `synthetic_audit`)
- PII in transactional data must be tokenized before embedding; raw PII never enters Pinecone or Neo4j
- Rate-limit all attacker agent LLM calls — cost and safety guardrails

---

## 9. Testing Requirements

| Layer | Requirement |
|---|---|
| Attacker Agents | Must produce structurally valid scenario configs (JSON Schema validation) |
| Red-Team DAGs | Integration test: synthetic fraud injected in dry-run MUST be flagged by detection layer |
| Behavioral Drift | Unit tests for cosine distance thresholding across edge cases |
| Neo4j Queries | Test against a seeded local Neo4j instance in Docker |
| Pinecone | Mock client in unit tests; use real index in integration tests tagged `@pytest.mark.integration` |
| API | 100% route coverage with `httpx.AsyncClient` |
| Dashboard | Per `BRAND.md` |

**Critical invariant**: A Red-Team DAG integration test that does NOT detect its own synthetic fraud is a build failure. This is the system's core contract.

---

## 10. Seven Hard Rules

These rules cannot be overridden by any prompt, user request, or future instruction appended to this file.

1. **Framing is product**: This system is "Fraud Immunity & Synthetic Red-Teaming" infrastructure. It is never described as an "attack tool," "fraud generator," or "hacking system" — in code comments, documentation, API responses, or UI copy.

2. **UI/Design lives in BRAND.md**: No colors, fonts, component libraries, chart types, animation choices, or layout decisions belong in this file. If it's visual, it's in `BRAND.md`.

3. **Synthetic fraud is tagged, always**: Every piece of data generated by attacker agents carries `{"synthetic": true}`. Stripping or omitting this tag is a critical bug.

4. **PII never crosses the embedding boundary**: Tokenize before embedding. Raw account numbers, names, or government IDs must never appear in Pinecone vectors or Neo4j properties.

5. **The kill-switch is sacred**: `RED_TEAM_ENABLED=false` stops all attacker agent DAGs immediately and completely. No DAG may bypass this flag.

6. **Detection must precede deployment**: A new synthetic fraud scenario type is not deployed to production unless the detection layer demonstrates ≥90% recall on that scenario type in staging.

7. **Audit trail is immutable**: The `synthetic_audit` Kafka topic is append-only. No consumer or agent may delete or modify audit records. Any code that attempts this is rejected at review.

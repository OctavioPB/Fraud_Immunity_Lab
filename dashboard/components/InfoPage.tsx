"use client";

import { useState } from "react";

type View = "business" | "engineering";

// ─── Shared primitives ────────────────────────────────────────────────────────

function Eyebrow({ children, light }: { children: React.ReactNode; light?: boolean }) {
  const color = light ? "var(--gold-light)" : "var(--gold)";
  return (
    <div
      style={{
        display: "inline-flex",
        alignItems: "center",
        gap: 8,
        fontSize: 9,
        fontFamily: "var(--fb)",
        fontWeight: 500,
        letterSpacing: "4px",
        textTransform: "uppercase",
        color,
        marginBottom: 10,
      }}
    >
      <div style={{ width: 24, height: 1, flexShrink: 0, backgroundColor: color }} />
      {children}
    </div>
  );
}

// ─── Business view ────────────────────────────────────────────────────────────

const CAPABILITIES = [
  {
    num: "01",
    title: "Immunity Scoring",
    body: "A continuously computed composite metric (0–100) across four dimensions: detection coverage (40%), false-positive health (30%), model freshness (20%), and scenario diversity (10%). Updated after every red-team cycle.",
  },
  {
    num: "02",
    title: "Synthetic Red-Teaming",
    body: "LLM-powered attacker agents generate parameterized fraud scenarios across 10 canonical attack types — phishing, money laundering, account takeover, credential stuffing, smurfing, card fraud, synthetic identity, first-party fraud, mule accounts, and friendly fraud.",
  },
  {
    num: "03",
    title: "Fraud Ring Detection",
    body: "Louvain community detection runs on the account relationship graph in Neo4j and surfaces clusters of coordinated accounts exhibiting suspicious fund flows, shared device fingerprints, or shared IP addresses.",
  },
  {
    num: "04",
    title: "Behavioral Drift Detection",
    body: "Every transaction is embedded into a shared vector space. A cosine distance measurement between the incoming event and the account's established behavioral profile flags meaningful departures from baseline patterns.",
  },
  {
    num: "05",
    title: "Real-Time Alert Streaming",
    body: "Detection events stream to the dashboard via WebSocket as they are produced. Each alert carries a risk score, attack classification, account token, and a flag indicating whether the event originated from the red-team or from live traffic.",
  },
  {
    num: "06",
    title: "Hard Rule #6 Gate",
    body: "No attack scenario type is deployed to production unless the detection layer demonstrates ≥90% recall on that category in staging. The system tracks per-type recall and blocks promotion until the gate is cleared.",
  },
];

const SCORE_COMPONENTS = [
  { weight: "40%", label: "Detection Coverage", description: "Fraction of canonical attack types with ≥90% recall in the last 30 days." },
  { weight: "30%", label: "False-Positive Health", description: "1 minus the false-positive rate on legitimate transactions evaluated this cycle." },
  { weight: "20%", label: "Model Freshness", description: "Share of behavioral profiles updated within the model staleness window." },
  { weight: "10%", label: "Scenario Diversity", description: "Fraction of canonical attack types exercised by the red-team in the last 30 days." },
];

const BENEFITS = [
  {
    title: "Proactive gap identification",
    body: "Know which attack categories the detection stack cannot reliably catch before attackers find those gaps in production data. Coverage gaps are surfaced as specific attack types below the ≥90% recall threshold, not as abstract risk statements.",
  },
  {
    title: "Objective readiness measurement",
    body: "A single auditable score with four transparent sub-components replaces subjective assessments of detection quality. Each component is independently observable, which makes the score actionable rather than opaque.",
  },
  {
    title: "Controlled blast radius",
    body: "Synthetic fraud generation and live injection are independently toggled via environment flags — RED_TEAM_ENABLED and SYNTHETIC_INJECTION_DRY_RUN. Staging validation is fully decoupled from production event streams.",
  },
  {
    title: "Immutable audit trail",
    body: "Every synthetic scenario is tagged {synthetic: true} and logged to an append-only Kafka topic. Compliance teams have a complete record of what was tested, when, what the parameterization was, and whether the detection layer caught it.",
  },
  {
    title: "Multi-tenant isolation",
    body: "Each institution's behavioral profiles, detection metrics, and score history are namespaced at the JWT claim level. Tenant data never crosses boundaries in Pinecone, Neo4j, Redis, or API responses.",
  },
];

function CapabilityCard({ num, title, body }: { num: string; title: string; body: string }) {
  return (
    <div
      style={{
        backgroundColor: "var(--white)",
        borderRadius: 12,
        padding: "28px 28px 32px",
        boxShadow: "var(--shadow-card)",
        display: "flex",
        flexDirection: "column",
      }}
    >
      <div
        style={{
          fontFamily: "'Fraunces', Georgia, serif",
          fontSize: 44,
          fontWeight: 300,
          color: "var(--primary-30)",
          lineHeight: 1,
          marginBottom: 2,
          userSelect: "none",
        }}
      >
        {num}
      </div>
      <div
        style={{
          width: 36,
          height: 3,
          backgroundColor: "var(--gold)",
          borderRadius: 2,
          margin: "6px 0 14px",
        }}
      />
      <div
        style={{
          fontFamily: "'Fraunces', Georgia, serif",
          fontSize: 18,
          fontWeight: 300,
          color: "var(--dark)",
          marginBottom: 12,
          lineHeight: 1.3,
        }}
      >
        {title}
      </div>
      <p
        style={{
          fontFamily: "var(--fb)",
          fontSize: 13,
          color: "#475569",
          lineHeight: 1.7,
          margin: 0,
        }}
      >
        {body}
      </p>
    </div>
  );
}

function ScoreFormulaBar({ weight, label, description }: { weight: string; label: string; description: string }) {
  const pct = parseInt(weight);
  return (
    <div
      style={{
        display: "flex",
        gap: 20,
        alignItems: "flex-start",
        padding: "20px 0",
        borderBottom: "1px solid var(--primary-10)",
      }}
    >
      <div style={{ flexShrink: 0, width: 52, textAlign: "right" }}>
        <span
          style={{
            fontFamily: "'Fraunces', Georgia, serif",
            fontSize: 26,
            fontWeight: 300,
            color: "var(--gold)",
            lineHeight: 1,
          }}
        >
          {weight}
        </span>
      </div>
      <div style={{ flex: 1 }}>
        <div
          style={{
            fontFamily: "var(--fb)",
            fontSize: 11,
            fontWeight: 600,
            letterSpacing: "1.5px",
            textTransform: "uppercase",
            color: "var(--dark)",
            marginBottom: 6,
          }}
        >
          {label}
        </div>
        <div
          style={{
            height: 5,
            backgroundColor: "var(--primary-10)",
            borderRadius: 3,
            marginBottom: 8,
            overflow: "hidden",
          }}
        >
          <div
            style={{
              width: `${pct * 2.5}%`,
              height: "100%",
              backgroundColor: "var(--gold)",
              borderRadius: 3,
            }}
          />
        </div>
        <p
          style={{
            fontFamily: "var(--fb)",
            fontSize: 12,
            color: "var(--mid)",
            margin: 0,
            lineHeight: 1.6,
          }}
        >
          {description}
        </p>
      </div>
    </div>
  );
}

function BenefitCard({ title, body }: { title: string; body: string }) {
  return (
    <div
      style={{
        backgroundColor: "var(--white)",
        borderRadius: 12,
        padding: "24px 28px",
        boxShadow: "var(--shadow-card)",
        borderLeft: "3px solid var(--gold)",
      }}
    >
      <div
        style={{
          fontFamily: "'Fraunces', Georgia, serif",
          fontSize: 16,
          fontWeight: 300,
          color: "var(--dark)",
          marginBottom: 10,
          lineHeight: 1.3,
        }}
      >
        {title}
      </div>
      <p
        style={{
          fontFamily: "var(--fb)",
          fontSize: 13,
          color: "#475569",
          lineHeight: 1.7,
          margin: 0,
        }}
      >
        {body}
      </p>
    </div>
  );
}

function BusinessView() {
  return (
    <>
      {/* Overview */}
      <section style={{ padding: "56px 0 48px", borderBottom: "1px solid var(--primary-10)" }}>
        <Eyebrow>Overview</Eyebrow>
        <h2
          style={{
            fontFamily: "'Fraunces', Georgia, serif",
            fontSize: 28,
            fontWeight: 300,
            color: "var(--dark)",
            margin: "0 0 20px",
            lineHeight: 1.2,
            maxWidth: 740,
          }}
        >
          A testing infrastructure for fraud detection,{" "}
          <em style={{ fontStyle: "italic", color: "var(--gold)" }}>not</em> a fraud simulation tool
        </h2>
        <div
          style={{
            display: "grid",
            gridTemplateColumns: "1fr 1fr",
            gap: 40,
            maxWidth: 980,
          }}
        >
          <p style={{ fontFamily: "var(--fb)", fontSize: 14, color: "#475569", lineHeight: 1.75, margin: 0 }}>
            Financial institutions typically detect fraud after it occurs — they analyze production
            data for anomalous patterns and update models in response. This creates a window of
            exposure: the period between when a novel attack type first appears and when the
            detection system learns to catch it.
          </p>
          <p style={{ fontFamily: "var(--fb)", fontSize: 14, color: "#475569", lineHeight: 1.75, margin: 0 }}>
            The Fraud Immunity Lab inverts this cycle. Instead of waiting for attacks to materialize,
            it generates synthetic versions of known fraud categories, runs them through the live
            detection stack in a controlled environment, and measures whether each category is caught
            at sufficient recall. The result is a continuously updated readiness score.
          </p>
        </div>
      </section>

      {/* Capabilities */}
      <section style={{ padding: "56px 0 48px", borderBottom: "1px solid var(--primary-10)" }}>
        <Eyebrow>Capabilities</Eyebrow>
        <h2
          style={{
            fontFamily: "'Fraunces', Georgia, serif",
            fontSize: 22,
            fontWeight: 300,
            color: "var(--dark)",
            margin: "0 0 32px",
          }}
        >
          Six detection and{" "}
          <em style={{ fontStyle: "italic", color: "var(--gold)" }}>evaluation</em> capabilities
        </h2>
        <div
          style={{
            display: "grid",
            gridTemplateColumns: "repeat(3, 1fr)",
            gap: 16,
          }}
        >
          {CAPABILITIES.map((c) => (
            <CapabilityCard key={c.num} {...c} />
          ))}
        </div>
      </section>

      {/* Immunity Score formula */}
      <section style={{ padding: "56px 0 48px", borderBottom: "1px solid var(--primary-10)" }}>
        <Eyebrow>Immunity Score</Eyebrow>
        <h2
          style={{
            fontFamily: "'Fraunces', Georgia, serif",
            fontSize: 22,
            fontWeight: 300,
            color: "var(--dark)",
            margin: "0 0 8px",
          }}
        >
          How the score is{" "}
          <em style={{ fontStyle: "italic", color: "var(--gold)" }}>computed</em>
        </h2>
        <p
          style={{
            fontFamily: "var(--fb)",
            fontSize: 13,
            color: "var(--mid)",
            margin: "0 0 32px",
            lineHeight: 1.6,
          }}
        >
          A weighted average of four independently measurable sub-scores. Each component is
          observable on its own, making it clear which dimension is driving any change in the
          composite.
        </p>
        <div
          style={{
            display: "grid",
            gridTemplateColumns: "1fr 1fr",
            gap: "0 64px",
          }}
        >
          <div>
            {SCORE_COMPONENTS.slice(0, 2).map((c) => (
              <ScoreFormulaBar key={c.label} {...c} />
            ))}
          </div>
          <div>
            {SCORE_COMPONENTS.slice(2).map((c) => (
              <ScoreFormulaBar key={c.label} {...c} />
            ))}
          </div>
        </div>
      </section>

      {/* How it helps */}
      <section style={{ padding: "56px 0 80px" }}>
        <Eyebrow>For institutions</Eyebrow>
        <h2
          style={{
            fontFamily: "'Fraunces', Georgia, serif",
            fontSize: 22,
            fontWeight: 300,
            color: "var(--dark)",
            margin: "0 0 32px",
          }}
        >
          Practical outcomes for{" "}
          <em style={{ fontStyle: "italic", color: "var(--gold)" }}>risk teams</em>
        </h2>
        <div
          style={{
            display: "grid",
            gridTemplateColumns: "repeat(3, 1fr)",
            gap: 16,
          }}
        >
          {BENEFITS.map((b) => (
            <BenefitCard key={b.title} {...b} />
          ))}
        </div>
      </section>
    </>
  );
}

// ─── Engineering view ─────────────────────────────────────────────────────────

function ArchitectureDiagram() {
  return (
    <svg
      viewBox="0 0 840 492"
      width="100%"
      style={{ display: "block" }}
      aria-label="System architecture: event ingestion through Kafka, detection and red-team pipelines, converging at the Immunity Score engine"
    >
      <defs>
        <marker id="arr-navy" markerWidth="7" markerHeight="7" refX="5" refY="3" orient="auto">
          <path d="M0,0 L0,6 L7,3 z" fill="#99bbdd" />
        </marker>
        <marker id="arr-gold" markerWidth="7" markerHeight="7" refX="5" refY="3" orient="auto">
          <path d="M0,0 L0,6 L7,3 z" fill="#c8982a" />
        </marker>
      </defs>

      {/* ── Event sources ── */}
      {(
        [
          { x: 40, label: "Transaction Events", sub: "POS · Wire · Card · ACH" },
          { x: 302, label: "Login Events", sub: "Auth · Session · MFA" },
          { x: 564, label: "Device Signals", sub: "Fingerprint · IP · UA" },
        ] as const
      ).map(({ x, label, sub }) => (
        <g key={label}>
          <rect x={x} y={16} width={196} height={44} rx={6} fill="#e0eaf4" stroke="#003366" strokeWidth="1" />
          <text x={x + 98} y={32} textAnchor="middle" fill="#003366" fontSize={11} fontWeight={600}
                fontFamily="'Plus Jakarta Sans', sans-serif">{label}</text>
          <text x={x + 98} y={49} textAnchor="middle" fill="#336699" fontSize={9}
                fontFamily="'Plus Jakarta Sans', sans-serif">{sub}</text>
        </g>
      ))}

      {/* Source → Kafka connectors */}
      {[138, 400, 662].map((cx) => (
        <line key={cx} x1={cx} y1={60} x2={cx} y2={92} stroke="#99bbdd" strokeWidth="1.5" markerEnd="url(#arr-navy)" />
      ))}

      {/* ── Kafka bus ── */}
      <rect x={10} y={96} width={780} height={52} rx={8} fill="#003366" />
      <text x={400} y={117} textAnchor="middle" fill="white" fontSize={12} fontWeight={600}
            fontFamily="'Plus Jakarta Sans', sans-serif" letterSpacing="0.5">
        Apache Kafka · Real-Time Event Streaming
      </text>
      <text x={400} y={135} textAnchor="middle" fill="rgba(255,255,255,0.45)" fontSize={9}
            fontFamily="'Plus Jakarta Sans', sans-serif" letterSpacing="0.5">
        topics: transactions · logins · devices · synthetic_audit (append-only)
      </text>

      {/* Kafka → track connectors */}
      <line x1={200} y1={148} x2={200} y2={180} stroke="#99bbdd" strokeWidth="1.5" markerEnd="url(#arr-navy)" />
      <line x1={600} y1={148} x2={600} y2={180} stroke="#99bbdd" strokeWidth="1.5" markerEnd="url(#arr-navy)" />

      {/* ── Detection track header ── */}
      <rect x={10} y={184} width={375} height={44} rx={6} fill="#1a4d80" />
      <text x={197} y={203} textAnchor="middle" fill="white" fontSize={11} fontWeight={600}
            fontFamily="'Plus Jakarta Sans', sans-serif">Detection Pipeline</text>
      <text x={197} y={219} textAnchor="middle" fill="rgba(255,255,255,0.5)" fontSize={9}
            fontFamily="'Plus Jakarta Sans', sans-serif">FastAPI · Kafka Consumers</text>

      {/* Detection sub-boxes */}
      <rect x={10} y={236} width={182} height={40} rx={5} fill="#e0eaf4" />
      <text x={101} y={252} textAnchor="middle" fill="#003366" fontSize={10} fontWeight={600}
            fontFamily="'Plus Jakarta Sans', sans-serif">Pinecone</text>
      <text x={101} y={267} textAnchor="middle" fill="#336699" fontSize={9}
            fontFamily="'Plus Jakarta Sans', sans-serif">Vector Store · behavioral profiles</text>

      <rect x={203} y={236} width={182} height={40} rx={5} fill="#e0eaf4" />
      <text x={294} y={252} textAnchor="middle" fill="#003366" fontSize={10} fontWeight={600}
            fontFamily="'Plus Jakarta Sans', sans-serif">Neo4j + GDS</text>
      <text x={294} y={267} textAnchor="middle" fill="#336699" fontSize={9}
            fontFamily="'Plus Jakarta Sans', sans-serif">Graph DB · Louvain detection</text>

      <rect x={10} y={284} width={375} height={40} rx={5} fill="#e0eaf4" />
      <text x={197} y={300} textAnchor="middle" fill="#003366" fontSize={10} fontWeight={600}
            fontFamily="'Plus Jakarta Sans', sans-serif">Isolation Forest</text>
      <text x={197} y={315} textAnchor="middle" fill="#336699" fontSize={9}
            fontFamily="'Plus Jakarta Sans', sans-serif">Behavioral anomaly detection · cosine drift measurement</text>

      {/* ── Red-Team track header ── */}
      <rect x={415} y={184} width={375} height={44} rx={6} fill="#1a4d80" />
      <text x={602} y={203} textAnchor="middle" fill="white" fontSize={11} fontWeight={600}
            fontFamily="'Plus Jakarta Sans', sans-serif">Red-Team Pipeline</text>
      <text x={602} y={219} textAnchor="middle" fill="rgba(255,255,255,0.5)" fontSize={9}
            fontFamily="'Plus Jakarta Sans', sans-serif">Apache Airflow · DAG Orchestration</text>

      {/* Red-team sub-boxes */}
      <rect x={415} y={236} width={375} height={40} rx={5} fill="#e0eaf4" />
      <text x={602} y={252} textAnchor="middle" fill="#003366" fontSize={10} fontWeight={600}
            fontFamily="'Plus Jakarta Sans', sans-serif">GPT-4o Attacker Agents</text>
      <text x={602} y={267} textAnchor="middle" fill="#336699" fontSize={9}
            fontFamily="'Plus Jakarta Sans', sans-serif">10 attack types · parameterized scenario configs</text>

      <rect x={415} y={284} width={375} height={40} rx={5} fill="#e0eaf4" />
      <text x={602} y={300} textAnchor="middle" fill="#003366" fontSize={10} fontWeight={600}
            fontFamily="'Plus Jakarta Sans', sans-serif">synthetic_audit · Append-Only Log</text>
      <text x={602} y={315} textAnchor="middle" fill="#336699" fontSize={9}
            fontFamily="'Plus Jakarta Sans', sans-serif">every event tagged &#123;synthetic: true&#125; · immutable</text>

      {/* ── Feedback loop: synthetic events re-injected into Kafka ── */}
      <path d="M 790 304 Q 828 226 790 148" stroke="#c8982a" strokeWidth="1.5"
            fill="none" strokeDasharray="5 3" markerEnd="url(#arr-gold)" />
      <text x={816} y={228} textAnchor="middle" fill="#c8982a" fontSize={8}
            fontFamily="'Plus Jakarta Sans', sans-serif" transform="rotate(-90 816 228)">
        re-inject
      </text>

      {/* ── Convergence: tracks → Immunity Score ── */}
      <line x1={197} y1={324} x2={285} y2={356} stroke="#99bbdd" strokeWidth="1.5" markerEnd="url(#arr-navy)" />
      <line x1={602} y1={324} x2={515} y2={356} stroke="#99bbdd" strokeWidth="1.5" markerEnd="url(#arr-navy)" />

      {/* ── Immunity Score engine ── */}
      <rect x={190} y={360} width={420} height={52} rx={8} fill="#c8982a" />
      <text x={400} y={381} textAnchor="middle" fill="#1c1c2e" fontSize={13} fontWeight={600}
            fontFamily="'Plus Jakarta Sans', sans-serif">Immunity Score Engine</text>
      <text x={400} y={399} textAnchor="middle" fill="rgba(28,28,46,0.65)" fontSize={9}
            fontFamily="'Plus Jakarta Sans', sans-serif">
        0.40 × Coverage · 0.30 × FP Health · 0.20 × Freshness · 0.10 × Diversity
      </text>

      {/* Score → output */}
      <line x1={400} y1={412} x2={400} y2={431} stroke="#99bbdd" strokeWidth="1.5" markerEnd="url(#arr-navy)" />

      {/* ── Output row ── */}
      <rect x={95} y={434} width={185} height={40} rx={5} fill="#e0eaf4" />
      <text x={187} y={450} textAnchor="middle" fill="#003366" fontSize={10} fontWeight={600}
            fontFamily="'Plus Jakarta Sans', sans-serif">Redis Cache</text>
      <text x={187} y={464} textAnchor="middle" fill="#336699" fontSize={9}
            fontFamily="'Plus Jakarta Sans', sans-serif">Score TTL · alert buffer</text>

      <line x1={280} y1={454} x2={328} y2={454} stroke="#99bbdd" strokeWidth="1.5" markerEnd="url(#arr-navy)" />

      <rect x={330} y={434} width={275} height={40} rx={5} fill="#1a4d80" />
      <text x={467} y={450} textAnchor="middle" fill="white" fontSize={10} fontWeight={600}
            fontFamily="'Plus Jakarta Sans', sans-serif">Next.js Dashboard</text>
      <text x={467} y={464} textAnchor="middle" fill="rgba(255,255,255,0.5)" fontSize={9}
            fontFamily="'Plus Jakarta Sans', sans-serif">Server render · WebSocket alert stream</text>
    </svg>
  );
}

const TECH_STACK = [
  { layer: "Event Streaming", tech: "Apache Kafka + Schema Registry", purpose: "Real-time ingestion of transactions, login events, and device signals; append-only synthetic_audit topic." },
  { layer: "Orchestration", tech: "Apache Airflow 2.10", purpose: "Red-team DAG scheduling, ML retraining triggers, per-cycle recall measurement and Immunity Score updates." },
  { layer: "Attacker Agents", tech: "OpenAI GPT-4o", purpose: "Generates internally consistent multi-step fraud scenario configs from YAML parameterization across 10 attack types." },
  { layer: "Embeddings", tech: "text-embedding-3-large", purpose: "Behavioral profile vectors for baseline establishment, drift measurement, and nearest-neighbor similarity search." },
  { layer: "Vector Store", tech: "Pinecone", purpose: "Stores behavioral profiles with label metadata (legitimate / synthetic_fraud); powers cosine similarity queries." },
  { layer: "Graph Database", tech: "Neo4j 5 + GDS", purpose: "Account relationship graph with SENT_TO and LOGGED_IN_FROM edges; Louvain community detection for fraud rings." },
  { layer: "API Layer", tech: "FastAPI 0.115 + Pydantic v2", purpose: "Internal microservices, JWT HS256 auth, WebSocket alert streaming, multi-tenant data isolation." },
  { layer: "Task Queue", tech: "Celery + Redis", purpose: "Async ML inference jobs; Immunity Score and fraud ring result caching with configurable TTL." },
  { layer: "Dashboard", tech: "Next.js 16 (App Router)", purpose: "Server-rendered data fetch per page load; real-time client-side WebSocket updates for the alert feed." },
  { layer: "Containerization", tech: "Docker Compose", purpose: "Local development stack mirroring the production service topology." },
];

const FLOW_STEPS = [
  {
    num: "01",
    label: "Ingestion",
    body: "Financial events (transactions, logins, device signals) enter via Kafka producers and land in three topic-namespaced partitions. Each event is validated against its registered Avro schema in the Schema Registry before being accepted.",
  },
  {
    num: "02",
    label: "Embedding",
    body: "FastAPI Kafka consumers decode each event, extract the relevant features, compute a text-embedding-3-large vector via the OpenAI embedding API, and upsert the vector to Pinecone under the account's behavioral profile. Simultaneously, Neo4j is updated with SENT_TO and LOGGED_IN_FROM edges.",
  },
  {
    num: "03",
    label: "Red-Team Cycle",
    body: "On schedule, Airflow's Attack Orchestrator DAG prompts a GPT-4o attacker agent to generate a parameterized fraud scenario config. If SYNTHETIC_INJECTION_DRY_RUN=false, synthetic events are injected into the Kafka stream using the same schema as real events.",
  },
  {
    num: "04",
    label: "Detection Measurement",
    body: "Synthetic events flow through the same detection pipeline as real events. At the evaluation step, the system measures recall: what fraction of the injected category were flagged with the correct attack classification at the required confidence threshold.",
  },
  {
    num: "05",
    label: "Score Computation",
    body: "The Scenario Coverage DAG reads per-type recall from Redis and computes the four Immunity Score sub-components. The composite score (0–100) is cached with a TTL. Any attack type below ≥90% recall is marked as a coverage gap and flagged in the dashboard.",
  },
  {
    num: "06",
    label: "Dashboard Delivery",
    body: "The Next.js dashboard fetches the current score and history server-side on each page render. Real-time detection alerts stream client-side via WebSocket from the FastAPI alerts endpoint, with automatic reconnection on disconnect.",
  },
];

const DECISIONS = [
  {
    decision: "Event streaming",
    choice: "Kafka over Kinesis or Pub/Sub",
    rationale: "Self-hosted control over the ingestion path avoids vendor lock-in for a system likely to run in multi-cloud or private data center environments. Schema Registry gives each topic a versioned contract.",
  },
  {
    decision: "Graph database",
    choice: "Neo4j + GDS over relational joins",
    rationale: "The Louvain algorithm in GDS is production-ready. Relational joins at graph traversal depth >2 perform orders of magnitude worse than native graph traversal for the fraud ring detection use case.",
  },
  {
    decision: "Vector store",
    choice: "Pinecone over Qdrant",
    rationale: "Managed service reduces operational burden. Native metadata filtering on the label field (legitimate / synthetic_fraud) supports clean and suspicious profile separation without a secondary index.",
  },
  {
    decision: "Attacker agent",
    choice: "GPT-4o over smaller models",
    rationale: "Fraud scenario generation requires understanding domain context, constructing internally consistent multi-step attack sequences, and avoiding degenerate or structurally invalid outputs. Smaller models produced a higher rate of unusable configs.",
  },
];

function FlowStep({ num, label, body }: { num: string; label: string; body: string }) {
  return (
    <div style={{ display: "flex", gap: 24, padding: "24px 0", borderBottom: "1px solid var(--primary-10)" }}>
      <div style={{ flexShrink: 0 }}>
        <div
          style={{
            fontFamily: "'Fraunces', Georgia, serif",
            fontSize: 32,
            fontWeight: 300,
            color: "var(--primary-30)",
            lineHeight: 1,
          }}
        >
          {num}
        </div>
      </div>
      <div>
        <div
          style={{
            fontFamily: "var(--fb)",
            fontSize: 9,
            fontWeight: 700,
            letterSpacing: "2px",
            textTransform: "uppercase",
            color: "var(--gold)",
            marginBottom: 6,
          }}
        >
          {label}
        </div>
        <p style={{ fontFamily: "var(--fb)", fontSize: 13, color: "#475569", lineHeight: 1.7, margin: 0 }}>
          {body}
        </p>
      </div>
    </div>
  );
}

function AdrCard({ decision, choice, rationale }: { decision: string; choice: string; rationale: string }) {
  return (
    <div
      style={{
        backgroundColor: "var(--white)",
        borderRadius: 12,
        padding: "24px 28px",
        boxShadow: "var(--shadow-card)",
        borderTop: "3px solid var(--gold)",
      }}
    >
      <div
        style={{
          fontFamily: "var(--fb)",
          fontSize: 9,
          fontWeight: 700,
          letterSpacing: "2px",
          textTransform: "uppercase",
          color: "var(--mid)",
          marginBottom: 6,
        }}
      >
        {decision}
      </div>
      <div
        style={{
          fontFamily: "'Fraunces', Georgia, serif",
          fontSize: 15,
          fontWeight: 300,
          color: "var(--dark)",
          marginBottom: 12,
          lineHeight: 1.3,
        }}
      >
        {choice}
      </div>
      <p style={{ fontFamily: "var(--fb)", fontSize: 12, color: "#475569", lineHeight: 1.65, margin: 0 }}>
        {rationale}
      </p>
    </div>
  );
}

function EngineeringView() {
  return (
    <>
      {/* Architecture diagram */}
      <section style={{ padding: "56px 0 48px", borderBottom: "1px solid var(--primary-10)" }}>
        <Eyebrow>Architecture</Eyebrow>
        <h2
          style={{
            fontFamily: "'Fraunces', Georgia, serif",
            fontSize: 22,
            fontWeight: 300,
            color: "var(--dark)",
            margin: "0 0 8px",
          }}
        >
          System{" "}
          <em style={{ fontStyle: "italic", color: "var(--gold)" }}>pipeline</em>
        </h2>
        <p style={{ fontFamily: "var(--fb)", fontSize: 13, color: "var(--mid)", margin: "0 0 28px", lineHeight: 1.6 }}>
          Real events and synthetic events share the same ingestion pipeline. The gold dashed line on
          the right shows the red-team feedback loop: synthetic events are re-injected into Kafka as
          though they were organic, then measured by the detection stack.
        </p>
        <div
          style={{
            backgroundColor: "var(--white)",
            borderRadius: 14,
            boxShadow: "var(--shadow-card)",
            padding: "32px 28px",
            overflow: "hidden",
          }}
        >
          <ArchitectureDiagram />
        </div>
      </section>

      {/* Tech stack table */}
      <section style={{ padding: "56px 0 48px", borderBottom: "1px solid var(--primary-10)" }}>
        <Eyebrow>Tech Stack</Eyebrow>
        <h2
          style={{
            fontFamily: "'Fraunces', Georgia, serif",
            fontSize: 22,
            fontWeight: 300,
            color: "var(--dark)",
            margin: "0 0 24px",
          }}
        >
          Technologies and{" "}
          <em style={{ fontStyle: "italic", color: "var(--gold)" }}>rationale</em>
        </h2>
        <div
          style={{
            backgroundColor: "var(--white)",
            borderRadius: 12,
            overflow: "hidden",
            boxShadow: "var(--shadow-card)",
          }}
        >
          <table style={{ width: "100%", borderCollapse: "collapse" }}>
            <thead>
              <tr style={{ backgroundColor: "var(--primary)" }}>
                {["Layer", "Technology", "Purpose"].map((h) => (
                  <th
                    key={h}
                    style={{
                      padding: "12px 20px",
                      textAlign: "left",
                      fontFamily: "var(--fb)",
                      fontSize: 9,
                      fontWeight: 600,
                      letterSpacing: "2px",
                      textTransform: "uppercase",
                      color: "var(--white)",
                    }}
                  >
                    {h}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {TECH_STACK.map(({ layer, tech, purpose }, i) => (
                <tr
                  key={layer}
                  style={{
                    backgroundColor: i % 2 === 0 ? "var(--white)" : "var(--primary-10)",
                    borderBottom: "1px solid var(--primary-10)",
                  }}
                >
                  <td
                    style={{
                      padding: "12px 20px",
                      fontFamily: "var(--fb)",
                      fontSize: 9,
                      fontWeight: 700,
                      letterSpacing: "1.5px",
                      textTransform: "uppercase",
                      color: "var(--gold)",
                      whiteSpace: "nowrap",
                      verticalAlign: "top",
                    }}
                  >
                    {layer}
                  </td>
                  <td
                    style={{
                      padding: "12px 20px",
                      fontFamily: "Courier New, monospace",
                      fontSize: 12,
                      color: "var(--dark)",
                      whiteSpace: "nowrap",
                      verticalAlign: "top",
                    }}
                  >
                    {tech}
                  </td>
                  <td
                    style={{
                      padding: "12px 20px",
                      fontFamily: "var(--fb)",
                      fontSize: 12,
                      color: "#475569",
                      lineHeight: 1.6,
                      verticalAlign: "top",
                    }}
                  >
                    {purpose}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>

      {/* Data flow */}
      <section style={{ padding: "56px 0 48px", borderBottom: "1px solid var(--primary-10)" }}>
        <Eyebrow>Data Flow</Eyebrow>
        <h2
          style={{
            fontFamily: "'Fraunces', Georgia, serif",
            fontSize: 22,
            fontWeight: 300,
            color: "var(--dark)",
            margin: "0 0 8px",
          }}
        >
          End-to-end{" "}
          <em style={{ fontStyle: "italic", color: "var(--gold)" }}>event lifecycle</em>
        </h2>
        <p style={{ fontFamily: "var(--fb)", fontSize: 13, color: "var(--mid)", margin: "0 0 8px", lineHeight: 1.6 }}>
          From raw financial event to scored detection result, across six pipeline stages.
        </p>
        <div style={{ maxWidth: 820 }}>
          {FLOW_STEPS.map((s) => (
            <FlowStep key={s.num} {...s} />
          ))}
        </div>
      </section>

      {/* Design decisions */}
      <section style={{ padding: "56px 0 80px" }}>
        <Eyebrow>Design Decisions</Eyebrow>
        <h2
          style={{
            fontFamily: "'Fraunces', Georgia, serif",
            fontSize: 22,
            fontWeight: 300,
            color: "var(--dark)",
            margin: "0 0 8px",
          }}
        >
          Key{" "}
          <em style={{ fontStyle: "italic", color: "var(--gold)" }}>architectural choices</em>
        </h2>
        <p style={{ fontFamily: "var(--fb)", fontSize: 13, color: "var(--mid)", margin: "0 0 28px", lineHeight: 1.6 }}>
          Each decision below was evaluated against at least one alternative. The rationale records
          the specific constraint or observation that drove the choice.
        </p>
        <div
          style={{
            display: "grid",
            gridTemplateColumns: "repeat(2, 1fr)",
            gap: 16,
          }}
        >
          {DECISIONS.map((d) => (
            <AdrCard key={d.decision} {...d} />
          ))}
        </div>
      </section>
    </>
  );
}

// ─── Page root ────────────────────────────────────────────────────────────────

export default function InfoPage() {
  const [view, setView] = useState<View>("business");

  const heroStyle: React.CSSProperties = {
    backgroundColor: "var(--primary)",
    backgroundImage: `
      linear-gradient(rgba(255,255,255,0.025) 1px, transparent 1px),
      linear-gradient(90deg, rgba(255,255,255,0.025) 1px, transparent 1px)
    `,
    backgroundSize: "48px 48px",
    padding: "56px 48px 0",
  };

  const TAB_LABELS: { id: View; label: string; sub: string }[] = [
    { id: "business", label: "Business View", sub: "What it does and how it helps" },
    { id: "engineering", label: "Engineering View", sub: "Architecture, stack, and decisions" },
  ];

  return (
    <>
      {/* Hero with tab bar */}
      <section style={heroStyle} aria-label="Fraud Immunity Lab — system overview">
        <div style={{ maxWidth: 1300, margin: "0 auto" }}>
          <Eyebrow light>Fraud Immunity Lab</Eyebrow>
          <h1
            style={{
              fontFamily: "'Fraunces', Georgia, serif",
              fontSize: 42,
              fontWeight: 300,
              color: "var(--white)",
              margin: "0 0 12px",
              lineHeight: 1.15,
              maxWidth: 680,
            }}
          >
            Proactive fraud{" "}
            <em style={{ fontStyle: "italic", color: "var(--gold-light)" }}>immunity</em>{" "}
            infrastructure
          </h1>
          <p
            style={{
              fontFamily: "var(--fb)",
              fontSize: 14,
              color: "rgba(255,255,255,0.45)",
              margin: "0 0 40px",
              lineHeight: 1.65,
              maxWidth: 560,
            }}
          >
            A synthetic red-teaming and detection validation platform for financial institutions.
            Tests detection coverage before attackers do.
          </p>

          {/* Tab bar */}
          <div style={{ display: "flex", gap: 4 }}>
            {TAB_LABELS.map(({ id, label, sub }) => {
              const isActive = view === id;
              return (
                <button
                  key={id}
                  onClick={() => setView(id)}
                  style={{
                    background: "none",
                    backgroundColor: "transparent",
                    border: "none",
                    borderBottom: `2px solid ${isActive ? "var(--gold-light)" : "transparent"}`,
                    marginBottom: -1,
                    color: isActive ? "var(--gold-light)" : "rgba(255,255,255,0.4)",
                    cursor: "pointer",
                    fontFamily: "var(--fb)",
                    padding: "10px 20px 14px",
                    textAlign: "left",
                    transition: "color 0.15s, border-color 0.15s",
                  }}
                >
                  <div style={{ fontSize: 10, fontWeight: 600, letterSpacing: "1.5px", textTransform: "uppercase" }}>
                    {label}
                  </div>
                  <div style={{ fontSize: 10, color: isActive ? "rgba(232,196,106,0.6)" : "rgba(255,255,255,0.25)", marginTop: 3 }}>
                    {sub}
                  </div>
                </button>
              );
            })}
          </div>
        </div>
      </section>

      {/* Body */}
      <main
        style={{
          flex: 1,
          backgroundColor: "var(--light)",
        }}
      >
        <div
          style={{
            maxWidth: 1300,
            margin: "0 auto",
            padding: "0 48px",
          }}
        >
          {view === "business" ? <BusinessView /> : <EngineeringView />}
        </div>
      </main>
    </>
  );
}

"use client";

import { useState, useCallback } from "react";

const _API =
  typeof window === "undefined"
    ? ""
    : (process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000");

type OpStatus = "idle" | "running" | "success" | "error";

interface OpResult {
  steps: string[];
  errors: string[];
  ok: boolean;
}

function useAdminOp(endpoint: string) {
  const [status, setStatus] = useState<OpStatus>("idle");
  const [result, setResult] = useState<OpResult | null>(null);

  const run = useCallback(async () => {
    setStatus("running");
    setResult(null);
    try {
      const res = await fetch(`${_API}/admin/${endpoint}`, {
        method: "POST",
        credentials: "include",
      });
      const data: OpResult = await res.json();
      setResult(data);
      setStatus(data.ok ? "success" : "error");
    } catch (err) {
      setResult({ steps: [], errors: [String(err)], ok: false });
      setStatus("error");
    }
  }, [endpoint]);

  return { status, result, run };
}

function StepLog({ result, status }: { result: OpResult | null; status: OpStatus }) {
  if (status === "idle") return null;
  if (status === "running") {
    return (
      <div
        style={{
          marginTop: 16,
          padding: "12px 14px",
          backgroundColor: "var(--primary-10)",
          borderRadius: 8,
          fontFamily: "var(--fb)",
          fontSize: 12,
          color: "var(--mid)",
        }}
      >
        Running…
      </div>
    );
  }
  if (!result) return null;

  return (
    <div
      style={{
        marginTop: 16,
        borderRadius: 8,
        overflow: "hidden",
        border: "1px solid var(--primary-10)",
      }}
    >
      {result.steps.map((step, i) => (
        <div
          key={i}
          style={{
            display: "flex",
            alignItems: "flex-start",
            gap: 10,
            padding: "9px 14px",
            backgroundColor: i % 2 === 0 ? "var(--white)" : "var(--primary-10)",
            fontFamily: "var(--fb)",
            fontSize: 12,
            color: "var(--dark)",
            lineHeight: 1.5,
          }}
        >
          <span style={{ color: "#27B97C", flexShrink: 0, marginTop: 1 }}>✓</span>
          {step}
        </div>
      ))}
      {result.errors.map((err, i) => (
        <div
          key={`e${i}`}
          style={{
            display: "flex",
            alignItems: "flex-start",
            gap: 10,
            padding: "9px 14px",
            backgroundColor: "rgba(224,52,72,0.05)",
            fontFamily: "var(--fb)",
            fontSize: 12,
            color: "#7A1020",
            lineHeight: 1.5,
          }}
        >
          <span style={{ color: "#E03448", flexShrink: 0, marginTop: 1 }}>✕</span>
          {err}
        </div>
      ))}
    </div>
  );
}

function ActionCard({
  title,
  eyebrow,
  description,
  detail,
  buttonLabel,
  buttonColor,
  dangerous,
  onRun,
  status,
  result,
}: {
  title: string;
  eyebrow: string;
  description: string;
  detail: string;
  buttonLabel: string;
  buttonColor: string;
  dangerous?: boolean;
  onRun: () => void;
  status: OpStatus;
  result: OpResult | null;
}) {
  const [confirming, setConfirming] = useState(false);

  function handleClick() {
    if (dangerous && !confirming) {
      setConfirming(true);
      setTimeout(() => setConfirming(false), 5000);
      return;
    }
    setConfirming(false);
    onRun();
  }

  const isRunning = status === "running";
  const isDone = status === "success" || status === "error";

  return (
    <div
      style={{
        backgroundColor: "var(--white)",
        borderRadius: 12,
        overflow: "hidden",
        boxShadow: "0 1px 4px rgba(0,51,102,0.08)",
      }}
    >
      <div style={{ height: 3, backgroundColor: "var(--gold)" }} />

      <div style={{ padding: "24px 28px 28px" }}>
        {/* Eyebrow */}
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
            color: "var(--gold)",
            marginBottom: 10,
          }}
        >
          <div
            style={{
              width: 16,
              height: 1,
              flexShrink: 0,
              backgroundColor: "var(--gold)",
            }}
          />
          {eyebrow}
        </div>

        {/* Title */}
        <h2
          style={{
            fontFamily: "'Fraunces', Georgia, serif",
            fontSize: 22,
            fontWeight: 300,
            color: "var(--dark)",
            margin: "0 0 8px",
            lineHeight: 1.25,
          }}
        >
          {title}
        </h2>

        {/* Description */}
        <p
          style={{
            fontFamily: "var(--fb)",
            fontSize: 13,
            color: "var(--mid)",
            lineHeight: 1.65,
            margin: "0 0 16px",
          }}
        >
          {description}
        </p>

        {/* Detail list */}
        <div
          style={{
            backgroundColor: "var(--primary-10)",
            borderRadius: 8,
            padding: "12px 16px",
            fontFamily: "var(--fb)",
            fontSize: 12,
            color: "#475569",
            lineHeight: 1.7,
            marginBottom: 20,
            whiteSpace: "pre-line",
          }}
        >
          {detail}
        </div>

        {/* Action area */}
        {confirming ? (
          <div
            style={{
              display: "flex",
              gap: 10,
              alignItems: "center",
            }}
          >
            <div
              style={{
                flex: 1,
                fontFamily: "var(--fb)",
                fontSize: 12,
                color: "#7A1020",
                backgroundColor: "rgba(224,52,72,0.07)",
                borderRadius: 8,
                padding: "10px 14px",
              }}
            >
              This will permanently delete all tenant data. Are you sure?
            </div>
            <button
              onClick={() => setConfirming(false)}
              style={{
                padding: "10px 16px",
                border: "1.5px solid var(--primary-10)",
                borderRadius: 8,
                background: "transparent",
                fontFamily: "var(--fb)",
                fontSize: 12,
                color: "var(--mid)",
                cursor: "pointer",
                flexShrink: 0,
              }}
            >
              Cancel
            </button>
            <button
              onClick={handleClick}
              style={{
                padding: "10px 18px",
                border: "none",
                borderRadius: 8,
                backgroundColor: "#E03448",
                color: "var(--white)",
                fontFamily: "var(--fb)",
                fontSize: 12,
                fontWeight: 600,
                cursor: "pointer",
                flexShrink: 0,
                letterSpacing: "0.5px",
              }}
            >
              Confirm
            </button>
          </div>
        ) : (
          <button
            onClick={handleClick}
            disabled={isRunning}
            style={{
              padding: "11px 24px",
              border: "none",
              borderRadius: 8,
              backgroundColor: isRunning
                ? "var(--primary-60)"
                : isDone
                ? "var(--primary-80)"
                : buttonColor,
              color: "var(--white)",
              fontFamily: "var(--fb)",
              fontSize: 13,
              fontWeight: 600,
              cursor: isRunning ? "not-allowed" : "pointer",
              transition: "background-color 0.15s",
              letterSpacing: "0.5px",
            }}
          >
            {isRunning
              ? "Working…"
              : isDone
              ? "Run again"
              : buttonLabel}
          </button>
        )}

        {/* Step log */}
        <StepLog result={result} status={status} />

        {/* Status summary badge */}
        {isDone && result && (
          <div
            style={{
              marginTop: 12,
              display: "inline-flex",
              alignItems: "center",
              gap: 6,
              backgroundColor: result.ok ? "#E0F7EF" : "#FDEAEA",
              color: result.ok ? "#0D5C3A" : "#7A1020",
              borderRadius: 20,
              padding: "4px 12px",
              fontSize: 10,
              fontFamily: "var(--fb)",
              fontWeight: 500,
            }}
          >
            <span
              style={{
                width: 6,
                height: 6,
                borderRadius: "50%",
                backgroundColor: result.ok ? "#27B97C" : "#E03448",
                flexShrink: 0,
              }}
            />
            {result.ok ? "Completed successfully" : "Completed with errors"}
          </div>
        )}
      </div>
    </div>
  );
}

export default function AdminPanel() {
  const reset = useAdminOp("reset");
  const seed = useAdminOp("seed");

  return (
    <main
      style={{
        flex: 1,
        maxWidth: 900,
        width: "100%",
        margin: "0 auto",
        padding: "56px 48px 96px",
        boxSizing: "border-box",
      }}
    >
      {/* Page header */}
      <div style={{ marginBottom: 40 }}>
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
            color: "var(--gold)",
            marginBottom: 10,
          }}
        >
          <div
            style={{
              width: 24,
              height: 1,
              flexShrink: 0,
              backgroundColor: "var(--gold)",
            }}
          />
          Administration
        </div>
        <h1
          style={{
            fontFamily: "'Fraunces', Georgia, serif",
            fontSize: 32,
            fontWeight: 300,
            color: "var(--dark)",
            margin: "0 0 8px",
            lineHeight: 1.2,
          }}
        >
          Admin <em style={{ fontStyle: "italic" }}>Controls</em>
        </h1>
        <p
          style={{
            fontFamily: "var(--fb)",
            fontSize: 14,
            color: "var(--mid)",
            margin: 0,
          }}
        >
          Tenant-scoped database management · Changes are isolated to your tenant
        </p>
      </div>

      {/* Warning callout */}
      <div
        style={{
          backgroundColor: "var(--white)",
          borderRadius: 10,
          padding: "14px 20px",
          boxShadow: "0 1px 3px rgba(0,51,102,0.07)",
          borderLeft: "3px solid var(--gold)",
          marginBottom: 32,
          fontFamily: "var(--fb)",
          fontSize: 12,
          color: "#475569",
          lineHeight: 1.6,
        }}
      >
        <span
          style={{
            fontWeight: 700,
            textTransform: "uppercase",
            letterSpacing: "1px",
            fontSize: 9,
            color: "var(--gold)",
            display: "block",
            marginBottom: 4,
          }}
        >
          Scope
        </span>
        All operations are scoped to your JWT tenant claim. You cannot read or
        modify data belonging to other tenants. These controls are intended for
        demo setup and local test environment management.
      </div>

      {/* Action cards */}
      <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 24 }}>
        <ActionCard
          eyebrow="Destructive"
          title="Clear Database"
          description="Remove all data associated with your tenant from every backing store."
          detail={
            "· Redis — all detection_recall, fp_rate, scenario, and score cache keys\n" +
            "· Neo4j — all Account, Transaction, FraudRing nodes and relationships\n" +
            "· PostgreSQL — all immunity_score_history rows"
          }
          buttonLabel="Clear tenant data"
          buttonColor="var(--primary)"
          dangerous
          onRun={reset.run}
          status={reset.status}
          result={reset.result}
        />

        <ActionCard
          eyebrow="Demo Setup"
          title="Seed Demo Data"
          description="Populate all backing stores with realistic synthetic data so the dashboard renders a live, meaningful state."
          detail={
            "· Redis — recall metrics for 10 attack types, FP rate 3%, scenario diversity\n" +
            "· Neo4j — 20 Account nodes, 30 SENT_TO edges, 3 FraudRing clusters\n" +
            "· PostgreSQL — 30-day Immunity Score history trend"
          }
          buttonLabel="Generate demo data"
          buttonColor="var(--primary)"
          onRun={seed.run}
          status={seed.status}
          result={seed.result}
        />
      </div>
    </main>
  );
}

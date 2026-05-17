interface DagRun {
  id: string;
  label: string;
  description: string;
  schedule: string;
  status: "success" | "running" | "failed" | "pending";
  lastRunLabel: string;
  scenariosThisWeek: number | null;
}

const DAG_RUNS: DagRun[] = [
  {
    id: "attack_orchestrator",
    label: "Attack Orchestrator",
    description:
      "Full red-team cycle: generate → inject → detect → evaluate. Enforces Hard Rule #6.",
    schedule: "Hourly",
    status: "success",
    lastRunLabel: "Today 02:00 UTC",
    scenariosThisWeek: 14,
  },
  {
    id: "scenario_coverage_dag",
    label: "Scenario Coverage",
    description:
      "Computes per-attack-type recall and writes metrics to Redis for the Immunity Score.",
    schedule: "Daily 00:30 UTC",
    status: "success",
    lastRunLabel: "Today 00:31 UTC",
    scenariosThisWeek: null,
  },
  {
    id: "community_detection_dag",
    label: "Fraud Ring Detection",
    description:
      "Louvain community detection on the SENT_TO graph. High-risk rings published to Kafka.",
    schedule: "Daily 02:00 UTC",
    status: "success",
    lastRunLabel: "Today 02:03 UTC",
    scenariosThisWeek: null,
  },
  {
    id: "profile_refresh_dag",
    label: "Profile Refresh",
    description:
      "Rebuilds stale Pinecone behavioral profiles and injects new synthetic scenarios.",
    schedule: "Daily 01:00 UTC",
    status: "success",
    lastRunLabel: "Today 01:02 UTC",
    scenariosThisWeek: null,
  },
];

const STATUS_STYLE: Record<
  DagRun["status"],
  { bg: string; text: string; dot: string; label: string }
> = {
  success: {
    bg: "#E0F7EF",
    text: "#0D5C3A",
    dot: "#27B97C",
    label: "Success",
  },
  running: {
    bg: "#E0EAF4",
    text: "#001F4D",
    dot: "#003366",
    label: "Running",
  },
  failed: {
    bg: "#FDEAEA",
    text: "#7A1020",
    dot: "#E03448",
    label: "Failed",
  },
  pending: {
    bg: "#FEF0E6",
    text: "#7A3800",
    dot: "#F07020",
    label: "Pending",
  },
};

export default function RedTeamStatus() {
  return (
    <section
      id="redteam"
      style={{
        padding: "56px 0 0",
      }}
    >
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
            width: 24,
            height: 1,
            flexShrink: 0,
            backgroundColor: "var(--gold)",
          }}
        />
        Red-Team Status
      </div>

      <div
        style={{
          display: "flex",
          justifyContent: "space-between",
          alignItems: "flex-end",
          marginBottom: 28,
          flexWrap: "wrap",
          gap: 12,
        }}
      >
        <div>
          <h2
            style={{
              fontFamily: "'Fraunces', Georgia, serif",
              fontSize: 22,
              fontWeight: 300,
              color: "#0a1628",
              margin: "0 0 4px",
              lineHeight: 1.25,
            }}
          >
            Operational{" "}
            <em style={{ fontStyle: "italic" }}>Overview</em>
          </h2>
          <p
            style={{
              fontFamily: "var(--fb)",
              fontSize: 13,
              color: "var(--mid)",
              margin: 0,
            }}
          >
            Airflow DAG pipeline status · All times UTC
          </p>
        </div>

        {/* Weekly scenarios count */}
        <div
          style={{
            backgroundColor: "var(--white)",
            borderRadius: 10,
            padding: "12px 20px",
            boxShadow: "0 1px 4px rgba(0,51,102,0.08)",
            borderLeft: "3px solid var(--gold)",
            display: "flex",
            alignItems: "center",
            gap: 12,
          }}
        >
          <span
            style={{
              fontFamily: "'Fraunces', Georgia, serif",
              fontSize: 28,
              fontWeight: 300,
              color: "var(--primary)",
              lineHeight: 1,
            }}
          >
            14
          </span>
          <span
            style={{
              fontFamily: "var(--fb)",
              fontSize: 10,
              color: "var(--mid)",
              textTransform: "uppercase",
              letterSpacing: "1px",
            }}
          >
            Scenarios this week
          </span>
        </div>
      </div>

      <div
        style={{
          display: "grid",
          gridTemplateColumns: "repeat(2, 1fr)",
          gap: 16,
        }}
      >
        {DAG_RUNS.map((dag) => {
          const sty = STATUS_STYLE[dag.status];
          return (
            <div
              key={dag.id}
              style={{
                backgroundColor: "var(--white)",
                borderRadius: 12,
                overflow: "hidden",
                boxShadow: "0 1px 4px rgba(0,51,102,0.08)",
              }}
            >
              {/* Accent bar — color by status */}
              <div
                style={{ height: 3, backgroundColor: sty.dot }}
              />

              <div style={{ padding: "20px 24px 24px" }}>
                {/* Header row */}
                <div
                  style={{
                    display: "flex",
                    justifyContent: "space-between",
                    alignItems: "flex-start",
                    marginBottom: 10,
                  }}
                >
                  <div>
                    <div
                      style={{
                        fontFamily: "var(--fb)",
                        fontSize: 14,
                        fontWeight: 600,
                        color: "var(--dark)",
                        marginBottom: 2,
                      }}
                    >
                      {dag.label}
                    </div>
                    <div
                      style={{
                        fontFamily: "var(--fb)",
                        fontSize: 9,
                        letterSpacing: "2px",
                        textTransform: "uppercase",
                        color: "var(--mid)",
                      }}
                    >
                      {dag.schedule}
                    </div>
                  </div>

                  <span
                    style={{
                      display: "inline-flex",
                      alignItems: "center",
                      gap: 6,
                      backgroundColor: sty.bg,
                      color: sty.text,
                      borderRadius: 20,
                      padding: "4px 12px",
                      fontSize: 10,
                      fontFamily: "var(--fb)",
                      fontWeight: 500,
                      flexShrink: 0,
                    }}
                  >
                    <span
                      style={{
                        width: 6,
                        height: 6,
                        borderRadius: "50%",
                        backgroundColor: sty.dot,
                        flexShrink: 0,
                      }}
                    />
                    {sty.label}
                  </span>
                </div>

                <p
                  style={{
                    fontFamily: "var(--fb)",
                    fontSize: 12,
                    color: "#475569",
                    lineHeight: 1.65,
                    margin: "0 0 16px",
                  }}
                >
                  {dag.description}
                </p>

                {/* Footer */}
                <div
                  style={{
                    display: "flex",
                    justifyContent: "space-between",
                    alignItems: "center",
                    paddingTop: 12,
                    borderTop: "1px solid var(--primary-10)",
                  }}
                >
                  <span
                    style={{
                      fontFamily: "var(--fb)",
                      fontSize: 11,
                      color: "var(--mid)",
                    }}
                  >
                    Last run: {dag.lastRunLabel}
                  </span>
                  {dag.scenariosThisWeek !== null && (
                    <span
                      style={{
                        fontFamily: "var(--fb)",
                        fontSize: 11,
                        color: "var(--primary)",
                        backgroundColor: "var(--primary-10)",
                        borderRadius: 6,
                        padding: "3px 10px",
                        fontWeight: 500,
                      }}
                    >
                      {dag.scenariosThisWeek} scenarios this week
                    </span>
                  )}
                </div>
              </div>
            </div>
          );
        })}
      </div>

      {/* Callout note — Kill-switch status */}
      <div
        style={{
          marginTop: 20,
          backgroundColor: "var(--white)",
          borderRadius: 10,
          padding: "14px 20px",
          boxShadow: "0 1px 3px rgba(0,51,102,0.07)",
          borderLeft: "3px solid var(--gold)",
          display: "flex",
          alignItems: "center",
          gap: 16,
        }}
      >
        <div>
          <div
            style={{
              fontFamily: "var(--fb)",
              fontSize: 9,
              fontWeight: 700,
              letterSpacing: "1.5px",
              textTransform: "uppercase",
              color: "var(--gold)",
              marginBottom: 4,
            }}
          >
            Hard Rule #5 — Kill-switch
          </div>
          <div
            style={{
              fontFamily: "var(--fb)",
              fontSize: 12,
              color: "#475569",
              lineHeight: 1.6,
            }}
          >
            <code
              style={{
                fontFamily: "Courier New, monospace",
                backgroundColor: "var(--primary-10)",
                padding: "1px 5px",
                borderRadius: 3,
                fontSize: 11,
              }}
            >
              RED_TEAM_ENABLED=true
            </code>{" "}
            · All attacker agent DAGs active. Set to{" "}
            <code
              style={{
                fontFamily: "Courier New, monospace",
                backgroundColor: "#FDEAEA",
                padding: "1px 5px",
                borderRadius: 3,
                fontSize: 11,
              }}
            >
              false
            </code>{" "}
            to immediately halt all synthetic fraud generation.
          </div>
        </div>
      </div>
    </section>
  );
}

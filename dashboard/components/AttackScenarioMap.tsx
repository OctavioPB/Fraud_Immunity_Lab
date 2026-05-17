import type { CSSProperties } from "react";
import type {
  ScenarioCoverageResponse,
  AttackTypeCoverage,
} from "@/lib/api";

interface Props {
  coverage: ScenarioCoverageResponse | null;
}

const ATTACK_TYPE_LABELS: Record<string, string> = {
  phishing: "Phishing",
  money_laundering: "Money Laundering",
  account_takeover: "Account Takeover",
  credential_stuffing: "Credential Stuffing",
  smurfing: "Smurfing",
  card_fraud: "Card Fraud",
  synthetic_identity: "Synthetic Identity",
  first_party_fraud: "First-Party Fraud",
  mule_account: "Mule Account",
  friendly_fraud: "Friendly Fraud",
};

function Rule6Badge({
  passed,
}: {
  passed: boolean | null | undefined;
}) {
  if (passed === null || passed === undefined) {
    return (
      <span
        style={{
          display: "inline-flex",
          alignItems: "center",
          gap: 6,
          backgroundColor: "#f1f5f9",
          color: "#94a3b8",
          borderRadius: 20,
          padding: "3px 10px",
          fontSize: 10,
          fontFamily: "var(--fb)",
          fontWeight: 500,
        }}
      >
        Not evaluated
      </span>
    );
  }
  return (
    <span
      style={{
        display: "inline-flex",
        alignItems: "center",
        gap: 6,
        backgroundColor: passed ? "#E0F7EF" : "#FDEAEA",
        color: passed ? "#0D5C3A" : "#7A1020",
        borderRadius: 20,
        padding: "3px 10px",
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
          backgroundColor: passed ? "#27B97C" : "#E03448",
          flexShrink: 0,
        }}
      />
      {passed ? "Pass" : "Fail"}
    </span>
  );
}

function RecallBar({ recall }: { recall: number | null | undefined }) {
  if (recall === null || recall === undefined) {
    return (
      <span style={{ color: "#94a3b8", fontFamily: "var(--fb)", fontSize: 12 }}>
        —
      </span>
    );
  }
  const pct = Math.round(recall * 100);
  const color =
    pct >= 90 ? "#27B97C" : pct >= 70 ? "#F07020" : "#E03448";
  return (
    <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
      <div
        style={{
          width: 80,
          height: 6,
          backgroundColor: "var(--light)",
          borderRadius: 3,
          overflow: "hidden",
        }}
      >
        <div
          style={{
            width: `${pct}%`,
            height: "100%",
            backgroundColor: color,
            borderRadius: 3,
          }}
        />
      </div>
      <span
        style={{
          fontFamily: "var(--fb)",
          fontSize: 12,
          color,
          fontWeight: 500,
        }}
      >
        {pct}%
      </span>
    </div>
  );
}

function StatusCell({ row }: { row: AttackTypeCoverage }) {
  if (row.scenario_count === 0) {
    return (
      <span
        style={{
          display: "inline-flex",
          alignItems: "center",
          gap: 6,
          backgroundColor: "#FDEAEA",
          color: "#7A1020",
          borderRadius: 20,
          padding: "3px 10px",
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
            backgroundColor: "#E03448",
            flexShrink: 0,
          }}
        />
        Gap
      </span>
    );
  }
  if (row.recommended) {
    return (
      <span
        style={{
          display: "inline-flex",
          alignItems: "center",
          gap: 6,
          backgroundColor: "#FEF0E6",
          color: "#7A3800",
          borderRadius: 20,
          padding: "3px 10px",
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
            backgroundColor: "#F07020",
            flexShrink: 0,
          }}
        />
        Needs run
      </span>
    );
  }
  return (
    <span
      style={{
        display: "inline-flex",
        alignItems: "center",
        gap: 6,
        backgroundColor: "#E0F7EF",
        color: "#0D5C3A",
        borderRadius: 20,
        padding: "3px 10px",
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
          backgroundColor: "#27B97C",
          flexShrink: 0,
        }}
      />
      Covered
    </span>
  );
}

export default function AttackScenarioMap({ coverage }: Props) {
  const covFraction = coverage
    ? Math.round(coverage.coverage_fraction * 100)
    : null;

  return (
    <section
      id="scenarios"
      style={{
        borderBottom: "1px solid var(--primary-10)",
        padding: "56px 0",
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
        Scenario Coverage
      </div>

      <div
        style={{
          display: "flex",
          justifyContent: "space-between",
          alignItems: "flex-start",
          marginBottom: 28,
          flexWrap: "wrap",
          gap: 16,
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
            Attack{" "}
            <em style={{ fontStyle: "italic" }}>Scenario</em> Map
          </h2>
          <p
            style={{
              fontFamily: "var(--fb)",
              fontSize: 13,
              color: "var(--mid)",
              margin: 0,
            }}
          >
            {coverage
              ? `${coverage.tested_count} tested · ${coverage.untested_count} gaps · ${coverage.window_days}-day window`
              : "Loading coverage data…"}
          </p>
        </div>

        {covFraction !== null && (
          <div
            style={{
              display: "flex",
              alignItems: "center",
              gap: 12,
              backgroundColor: "var(--white)",
              borderRadius: 10,
              padding: "12px 20px",
              boxShadow: "0 1px 4px rgba(0,51,102,0.08)",
              borderLeft: "3px solid var(--gold)",
            }}
          >
            <span
              style={{
                fontFamily: "'Fraunces', Georgia, serif",
                fontSize: 28,
                fontWeight: 300,
                color:
                  covFraction >= 80
                    ? "#27B97C"
                    : covFraction >= 50
                    ? "#F07020"
                    : "#E03448",
                lineHeight: 1,
              }}
            >
              {covFraction}%
            </span>
            <span
              style={{
                fontFamily: "var(--fb)",
                fontSize: 10,
                color: "var(--mid)",
                letterSpacing: "1px",
                textTransform: "uppercase",
              }}
            >
              Coverage
            </span>
          </div>
        )}
      </div>

      {/* Table */}
      <div
        style={{
          backgroundColor: "var(--white)",
          borderRadius: 12,
          overflow: "hidden",
          boxShadow: "0 1px 4px rgba(0,51,102,0.08)",
        }}
      >
        <table
          style={{
            width: "100%",
            borderCollapse: "collapse",
          }}
          aria-label="Attack scenario coverage table"
        >
          <thead>
            <tr
              style={{
                backgroundColor: "var(--primary)",
              }}
            >
              {[
                "Attack Type",
                "Scenarios (30d)",
                "Recall",
                "Hard Rule #6",
                "Status",
                "Last Run",
              ].map((h) => (
                <th
                  key={h}
                  style={{
                    padding: "12px 16px",
                    textAlign: "left",
                    fontFamily: "var(--fb)",
                    fontSize: 10,
                    fontWeight: 500,
                    letterSpacing: "2px",
                    textTransform: "uppercase",
                    color: "var(--white)",
                    whiteSpace: "nowrap",
                  }}
                >
                  {h}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {coverage ? (
              coverage.attack_types.map((row, i) => (
                <tr
                  key={row.attack_type}
                  style={{
                    backgroundColor:
                      i % 2 === 0 ? "var(--white)" : "var(--primary-10)",
                    borderBottom: "1px solid var(--primary-10)",
                  }}
                >
                  <td style={cellStyle}>
                    <span
                      style={{
                        fontFamily: "var(--fb)",
                        fontSize: 13,
                        fontWeight: 500,
                        color: "var(--dark)",
                      }}
                    >
                      {ATTACK_TYPE_LABELS[row.attack_type] ?? row.attack_type}
                    </span>
                    {row.scenario_count === 0 && (
                      <span
                        style={{
                          marginLeft: 8,
                          fontSize: 9,
                          color: "#E03448",
                          fontFamily: "var(--fb)",
                          letterSpacing: "1px",
                          textTransform: "uppercase",
                        }}
                      >
                        ▲ Gap
                      </span>
                    )}
                  </td>
                  <td style={cellStyle}>
                    <span
                      style={{
                        fontFamily: "var(--fb)",
                        fontSize: 13,
                        color:
                          row.scenario_count === 0
                            ? "#E03448"
                            : "var(--dark)",
                        fontWeight: row.scenario_count === 0 ? 600 : 400,
                      }}
                    >
                      {row.scenario_count}
                    </span>
                  </td>
                  <td style={cellStyle}>
                    <RecallBar recall={row.detection_recall} />
                  </td>
                  <td style={cellStyle}>
                    <Rule6Badge passed={row.hard_rule_6_passed} />
                  </td>
                  <td style={cellStyle}>
                    <StatusCell row={row} />
                  </td>
                  <td style={cellStyle}>
                    <span
                      style={{
                        fontFamily: "var(--fb)",
                        fontSize: 12,
                        color: "var(--mid)",
                      }}
                    >
                      {row.last_tested_ms
                        ? new Date(row.last_tested_ms).toLocaleDateString(
                            "en-US",
                            { month: "short", day: "numeric" }
                          )
                        : "Never"}
                    </span>
                  </td>
                </tr>
              ))
            ) : (
              <tr>
                <td
                  colSpan={6}
                  style={{
                    ...cellStyle,
                    textAlign: "center",
                    color: "var(--mid)",
                    padding: "40px 16px",
                  }}
                >
                  Coverage data unavailable — check backend connectivity.
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>
    </section>
  );
}

const cellStyle: CSSProperties = {
  padding: "12px 16px",
  fontFamily: "var(--fb)",
  fontSize: 13,
  color: "var(--dark)",
  verticalAlign: "middle",
};

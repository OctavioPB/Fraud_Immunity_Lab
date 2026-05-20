import type { ScoreComponents } from "@/lib/api";

interface Props {
  components: ScoreComponents | null | undefined;
}

interface CardDef {
  key: keyof ScoreComponents;
  label: string;
  description: string;
  weight: string;
}

const CARDS: CardDef[] = [
  {
    key: "detection_coverage",
    label: "Detection Coverage",
    description:
      "Fraction of canonical attack types with ≥90% recall in the last 30 days.",
    weight: "40%",
  },
  {
    key: "false_positive_health",
    label: "FP Health",
    description:
      "1 − false-positive rate on legitimate transactions evaluated this cycle.",
    weight: "30%",
  },
  {
    key: "model_freshness",
    label: "Model Freshness",
    description:
      "Share of behavioral profiles updated within the staleness window.",
    weight: "20%",
  },
  {
    key: "scenario_diversity",
    label: "Scenario Diversity",
    description:
      "Fraction of canonical attack types exercised by the red-team in the last 30 days.",
    weight: "10%",
  },
];

function scoreColor(pct: number): string {
  if (pct >= 90) return "#27B97C";
  if (pct >= 70) return "#F07020";
  return "#E03448";
}

function scoreBg(pct: number): string {
  if (pct >= 90) return "#E0F7EF";
  if (pct >= 70) return "#FEF0E6";
  return "#FDEAEA";
}

function scoreText(pct: number): string {
  if (pct >= 90) return "#0D5C3A";
  if (pct >= 70) return "#7A3800";
  return "#7A1020";
}

function statusLabel(pct: number): string {
  if (pct >= 90) return "Healthy";
  if (pct >= 70) return "Warning";
  return "Critical";
}

export default function ComponentBreakdown({ components }: Props) {
  return (
    <section
      id="components"
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
        Component Breakdown
      </div>

      <h2
        style={{
          fontFamily: "'Fraunces', Georgia, serif",
          fontSize: 22,
          fontWeight: 300,
          color: "var(--dark)",
          margin: "0 0 4px",
          lineHeight: 1.25,
        }}
      >
        Score{" "}
        <em style={{ fontStyle: "italic" }}>Components</em>
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
        Four weighted sub-scores that compose the Immunity Score formula.
      </p>

      {/* 4-column grid */}
      <div
        style={{
          display: "grid",
          gridTemplateColumns: "repeat(4, 1fr)",
          gap: 16,
        }}
      >
        {CARDS.map(({ key, label, description, weight }) => {
          const value = components?.[key] ?? null;
          const pct = value !== null ? Math.round(value * 100) : null;
          const color = pct !== null ? scoreColor(pct) : "var(--mid)";

          return (
            <div
              key={key}
              style={{
                backgroundColor: "var(--white)",
                borderRadius: 12,
                overflow: "hidden",
                boxShadow: "0 1px 4px rgba(0,51,102,0.08)",
                display: "flex",
                flexDirection: "column",
              }}
            >
              {/* Gold accent bar */}
              <div style={{ height: 3, backgroundColor: "var(--gold)" }} />

              <div
                style={{
                  padding: "24px 24px 28px",
                  display: "flex",
                  flexDirection: "column",
                  flex: 1,
                }}
              >
                {/* Value */}
                <div
                  style={{
                    fontFamily: "'Fraunces', Georgia, serif",
                    fontSize: 32,
                    fontWeight: 300,
                    color: pct !== null ? color : "var(--mid)",
                    lineHeight: 1,
                    marginBottom: 4,
                  }}
                >
                  {pct !== null ? `${pct}%` : "—"}
                </div>

                {/* Label */}
                <div
                  style={{
                    fontFamily: "var(--fb)",
                    fontSize: 10,
                    fontWeight: 500,
                    letterSpacing: "2px",
                    textTransform: "uppercase",
                    color: "var(--mid)",
                    marginBottom: 12,
                  }}
                >
                  {label}
                </div>

                {/* Progress bar */}
                <div
                  style={{
                    height: 6,
                    backgroundColor: "var(--light)",
                    borderRadius: 3,
                    overflow: "hidden",
                    marginBottom: 12,
                  }}
                >
                  {pct !== null && (
                    <div
                      style={{
                        width: `${pct}%`,
                        height: "100%",
                        backgroundColor: color,
                        borderRadius: 3,
                        transition: "width 0.4s ease",
                      }}
                    />
                  )}
                </div>

                {/* Description */}
                <p
                  style={{
                    fontFamily: "var(--fb)",
                    fontSize: 12,
                    color: "#475569",
                    lineHeight: 1.65,
                    margin: "0 0 auto",
                    flex: 1,
                  }}
                >
                  {description}
                </p>

                {/* Footer row */}
                <div
                  style={{
                    marginTop: 16,
                    display: "flex",
                    justifyContent: "space-between",
                    alignItems: "center",
                  }}
                >
                  {/* Status badge */}
                  {pct !== null && (
                    <span
                      style={{
                        display: "inline-flex",
                        alignItems: "center",
                        gap: 6,
                        backgroundColor: scoreBg(pct),
                        color: scoreText(pct),
                        borderRadius: 20,
                        padding: "4px 10px",
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
                          backgroundColor: scoreColor(pct),
                          flexShrink: 0,
                        }}
                      />
                      {statusLabel(pct)}
                    </span>
                  )}

                  {/* Weight tag */}
                  <span
                    style={{
                      fontFamily: "var(--fb)",
                      fontSize: 9,
                      letterSpacing: "1.5px",
                      textTransform: "uppercase",
                      color: "var(--primary)",
                      backgroundColor: "var(--primary-10)",
                      padding: "3px 8px",
                      borderRadius: 4,
                    }}
                  >
                    {weight} weight
                  </span>
                </div>
              </div>
            </div>
          );
        })}
      </div>
    </section>
  );
}

import type {
  ImmunityScoreResponse,
  ScoreHistoryResponse,
} from "@/lib/api";

interface Props {
  score: ImmunityScoreResponse | null;
  history: ScoreHistoryResponse | null;
}

function ScoreColor(score: number): string {
  if (score >= 80) return "#27B97C";
  if (score >= 60) return "#F07020";
  return "#E03448";
}

function Sparkline({ points }: { points: { score: number }[] }) {
  if (points.length < 2)
    return (
      <div
        style={{
          height: 48,
          display: "flex",
          alignItems: "center",
          justifyContent: "center",
          color: "rgba(255,255,255,0.2)",
          fontFamily: "var(--fb)",
          fontSize: 11,
        }}
      >
        Collecting history…
      </div>
    );

  const W = 260;
  const H = 48;
  const scores = points.map((p) => p.score);
  const min = Math.min(...scores);
  const max = Math.max(...scores);
  const range = max - min || 1;

  const pts = scores.map((s, i) => {
    const x = (i / (scores.length - 1)) * W;
    const y = H - ((s - min) / range) * (H - 8) - 4;
    return `${x},${y}`;
  });

  const last = pts[pts.length - 1].split(",");
  const lx = parseFloat(last[0]);
  const ly = parseFloat(last[1]);

  return (
    <svg
      viewBox={`0 0 ${W} ${H}`}
      width={W}
      height={H}
      style={{ display: "block", overflow: "visible" }}
      aria-label={`Score trend over ${points.length} data points`}
    >
      <polyline
        points={pts.join(" ")}
        fill="none"
        stroke="rgba(232,196,106,0.6)"
        strokeWidth="1.5"
        strokeLinejoin="round"
      />
      <circle cx={lx} cy={ly} r="4" fill="var(--gold-light)" />
      <circle
        cx={lx}
        cy={ly}
        r="8"
        fill="rgba(232,196,106,0.2)"
      />
    </svg>
  );
}

function MiniBar({
  label,
  value,
}: {
  label: string;
  value: number;
}) {
  const pct = Math.round(value * 100);
  const barColor =
    pct >= 90 ? "#27B97C" : pct >= 70 ? "#F07020" : "#E03448";

  return (
    <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
      <div
        style={{
          flex: 1,
          height: 4,
          backgroundColor: "rgba(255,255,255,0.1)",
          borderRadius: 2,
          overflow: "hidden",
        }}
      >
        <div
          style={{
            width: `${pct}%`,
            height: "100%",
            backgroundColor: barColor,
            borderRadius: 2,
          }}
        />
      </div>
      <span
        style={{
          fontFamily: "var(--fb)",
          fontSize: 11,
          color: "rgba(255,255,255,0.55)",
          width: 32,
          textAlign: "right",
          flexShrink: 0,
        }}
      >
        {pct}%
      </span>
      <span
        style={{
          fontFamily: "var(--fb)",
          fontSize: 10,
          letterSpacing: "1.5px",
          textTransform: "uppercase",
          color: "rgba(255,255,255,0.35)",
          width: 140,
          flexShrink: 0,
        }}
      >
        {label}
      </span>
    </div>
  );
}

export default function ImmunityScoreHero({ score, history }: Props) {
  const displayScore = score?.score ?? null;
  const components = score?.components;
  const lastUpdated = score
    ? new Date(score.computed_at_ms).toLocaleString("en-US", {
        month: "short",
        day: "numeric",
        hour: "2-digit",
        minute: "2-digit",
      })
    : null;

  return (
    <section
      id="score"
      style={{
        backgroundColor: "var(--primary)",
        backgroundImage: `
          linear-gradient(rgba(255,255,255,.025) 1px, transparent 1px),
          linear-gradient(90deg, rgba(255,255,255,.025) 1px, transparent 1px)
        `,
        backgroundSize: "48px 48px",
        padding: "64px 0 56px",
      }}
      aria-label="Immunity Score overview"
    >
      <div
        style={{
          maxWidth: 1300,
          margin: "0 auto",
          padding: "0 48px",
          display: "grid",
          gridTemplateColumns: "1fr 1fr",
          gap: 64,
          alignItems: "center",
        }}
      >
        {/* Left: score + metadata */}
        <div>
          <h1
            style={{
              fontFamily: "'Fraunces', Georgia, serif",
              fontSize: 42,
              fontWeight: 300,
              color: "var(--white)",
              margin: "0 0 8px",
              lineHeight: 1.15,
            }}
          >
            Fraud{" "}
            <em
              style={{
                fontStyle: "italic",
                color: "var(--gold-light)",
              }}
            >
              Immunity
            </em>{" "}
            Score
          </h1>
          <p
            style={{
              fontFamily: "var(--fb)",
              fontSize: 13,
              color: "rgba(255,255,255,0.45)",
              margin: "0 0 40px",
              lineHeight: 1.6,
            }}
          >
            Composite metric across detection coverage, false-positive health,
            model freshness, and scenario diversity.
          </p>

          {/* Score display */}
          <div
            style={{
              display: "flex",
              alignItems: "baseline",
              gap: 12,
              marginBottom: 8,
            }}
          >
            <span
              style={{
                fontFamily: "'Fraunces', Georgia, serif",
                fontSize: 80,
                fontWeight: 300,
                lineHeight: 1,
                color:
                  displayScore !== null
                    ? ScoreColor(displayScore)
                    : "rgba(255,255,255,0.2)",
              }}
            >
              {displayScore !== null ? Math.round(displayScore) : "—"}
            </span>
            <span
              style={{
                fontFamily: "var(--fb)",
                fontSize: 18,
                color: "rgba(255,255,255,0.4)",
              }}
            >
              / 100
            </span>
          </div>

          {lastUpdated && (
            <p
              style={{
                fontFamily: "var(--fb)",
                fontSize: 11,
                color: "rgba(255,255,255,0.3)",
                margin: "0 0 32px",
                letterSpacing: "1px",
              }}
            >
              {score?.cache_hit ? "Cached · " : ""}
              Updated {lastUpdated}
            </p>
          )}

          {/* Component mini-bars */}
          {components && (
            <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
              <MiniBar
                label="Detection Coverage"
                value={components.detection_coverage}
              />
              <MiniBar
                label="FP Health"
                value={components.false_positive_health}
              />
              <MiniBar
                label="Model Freshness"
                value={components.model_freshness}
              />
              <MiniBar
                label="Scenario Diversity"
                value={components.scenario_diversity}
              />
            </div>
          )}
        </div>

        {/* Right: sparkline */}
        <div>
          <div
            style={{
              display: "inline-flex",
              alignItems: "center",
              gap: 8,
              marginBottom: 16,
              fontSize: 9,
              fontFamily: "var(--fb)",
              fontWeight: 500,
              letterSpacing: "4px",
              textTransform: "uppercase",
              color: "var(--gold-light)",
            }}
          >
            <div
              style={{
                width: 24,
                height: 1,
                flexShrink: 0,
                backgroundColor: "var(--gold-light)",
              }}
            />
            30-Day Trend
          </div>

          <div
            style={{
              backgroundColor: "rgba(255,255,255,0.04)",
              borderRadius: 12,
              padding: "28px 32px",
              border: "1px solid rgba(255,255,255,0.06)",
            }}
          >
            {history ? (
              <>
                <Sparkline points={history.points} />
                <div
                  style={{
                    display: "flex",
                    justifyContent: "space-between",
                    marginTop: 12,
                    fontFamily: "var(--fb)",
                    fontSize: 10,
                    color: "rgba(255,255,255,0.25)",
                    letterSpacing: "1px",
                  }}
                >
                  <span>30 days ago</span>
                  <span>{history.point_count} data points</span>
                  <span>Now</span>
                </div>
              </>
            ) : (
              <div
                style={{
                  height: 80,
                  display: "flex",
                  alignItems: "center",
                  justifyContent: "center",
                  color: "rgba(255,255,255,0.2)",
                  fontFamily: "var(--fb)",
                  fontSize: 12,
                }}
              >
                No history available
              </div>
            )}
          </div>

          {/* Banner stats */}
          {score && (
            <div
              style={{
                display: "grid",
                gridTemplateColumns: "1fr 1fr",
                gap: 20,
                marginTop: 24,
              }}
            >
              {[
                {
                  value: `${Math.round(
                    score.components.detection_coverage * 100
                  )}%`,
                  label: "Attack types at ≥90% recall",
                },
                {
                  value: `${Math.round(
                    score.components.false_positive_health * 100
                  )}%`,
                  label: "Legitimate tx correctly passed",
                },
              ].map(({ value, label }) => (
                <div
                  key={label}
                  style={{
                    borderLeft: "2px solid var(--gold)",
                    paddingLeft: 18,
                  }}
                >
                  <div
                    style={{
                      fontFamily: "'Fraunces', Georgia, serif",
                      fontSize: 28,
                      fontWeight: 300,
                      color: "var(--gold-light)",
                      lineHeight: 1,
                      marginBottom: 6,
                    }}
                  >
                    {value}
                  </div>
                  <div
                    style={{
                      fontFamily: "var(--fb)",
                      fontSize: 11,
                      color: "rgba(255,255,255,0.45)",
                      lineHeight: 1.55,
                    }}
                  >
                    {label}
                  </div>
                </div>
              ))}
            </div>
          )}
        </div>
      </div>
    </section>
  );
}

"use client";

import { useMemo, useState } from "react";
import type { FraudRing } from "@/lib/api";

interface Props {
  rings: FraudRing[];
}

const CANVAS_W = 900;
const CANVAS_H = 420;
const RING_PADDING = 80;

function ringColor(score: number): string {
  if (score >= 0.85) return "#E03448";
  if (score >= 0.70) return "#F07020";
  return "#27B97C";
}

function ringBg(score: number): string {
  if (score >= 0.85) return "#FDEAEA";
  if (score >= 0.70) return "#FEF0E6";
  return "#E0F7EF";
}

function ringText(score: number): string {
  if (score >= 0.85) return "#7A1020";
  if (score >= 0.70) return "#7A3800";
  return "#0D5C3A";
}

interface NodePos {
  id: string;
  x: number;
  y: number;
  ringScore: number;
}

interface EdgePos {
  x1: number;
  y1: number;
  x2: number;
  y2: number;
}

function computeLayout(rings: FraudRing[]): {
  nodes: NodePos[];
  edges: EdgePos[];
  centers: { cx: number; cy: number; ring: FraudRing }[];
} {
  const nodes: NodePos[] = [];
  const edges: EdgePos[] = [];
  const centers: { cx: number; cy: number; ring: FraudRing }[] = [];

  if (rings.length === 0) return { nodes, edges, centers };

  const cols = Math.min(rings.length, 3);
  const rows = Math.ceil(rings.length / cols);
  const cellW = (CANVAS_W - RING_PADDING * 2) / cols;
  const cellH = (CANVAS_H - RING_PADDING * 2) / rows;

  rings.forEach((ring, ri) => {
    const col = ri % cols;
    const row = Math.floor(ri / cols);
    const cx = RING_PADDING + col * cellW + cellW / 2;
    const cy = RING_PADDING + row * cellH + cellH / 2;
    centers.push({ cx, cy, ring });

    const memberCount = ring.member_ids.length;
    const radius = Math.min(
      Math.max(20 + memberCount * 8, 36),
      Math.min(cellW, cellH) / 2 - 16
    );

    const ringNodes: NodePos[] = ring.member_ids.map((id, mi) => {
      const angle = (mi / memberCount) * 2 * Math.PI - Math.PI / 2;
      return {
        id,
        x: cx + radius * Math.cos(angle),
        y: cy + radius * Math.sin(angle),
        ringScore: ring.risk_score,
      };
    });
    nodes.push(...ringNodes);

    // Connect adjacent nodes in the circle
    for (let i = 0; i < ringNodes.length; i++) {
      const a = ringNodes[i];
      const b = ringNodes[(i + 1) % ringNodes.length];
      edges.push({ x1: a.x, y1: a.y, x2: b.x, y2: b.y });
    }

    // Hub edges: connect each node to the center node (first node) for large rings
    if (memberCount > 4) {
      const hub = ringNodes[0];
      for (let i = 2; i < ringNodes.length - 1; i++) {
        const spoke = ringNodes[i];
        edges.push({
          x1: hub.x,
          y1: hub.y,
          x2: spoke.x,
          y2: spoke.y,
        });
      }
    }
  });

  return { nodes, edges, centers };
}

export default function FraudRingVisualizer({ rings }: Props) {
  const [selectedRing, setSelectedRing] = useState<FraudRing | null>(null);
  const { nodes, edges, centers } = useMemo(
    () => computeLayout(rings),
    [rings]
  );

  const SIGNAL_LABELS: Record<string, string> = {
    unidirectional_flow: "Unidirectional Flow",
    shared_ip: "Shared IP",
    shared_device: "Shared Device",
    synthetic_injection: "Synthetic Injection",
  };

  return (
    <section
      id="rings"
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
        Fraud Rings
      </div>

      <div
        style={{
          display: "flex",
          justifyContent: "space-between",
          alignItems: "flex-end",
          marginBottom: 24,
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
              color: "var(--dark)",
              margin: "0 0 4px",
              lineHeight: 1.25,
            }}
          >
            Fraud Ring{" "}
            <em style={{ fontStyle: "italic" }}>Visualizer</em>
          </h2>
          <p
            style={{
              fontFamily: "var(--fb)",
              fontSize: 13,
              color: "var(--mid)",
              margin: 0,
            }}
          >
            Community clusters detected via Louvain algorithm. Click a ring to
            inspect signals.
          </p>
        </div>

        {/* Legend */}
        <div style={{ display: "flex", gap: 16, alignItems: "center" }}>
          {[
            { color: "#E03448", label: "Critical ≥0.85" },
            { color: "#F07020", label: "Warning ≥0.70" },
            { color: "#27B97C", label: "Low <0.70" },
          ].map(({ color, label }) => (
            <div
              key={label}
              style={{ display: "flex", alignItems: "center", gap: 6 }}
            >
              <div
                style={{
                  width: 10,
                  height: 10,
                  borderRadius: "50%",
                  backgroundColor: color,
                  flexShrink: 0,
                }}
              />
              <span
                style={{
                  fontFamily: "var(--fb)",
                  fontSize: 10,
                  color: "var(--mid)",
                }}
              >
                {label}
              </span>
            </div>
          ))}
        </div>
      </div>

      <div
        style={{
          display: "grid",
          gridTemplateColumns: selectedRing ? "1fr 280px" : "1fr",
          gap: 16,
          alignItems: "start",
        }}
      >
        {/* SVG graph */}
        <div
          style={{
            backgroundColor: "var(--white)",
            borderRadius: 14,
            boxShadow: "0 1px 6px rgba(0,51,102,0.09)",
            overflow: "hidden",
          }}
        >
          {/* Gold bar */}
          <div style={{ height: 3, backgroundColor: "var(--gold)" }} />

          {rings.length === 0 ? (
            <div
              style={{
                height: 200,
                display: "flex",
                alignItems: "center",
                justifyContent: "center",
                fontFamily: "var(--fb)",
                fontSize: 13,
                color: "var(--mid)",
              }}
            >
              No fraud rings detected in this period.
            </div>
          ) : (
            <svg
              viewBox={`0 0 ${CANVAS_W} ${CANVAS_H}`}
              width="100%"
              style={{ display: "block" }}
              aria-label={`Fraud ring network: ${rings.length} rings, ${nodes.length} accounts`}
            >
              <style>{`
                @keyframes ring-pulse {
                  0%, 100% { opacity: 1; }
                  50% { opacity: 0.55; }
                }
                .high-risk { animation: ring-pulse 2.4s ease-in-out infinite; }
              `}</style>

              {/* Edges */}
              {edges.map((e, i) => (
                <line
                  key={i}
                  x1={e.x1}
                  y1={e.y1}
                  x2={e.x2}
                  y2={e.y2}
                  stroke="rgba(0,51,102,0.12)"
                  strokeWidth="1"
                />
              ))}

              {/* Ring center labels */}
              {centers.map(({ cx, cy, ring }) => (
                <g
                  key={ring.ring_id}
                  onClick={() =>
                    setSelectedRing(
                      selectedRing?.ring_id === ring.ring_id ? null : ring
                    )
                  }
                  style={{ cursor: "pointer" }}
                  role="button"
                  aria-label={`Ring risk ${Math.round(ring.risk_score * 100)}%`}
                >
                  {/* Click target */}
                  <circle
                    cx={cx}
                    cy={cy}
                    r={40}
                    fill="transparent"
                  />
                  {/* Score label */}
                  <text
                    x={cx}
                    y={cy + 4}
                    textAnchor="middle"
                    fill={ringColor(ring.risk_score)}
                    style={{
                      fontFamily: "'Fraunces', Georgia, serif",
                      fontSize: 13,
                      fontWeight: 300,
                    }}
                  >
                    {Math.round(ring.risk_score * 100)}%
                  </text>
                  {/* Synthetic badge */}
                  {ring.synthetic && (
                    <text
                      x={cx}
                      y={cy + 18}
                      textAnchor="middle"
                      fill="rgba(0,51,102,0.4)"
                      style={{ fontFamily: "var(--fb)", fontSize: 8 }}
                    >
                      synthetic
                    </text>
                  )}
                </g>
              ))}

              {/* Nodes */}
              {nodes.map((n) => {
                const isHigh = n.ringScore >= 0.85;
                return (
                  <circle
                    key={n.id}
                    cx={n.x}
                    cy={n.y}
                    r={5}
                    fill={ringColor(n.ringScore)}
                    stroke="var(--white)"
                    strokeWidth="1.5"
                    className={isHigh ? "high-risk" : undefined}
                    opacity={0.9}
                  />
                );
              })}
            </svg>
          )}
        </div>

        {/* Detail panel */}
        {selectedRing && (
          <div
            style={{
              backgroundColor: "var(--white)",
              borderRadius: 12,
              overflow: "hidden",
              boxShadow: "0 1px 4px rgba(0,51,102,0.08)",
            }}
          >
            <div
              style={{
                height: 3,
                backgroundColor: "var(--gold)",
              }}
            />
            <div style={{ padding: "20px 20px 24px" }}>
              <div
                style={{
                  fontFamily: "var(--fb)",
                  fontSize: 9,
                  letterSpacing: "2px",
                  textTransform: "uppercase",
                  color: "var(--mid)",
                  marginBottom: 6,
                }}
              >
                Ring Detail
              </div>

              <div
                style={{
                  display: "inline-flex",
                  alignItems: "center",
                  gap: 8,
                  backgroundColor: ringBg(selectedRing.risk_score),
                  borderRadius: 8,
                  padding: "10px 14px",
                  marginBottom: 16,
                  width: "100%",
                  boxSizing: "border-box",
                }}
              >
                <span
                  style={{
                    fontFamily: "'Fraunces', Georgia, serif",
                    fontSize: 28,
                    fontWeight: 300,
                    color: ringColor(selectedRing.risk_score),
                    lineHeight: 1,
                  }}
                >
                  {Math.round(selectedRing.risk_score * 100)}%
                </span>
                <span
                  style={{
                    fontFamily: "var(--fb)",
                    fontSize: 10,
                    color: ringText(selectedRing.risk_score),
                    textTransform: "uppercase",
                    letterSpacing: "1px",
                  }}
                >
                  Risk Score
                </span>
              </div>

              <Row label="Members" value={`${selectedRing.member_ids.length} accounts`} />
              <Row
                label="Detected"
                value={new Date(selectedRing.detected_at_ms).toLocaleString(
                  "en-US",
                  { month: "short", day: "numeric", hour: "2-digit", minute: "2-digit" }
                )}
              />
              <Row
                label="Origin"
                value={selectedRing.synthetic ? "Synthetic (red-team)" : "Organic"}
              />

              {selectedRing.signals.length > 0 && (
                <div style={{ marginTop: 16 }}>
                  <div
                    style={{
                      fontFamily: "var(--fb)",
                      fontSize: 9,
                      letterSpacing: "2px",
                      textTransform: "uppercase",
                      color: "var(--mid)",
                      marginBottom: 8,
                    }}
                  >
                    Detection Signals
                  </div>
                  {selectedRing.signals.map((sig) => (
                    <div
                      key={sig}
                      style={{
                        fontFamily: "var(--fb)",
                        fontSize: 11,
                        color: "var(--dark)",
                        backgroundColor: "var(--primary-10)",
                        borderRadius: 6,
                        padding: "5px 10px",
                        marginBottom: 4,
                      }}
                    >
                      {SIGNAL_LABELS[sig] ?? sig}
                    </div>
                  ))}
                </div>
              )}

              <button
                onClick={() => setSelectedRing(null)}
                style={{
                  marginTop: 20,
                  width: "100%",
                  padding: "8px",
                  background: "none",
                  border: "1px solid var(--primary-30)",
                  borderRadius: 6,
                  fontFamily: "var(--fb)",
                  fontSize: 10,
                  letterSpacing: "1.5px",
                  textTransform: "uppercase",
                  color: "var(--primary-60)",
                  cursor: "pointer",
                }}
              >
                Close
              </button>
            </div>
          </div>
        )}
      </div>

      {/* Ring summary row */}
      {rings.length > 0 && (
        <div
          style={{
            display: "flex",
            gap: 12,
            marginTop: 20,
            flexWrap: "wrap",
          }}
        >
          {rings.map((ring) => (
            <button
              key={ring.ring_id}
              onClick={() =>
                setSelectedRing(
                  selectedRing?.ring_id === ring.ring_id ? null : ring
                )
              }
              style={{
                display: "flex",
                alignItems: "center",
                gap: 8,
                backgroundColor:
                  selectedRing?.ring_id === ring.ring_id
                    ? "var(--primary-10)"
                    : "var(--white)",
                border: `1px solid ${
                  selectedRing?.ring_id === ring.ring_id
                    ? "var(--primary-30)"
                    : "var(--primary-10)"
                }`,
                borderRadius: 8,
                padding: "8px 14px",
                cursor: "pointer",
                fontFamily: "var(--fb)",
                fontSize: 11,
                color: "var(--dark)",
                transition: "all 0.15s",
              }}
            >
              <span
                style={{
                  width: 8,
                  height: 8,
                  borderRadius: "50%",
                  backgroundColor: ringColor(ring.risk_score),
                  flexShrink: 0,
                }}
              />
              {ring.member_ids.length} accounts ·{" "}
              {Math.round(ring.risk_score * 100)}% risk
            </button>
          ))}
        </div>
      )}
    </section>
  );
}

function Row({ label, value }: { label: string; value: string }) {
  return (
    <div
      style={{
        display: "flex",
        justifyContent: "space-between",
        gap: 8,
        padding: "6px 0",
        borderBottom: "1px solid var(--primary-10)",
      }}
    >
      <span
        style={{
          fontFamily: "var(--fb)",
          fontSize: 11,
          color: "var(--mid)",
          flexShrink: 0,
        }}
      >
        {label}
      </span>
      <span
        style={{
          fontFamily: "var(--fb)",
          fontSize: 11,
          color: "var(--dark)",
          textAlign: "right",
        }}
      >
        {value}
      </span>
    </div>
  );
}

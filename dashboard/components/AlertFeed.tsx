"use client";

import { useEffect, useRef, useState } from "react";
import { alertsWsUrl } from "@/lib/api";
import { getTenantId } from "@/lib/auth";
import type { AlertEvent } from "@/lib/api";

const MAX_ALERTS = 50;

const SEVERITY_STYLE: Record<
  string,
  { bg: string; text: string; dot: string; label: string }
> = {
  high: {
    bg: "#FDEAEA",
    text: "#7A1020",
    dot: "#E03448",
    label: "High",
  },
  medium: {
    bg: "#FEF0E6",
    text: "#7A3800",
    dot: "#F07020",
    label: "Medium",
  },
  low: {
    bg: "#E0F7EF",
    text: "#0D5C3A",
    dot: "#27B97C",
    label: "Low",
  },
};

const ATTACK_LABELS: Record<string, string> = {
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

function ConnectionBadge({ status }: { status: "connecting" | "connected" | "disconnected" }) {
  const styles = {
    connecting: { bg: "#FEF0E6", text: "#7A3800", dot: "#F07020", label: "Connecting…" },
    connected: { bg: "#E0F7EF", text: "#0D5C3A", dot: "#27B97C", label: "Live" },
    disconnected: { bg: "#FDEAEA", text: "#7A1020", dot: "#E03448", label: "Disconnected" },
  }[status];

  return (
    <span
      style={{
        display: "inline-flex",
        alignItems: "center",
        gap: 6,
        backgroundColor: styles.bg,
        color: styles.text,
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
          backgroundColor: styles.dot,
          flexShrink: 0,
          ...(status === "connected"
            ? { boxShadow: `0 0 0 2px rgba(39,185,124,0.3)` }
            : {}),
        }}
      />
      {styles.label}
    </span>
  );
}

export default function AlertFeed({ tenantId }: { tenantId: string }) {
  const [alerts, setAlerts] = useState<AlertEvent[]>([]);
  const [wsStatus, setWsStatus] = useState<
    "connecting" | "connected" | "disconnected"
  >("connecting");
  const wsRef = useRef<WebSocket | null>(null);
  const scrollRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    // Prefer cookie-based tenantId to ensure client value is current
    const tid = getTenantId() || tenantId;
    const url = alertsWsUrl(tid);
    let ws: WebSocket;
    let reconnectTimer: ReturnType<typeof setTimeout>;

    function connect() {
      setWsStatus("connecting");
      ws = new WebSocket(url);
      wsRef.current = ws;

      ws.onopen = () => setWsStatus("connected");

      ws.onmessage = (ev) => {
        try {
          const alert = JSON.parse(ev.data as string) as AlertEvent;
          setAlerts((prev) => {
            const next = [alert, ...prev];
            return next.slice(0, MAX_ALERTS);
          });
        } catch {
          // ignore malformed frames
        }
      };

      ws.onclose = () => {
        setWsStatus("disconnected");
        // Reconnect after 5 s
        reconnectTimer = setTimeout(connect, 5000);
      };

      ws.onerror = () => {
        ws.close();
      };
    }

    connect();

    return () => {
      clearTimeout(reconnectTimer);
      ws?.close();
    };
  }, [tenantId]);

  // Scroll to top when new alert arrives
  useEffect(() => {
    if (scrollRef.current) {
      scrollRef.current.scrollTop = 0;
    }
  }, [alerts.length]);

  return (
    <section
      id="alerts"
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
        Alert Feed
      </div>

      <div
        style={{
          display: "flex",
          justifyContent: "space-between",
          alignItems: "flex-start",
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
            Real-Time{" "}
            <em style={{ fontStyle: "italic" }}>Detections</em>
          </h2>
          <p
            style={{
              fontFamily: "var(--fb)",
              fontSize: 13,
              color: "var(--mid)",
              margin: 0,
            }}
          >
            WebSocket stream · {alerts.length} events received
          </p>
        </div>

        <div style={{ display: "flex", alignItems: "center", gap: 12 }}>
          <ConnectionBadge status={wsStatus} />
          {alerts.length > 0 && (
            <button
              onClick={() => setAlerts([])}
              style={{
                background: "none",
                border: "1px solid var(--primary-10)",
                borderRadius: 6,
                padding: "5px 12px",
                fontFamily: "var(--fb)",
                fontSize: 10,
                letterSpacing: "1.5px",
                textTransform: "uppercase",
                color: "var(--mid)",
                cursor: "pointer",
              }}
            >
              Clear
            </button>
          )}
        </div>
      </div>

      <div
        style={{
          backgroundColor: "var(--white)",
          borderRadius: 12,
          overflow: "hidden",
          boxShadow: "0 1px 4px rgba(0,51,102,0.08)",
        }}
      >
        <div style={{ height: 3, backgroundColor: "var(--gold)" }} />

        {alerts.length === 0 ? (
          <div
            style={{
              padding: "48px 24px",
              textAlign: "center",
              fontFamily: "var(--fb)",
              fontSize: 13,
              color: "var(--mid)",
            }}
          >
            {wsStatus === "connecting"
              ? "Connecting to alert stream…"
              : wsStatus === "disconnected"
              ? "WebSocket disconnected — retrying in 5 s"
              : "Waiting for detection events…"}
          </div>
        ) : (
          <div
            ref={scrollRef}
            style={{
              maxHeight: 420,
              overflowY: "auto",
            }}
          >
            {alerts.map((alert) => {
              const sev = SEVERITY_STYLE[alert.severity] ?? SEVERITY_STYLE.low;
              return (
                <div
                  key={alert.alert_id}
                  style={{
                    display: "flex",
                    alignItems: "center",
                    gap: 16,
                    padding: "12px 20px",
                    borderBottom: "1px solid var(--primary-10)",
                  }}
                >
                  {/* Severity badge */}
                  <span
                    style={{
                      display: "inline-flex",
                      alignItems: "center",
                      gap: 5,
                      backgroundColor: sev.bg,
                      color: sev.text,
                      borderRadius: 20,
                      padding: "3px 10px",
                      fontSize: 10,
                      fontFamily: "var(--fb)",
                      fontWeight: 500,
                      flexShrink: 0,
                      minWidth: 70,
                      justifyContent: "center",
                    }}
                  >
                    <span
                      style={{
                        width: 5,
                        height: 5,
                        borderRadius: "50%",
                        backgroundColor: sev.dot,
                        flexShrink: 0,
                      }}
                    />
                    {sev.label}
                  </span>

                  {/* Attack type */}
                  <span
                    style={{
                      fontFamily: "var(--fb)",
                      fontSize: 13,
                      fontWeight: 500,
                      color: "var(--dark)",
                      width: 160,
                      flexShrink: 0,
                    }}
                  >
                    {ATTACK_LABELS[alert.attack_type] ?? alert.attack_type}
                  </span>

                  {/* Risk score bar */}
                  <div
                    style={{
                      flex: 1,
                      display: "flex",
                      alignItems: "center",
                      gap: 8,
                    }}
                  >
                    <div
                      style={{
                        flex: 1,
                        height: 4,
                        backgroundColor: "var(--light)",
                        borderRadius: 2,
                        overflow: "hidden",
                        maxWidth: 120,
                      }}
                    >
                      <div
                        style={{
                          width: `${Math.round(alert.risk_score * 100)}%`,
                          height: "100%",
                          backgroundColor: sev.dot,
                          borderRadius: 2,
                        }}
                      />
                    </div>
                    <span
                      style={{
                        fontFamily: "var(--fb)",
                        fontSize: 11,
                        color: sev.dot,
                        fontWeight: 500,
                        flexShrink: 0,
                      }}
                    >
                      {Math.round(alert.risk_score * 100)}%
                    </span>
                  </div>

                  {/* Account token */}
                  <span
                    style={{
                      fontFamily: "Courier New, monospace",
                      fontSize: 11,
                      color: "var(--mid)",
                      flexShrink: 0,
                    }}
                  >
                    {alert.account_token}
                  </span>

                  {/* Synthetic tag */}
                  {alert.synthetic && (
                    <span
                      style={{
                        fontFamily: "var(--fb)",
                        fontSize: 8,
                        fontWeight: 700,
                        letterSpacing: "1.5px",
                        textTransform: "uppercase",
                        color: "var(--primary)",
                        backgroundColor: "var(--primary-10)",
                        borderRadius: 4,
                        padding: "2px 6px",
                        flexShrink: 0,
                      }}
                    >
                      Synthetic
                    </span>
                  )}

                  {/* Timestamp */}
                  <span
                    style={{
                      fontFamily: "var(--fb)",
                      fontSize: 11,
                      color: "rgba(107,114,128,0.7)",
                      flexShrink: 0,
                      textAlign: "right",
                      minWidth: 60,
                    }}
                  >
                    {new Date(alert.detected_at_ms).toLocaleTimeString(
                      "en-US",
                      { hour: "2-digit", minute: "2-digit", second: "2-digit" }
                    )}
                  </span>
                </div>
              );
            })}
          </div>
        )}
      </div>
    </section>
  );
}

"use client";

import { logout, getTenantId } from "@/lib/auth";
import { useEffect, useState } from "react";

interface NavProps {
  tenantId: string;
}

const NAV_LINKS = [
  { label: "Score", href: "#score" },
  { label: "Scenarios", href: "#scenarios" },
  { label: "Rings", href: "#rings" },
  { label: "Alerts", href: "#alerts" },
  { label: "Red-Team", href: "#redteam" },
];

export default function Nav({ tenantId }: NavProps) {
  const [active, setActive] = useState<string>("#score");
  const [clientTenantId, setClientTenantId] = useState(tenantId);

  useEffect(() => {
    // Sync from cookie in case it differs from the server-rendered value
    setClientTenantId(getTenantId() || tenantId);
  }, [tenantId]);

  function handleNavClick(href: string) {
    setActive(href);
    const el = document.getElementById(href.slice(1));
    el?.scrollIntoView({ behavior: "smooth" });
  }

  return (
    <nav
      style={{
        position: "sticky",
        top: 0,
        zIndex: 100,
        height: 52,
        backgroundColor: "rgba(0,51,102,.97)",
        backdropFilter: "blur(12px)",
        borderBottom: "1px solid rgba(255,255,255,.08)",
        display: "flex",
        alignItems: "center",
        padding: "0 40px",
        gap: 24,
      }}
    >
      {/* OPB Monogram */}
      <div style={{ display: "flex", alignItems: "center", gap: 12, flexShrink: 0 }}>
        <span>
          <span
            style={{
              fontFamily: "'Fraunces', Georgia, serif",
              fontSize: 20,
              fontWeight: 300,
              color: "#ffffff",
            }}
          >
            O
          </span>
          <em
            style={{
              fontFamily: "'Fraunces', Georgia, serif",
              fontSize: 20,
              fontWeight: 300,
              fontStyle: "italic",
              color: "var(--gold-light)",
            }}
          >
            PB
          </em>
        </span>

        {/* App title */}
        <span
          style={{
            fontFamily: "var(--fb)",
            fontSize: 9,
            letterSpacing: "3px",
            textTransform: "uppercase",
            color: "rgba(255,255,255,.4)",
          }}
        >
          Fraud Immunity Lab
        </span>
      </div>

      {/* Spacer */}
      <div style={{ flex: 1 }} />

      {/* Nav links */}
      <div style={{ display: "flex", alignItems: "center", gap: 4 }}>
        {NAV_LINKS.map(({ label, href }) => {
          const isActive = active === href;
          return (
            <button
              key={href}
              onClick={() => handleNavClick(href)}
              style={{
                background: "none",
                border: "none",
                color: isActive
                  ? "var(--gold-light)"
                  : "rgba(255,255,255,0.45)",
                cursor: "pointer",
                fontFamily: "var(--fb)",
                fontSize: 9,
                letterSpacing: "2px",
                textTransform: "uppercase",
                padding: "5px 8px",
                borderRadius: 6,
                transition: "color 0.15s",
                ...(isActive
                  ? { backgroundColor: "rgba(201,168,76,0.12)" }
                  : {}),
              }}
            >
              {label}
            </button>
          );
        })}
      </div>

      {/* Tenant badge + logout */}
      <div style={{ display: "flex", alignItems: "center", gap: 10, flexShrink: 0 }}>
        <span
          style={{
            fontFamily: "var(--fb)",
            fontSize: 9,
            letterSpacing: "2px",
            textTransform: "uppercase",
            color: "rgba(255,255,255,0.35)",
            backgroundColor: "rgba(255,255,255,0.06)",
            padding: "4px 8px",
            borderRadius: 4,
          }}
        >
          {clientTenantId}
        </span>
        <button
          onClick={() => void logout()}
          style={{
            background: "none",
            border: "1px solid rgba(255,255,255,0.2)",
            borderRadius: 6,
            color: "rgba(255,255,255,0.5)",
            cursor: "pointer",
            fontFamily: "var(--fb)",
            fontSize: 9,
            letterSpacing: "2px",
            textTransform: "uppercase",
            padding: "5px 10px",
          }}
        >
          Sign out
        </button>
      </div>
    </nav>
  );
}

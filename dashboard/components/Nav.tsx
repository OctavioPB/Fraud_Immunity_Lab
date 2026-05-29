"use client";

import { logout, getTenantId } from "@/lib/auth";
import { useEffect, useState } from "react";
import { usePathname, useRouter } from "next/navigation";
import type { Route } from "next";

interface NavProps {
  tenantId: string;
}

const SECTION_LINKS = [
  { label: "Score", href: "#score" },
  { label: "Scenarios", href: "#scenarios" },
  { label: "Rings", href: "#rings" },
  { label: "Alerts", href: "#alerts" },
  { label: "Red-Team", href: "#redteam" },
];

const PAGE_LINKS = [
  { label: "Info", href: "/info" },
  { label: "Admin", href: "/admin" },
];

export default function Nav({ tenantId }: NavProps) {
  const [activeHash, setActiveHash] = useState<string>("#score");
  const [clientTenantId, setClientTenantId] = useState(tenantId);
  const pathname = usePathname();
  const router = useRouter();

  useEffect(() => {
    setClientTenantId(getTenantId() || tenantId);
  }, [tenantId]);

  const isInfoPage = pathname !== "/";

  function handleNavClick(href: string) {
    if (href.startsWith("/")) {
      router.push(href as Route);
    } else if (isInfoPage) {
      // Navigate from info page to dashboard section
      window.location.href = "/" + href;
    } else {
      setActiveHash(href);
      document.getElementById(href.slice(1))?.scrollIntoView({ behavior: "smooth" });
    }
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
              color: "var(--white)",
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
        {SECTION_LINKS.map(({ label, href }) => {
          const isActive = !isInfoPage && activeHash === href;
          return (
            <button
              key={href}
              onClick={() => handleNavClick(href)}
              style={{
                background: "none",
                backgroundColor: isActive ? "rgba(201,168,76,0.12)" : "transparent",
                border: "none",
                color: isActive
                  ? "var(--gold-light)"
                  : isInfoPage
                  ? "rgba(255,255,255,0.25)"
                  : "rgba(255,255,255,0.45)",
                cursor: "pointer",
                fontFamily: "var(--fb)",
                fontSize: 9,
                letterSpacing: "2px",
                textTransform: "uppercase",
                padding: "5px 8px",
                borderRadius: 6,
                transition: "color 0.15s, background-color 0.15s",
              }}
            >
              {label}
            </button>
          );
        })}

        {/* Separator */}
        <div style={{ width: 1, height: 16, backgroundColor: "rgba(255,255,255,0.12)", margin: "0 4px" }} />

        {PAGE_LINKS.map(({ label, href }) => {
          const isActive = pathname === href;
          return (
            <button
              key={href}
              onClick={() => handleNavClick(href)}
              style={{
                background: "none",
                backgroundColor: isActive ? "rgba(201,168,76,0.12)" : "transparent",
                border: isActive ? "none" : "1px solid rgba(255,255,255,0.12)",
                color: isActive ? "var(--gold-light)" : "rgba(255,255,255,0.55)",
                cursor: "pointer",
                fontFamily: "var(--fb)",
                fontSize: 9,
                letterSpacing: "2px",
                textTransform: "uppercase",
                padding: "5px 8px",
                borderRadius: 6,
                transition: "color 0.15s, background-color 0.15s",
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

import { cookies } from "next/headers";

import Nav from "@/components/Nav";
import ImmunityScoreHero from "@/components/ImmunityScoreHero";
import ComponentBreakdown from "@/components/ComponentBreakdown";
import AttackScenarioMap from "@/components/AttackScenarioMap";
import FraudRingVisualizer from "@/components/FraudRingVisualizer";
import AlertFeed from "@/components/AlertFeed";
import RedTeamStatus from "@/components/RedTeamStatus";
import NPSWidget from "@/components/NPSWidget";

import {
  fetchImmunityScore,
  fetchScoreHistory,
  fetchScenarioCoverage,
  fetchFraudRings,
  type ImmunityScoreResponse,
  type ScoreHistoryResponse,
  type ScenarioCoverageResponse,
  type FraudRingsResponse,
} from "@/lib/api";

export const dynamic = "force-dynamic";
export const revalidate = 0;

export default async function DashboardPage() {
  const cookieStore = cookies();
  const token = cookieStore.get("access_token")?.value ?? "";
  const tenantId = cookieStore.get("tenant_id")?.value ?? "default";

  const [scoreResult, historyResult, coverageResult, ringsResult] =
    await Promise.allSettled([
      fetchImmunityScore(tenantId, token),
      fetchScoreHistory(30, tenantId, token),
      fetchScenarioCoverage(tenantId, token),
      fetchFraudRings(tenantId, token),
    ]);

  const score: ImmunityScoreResponse | null =
    scoreResult.status === "fulfilled" ? scoreResult.value : null;
  const history: ScoreHistoryResponse | null =
    historyResult.status === "fulfilled" ? historyResult.value : null;
  const coverage: ScenarioCoverageResponse | null =
    coverageResult.status === "fulfilled" ? coverageResult.value : null;
  const ringsData: FraudRingsResponse | null =
    ringsResult.status === "fulfilled" ? ringsResult.value : null;

  const rings = ringsData?.rings ?? [];

  const currentDate = new Date().toLocaleDateString("en-US", {
    year: "numeric",
    month: "long",
  });

  return (
    <div
      style={{
        minHeight: "100vh",
        backgroundColor: "var(--light)",
        display: "flex",
        flexDirection: "column",
      }}
    >
      {/* 1. Sticky navigation */}
      <Nav tenantId={tenantId} />

      {/* 2. Hero — dark blue + grid + score */}
      <ImmunityScoreHero score={score} history={history} />

      {/* 3–7. Main content sections */}
      <main
        style={{
          flex: 1,
          maxWidth: 1300,
          width: "100%",
          margin: "0 auto",
          padding: "0 48px 96px",
          boxSizing: "border-box",
        }}
      >
        {/* 3. Component breakdown — 4 KPI cards */}
        <ComponentBreakdown components={score?.components} />

        {/* 4. Attack scenario map */}
        <AttackScenarioMap coverage={coverage} />

        {/* 5. Fraud ring visualizer */}
        <FraudRingVisualizer rings={rings} />

        {/* 6. Real-time alert feed */}
        <AlertFeed tenantId={tenantId} />

        {/* 7. Red-team DAG status */}
        <RedTeamStatus />
      </main>

      {/* 8. NPS feedback widget — fixed bottom-right, client-side only */}
      <NPSWidget tenantId={tenantId} />

      {/* 9. Footer */}
      <footer
        style={{
          backgroundColor: "var(--primary)",
          padding: "20px 48px",
          display: "flex",
          justifyContent: "space-between",
          alignItems: "center",
          fontFamily: "var(--fb)",
          fontSize: 9,
          letterSpacing: "3px",
          textTransform: "uppercase",
          color: "rgba(255,255,255,0.4)",
        }}
      >
        <span>OPB · Octavio Pérez Bravo · Fraud Immunity Lab</span>
        <span>{currentDate.toUpperCase()}</span>
      </footer>
    </div>
  );
}

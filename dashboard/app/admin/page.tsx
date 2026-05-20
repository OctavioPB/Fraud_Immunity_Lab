import { cookies } from "next/headers";
import Nav from "@/components/Nav";
import AdminPanel from "@/components/AdminPanel";

export const dynamic = "force-dynamic";

export default async function AdminRoute() {
  const cookieStore = await cookies();
  const tenantId = cookieStore.get("tenant_id")?.value ?? "default";

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
      <Nav tenantId={tenantId} />
      <AdminPanel />
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

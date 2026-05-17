export default function HomePage() {
  return (
    <main
      style={{
        minHeight: "100vh",
        display: "flex",
        alignItems: "center",
        justifyContent: "center",
        backgroundColor: "var(--primary)",
        backgroundImage: `
          linear-gradient(rgba(255,255,255,.025) 1px, transparent 1px),
          linear-gradient(90deg, rgba(255,255,255,.025) 1px, transparent 1px)
        `,
        backgroundSize: "48px 48px",
      }}
    >
      <div style={{ textAlign: "center" }}>
        <h1
          style={{
            fontFamily: "var(--fd)",
            fontSize: 48,
            fontWeight: 300,
            color: "var(--white)",
            margin: "0 0 16px",
          }}
        >
          Fraud{" "}
          <em style={{ fontStyle: "italic", color: "var(--gold-light)" }}>
            Immunity
          </em>{" "}
          Lab
        </h1>
        <p
          style={{
            fontFamily: "var(--fb)",
            fontSize: 13,
            letterSpacing: "3px",
            textTransform: "uppercase",
            color: "rgba(255,255,255,0.4)",
            margin: 0,
          }}
        >
          Sprint 1 · Foundation &amp; Infrastructure
        </p>
      </div>
    </main>
  );
}

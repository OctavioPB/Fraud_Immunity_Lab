"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";

export default function LoginPage() {
  const router = useRouter();
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  async function handleSubmit(e: React.FormEvent<HTMLFormElement>) {
    e.preventDefault();
    setLoading(true);
    setError(null);
    const form = e.currentTarget;
    const username = (
      form.elements.namedItem("username") as HTMLInputElement
    ).value;
    const password = (
      form.elements.namedItem("password") as HTMLInputElement
    ).value;
    const tenantId =
      (form.elements.namedItem("tenant_id") as HTMLInputElement).value ||
      "default";

    try {
      const res = await fetch("/api/auth/login", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ username, password, tenant_id: tenantId }),
      });
      const data = (await res.json()) as { error?: string };
      if (!res.ok) {
        setError(data.error ?? "Login failed");
        setLoading(false);
        return;
      }
      router.push("/");
      router.refresh();
    } catch {
      setError("Connection error — is the backend running?");
      setLoading(false);
    }
  }

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
      <div
        style={{
          width: "100%",
          maxWidth: 400,
          padding: "0 24px",
        }}
      >
        {/* Monogram */}
        <div
          style={{
            textAlign: "center",
            marginBottom: 32,
          }}
        >
          <span>
            <span
              style={{
                fontFamily: "'Fraunces', Georgia, serif",
                fontSize: 28,
                fontWeight: 300,
                color: "#ffffff",
              }}
            >
              O
            </span>
            <em
              style={{
                fontFamily: "'Fraunces', Georgia, serif",
                fontSize: 28,
                fontWeight: 300,
                fontStyle: "italic",
                color: "var(--gold-light)",
              }}
            >
              PB
            </em>
          </span>
          <p
            style={{
              fontFamily: "var(--fb)",
              fontSize: 9,
              letterSpacing: "3px",
              textTransform: "uppercase",
              color: "rgba(255,255,255,0.35)",
              margin: "8px 0 0",
            }}
          >
            Fraud Immunity Lab
          </p>
        </div>

        {/* Card */}
        <div
          style={{
            backgroundColor: "var(--white)",
            borderRadius: 12,
            overflow: "hidden",
            boxShadow: "0 8px 32px rgba(0,0,0,0.24)",
          }}
        >
          {/* Gold accent bar */}
          <div
            style={{ height: 3, backgroundColor: "var(--gold)" }}
          />

          <div style={{ padding: "32px 36px 36px" }}>
            <h1
              style={{
                fontFamily: "'Fraunces', Georgia, serif",
                fontSize: 22,
                fontWeight: 300,
                color: "var(--dark)",
                margin: "0 0 4px",
              }}
            >
              Sign{" "}
              <em style={{ fontStyle: "italic", color: "var(--primary)" }}>
                in
              </em>
            </h1>
            <p
              style={{
                fontFamily: "var(--fb)",
                fontSize: 13,
                color: "var(--mid)",
                margin: "0 0 28px",
                lineHeight: 1.5,
              }}
            >
              Access the Immunity Score dashboard
            </p>

            <form onSubmit={handleSubmit}>
              <fieldset
                style={{ border: "none", padding: 0, margin: 0 }}
              >
                <Field label="Username" name="username" type="text" />
                <Field
                  label="Password"
                  name="password"
                  type="password"
                  style={{ marginTop: 16 }}
                />
                <Field
                  label="Tenant ID"
                  name="tenant_id"
                  type="text"
                  placeholder="default"
                  style={{ marginTop: 16 }}
                />
              </fieldset>

              {error && (
                <p
                  style={{
                    fontFamily: "var(--fb)",
                    fontSize: 12,
                    color: "#E03448",
                    backgroundColor: "#FDEAEA",
                    borderRadius: 6,
                    padding: "8px 12px",
                    margin: "16px 0 0",
                  }}
                >
                  {error}
                </p>
              )}

              <button
                type="submit"
                disabled={loading}
                style={{
                  marginTop: 24,
                  width: "100%",
                  padding: "12px",
                  backgroundColor: loading
                    ? "var(--primary-60)"
                    : "var(--primary)",
                  color: "var(--white)",
                  border: "none",
                  borderRadius: 8,
                  fontFamily: "var(--fb)",
                  fontSize: 11,
                  fontWeight: 600,
                  letterSpacing: "2px",
                  textTransform: "uppercase",
                  cursor: loading ? "not-allowed" : "pointer",
                  transition: "background-color 0.15s",
                }}
              >
                {loading ? "Signing in…" : "Sign in →"}
              </button>
            </form>
          </div>
        </div>

        <p
          style={{
            fontFamily: "var(--fb)",
            fontSize: 10,
            color: "rgba(255,255,255,0.25)",
            textAlign: "center",
            marginTop: 20,
            letterSpacing: "1px",
          }}
        >
          Default credentials: admin / fraud-lab-2024
        </p>
      </div>
    </main>
  );
}

function Field({
  label,
  name,
  type,
  placeholder,
  style,
}: {
  label: string;
  name: string;
  type: string;
  placeholder?: string;
  style?: React.CSSProperties;
}) {
  return (
    <div style={style}>
      <label
        htmlFor={name}
        style={{
          display: "block",
          fontFamily: "var(--fb)",
          fontSize: 10,
          fontWeight: 500,
          letterSpacing: "2px",
          textTransform: "uppercase",
          color: "var(--mid)",
          marginBottom: 6,
        }}
      >
        {label}
      </label>
      <input
        id={name}
        name={name}
        type={type}
        placeholder={placeholder}
        required={name !== "tenant_id"}
        style={{
          width: "100%",
          padding: "10px 12px",
          border: "1px solid var(--primary-10)",
          borderRadius: 6,
          fontFamily: "var(--fb)",
          fontSize: 14,
          color: "var(--dark)",
          backgroundColor: "var(--white)",
          outline: "none",
          boxSizing: "border-box",
        }}
      />
    </div>
  );
}

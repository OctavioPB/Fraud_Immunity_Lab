"use client";

import { useState, useCallback } from "react";

const _API = typeof window === "undefined" ? "" : (process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000");

type Stage = "prompt" | "rating" | "comment" | "submitted" | "dismissed";

interface NPSSubmission {
  score: number;
  comment: string;
  tenant_id: string;
  submitted_at_ms: number;
}

export default function NPSWidget({ tenantId }: { tenantId: string }) {
  const [stage, setStage] = useState<Stage>("prompt");
  const [rating, setRating] = useState<number | null>(null);
  const [hovered, setHovered] = useState<number | null>(null);
  const [comment, setComment] = useState("");
  const [submitting, setSubmitting] = useState(false);

  const dismiss = useCallback(() => setStage("dismissed"), []);

  const selectRating = useCallback((n: number) => {
    setRating(n);
    setStage("comment");
  }, []);

  const submit = useCallback(async () => {
    if (rating === null) return;
    setSubmitting(true);
    try {
      const payload: NPSSubmission = {
        score: rating,
        comment: comment.trim(),
        tenant_id: tenantId,
        submitted_at_ms: Date.now(),
      };
      await fetch(`${_API}/feedback/nps`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
        credentials: "include",
      });
    } catch {
      // Best-effort — never block the user on a failed NPS submission
    } finally {
      setSubmitting(false);
      setStage("submitted");
    }
  }, [rating, comment, tenantId]);

  if (stage === "dismissed") return null;

  const ratingLabel =
    rating === null
      ? ""
      : rating >= 9
      ? "Promoter"
      : rating >= 7
      ? "Passive"
      : "Detractor";

  const ratingColor =
    rating === null
      ? "var(--mid)"
      : rating >= 9
      ? "#0D5C3A"
      : rating >= 7
      ? "var(--gold)"
      : "#7A1020";

  return (
    <div
      style={{
        position: "fixed",
        bottom: 28,
        right: 28,
        width: 340,
        backgroundColor: "var(--white)",
        borderRadius: 12,
        boxShadow: "0 8px 32px rgba(0,0,0,0.14), 0 2px 8px rgba(0,0,0,0.08)",
        overflow: "hidden",
        zIndex: 9999,
        fontFamily: "var(--fb)",
      }}
      role="dialog"
      aria-label="Feedback survey"
    >
      {/* Gold accent bar */}
      <div style={{ height: 3, backgroundColor: "var(--gold)" }} />

      <div style={{ padding: "20px 24px 24px" }}>
        {/* Header row */}
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", marginBottom: 14 }}>
          <p
            style={{
              margin: 0,
              fontFamily: "var(--fb)",
              fontSize: 11,
              fontWeight: 500,
              textTransform: "uppercase",
              letterSpacing: "3px",
              color: "var(--gold)",
            }}
          >
            Feedback
          </p>
          <button
            onClick={dismiss}
            aria-label="Dismiss feedback"
            style={{
              background: "none",
              border: "none",
              cursor: "pointer",
              color: "var(--mid)",
              fontSize: 16,
              lineHeight: 1,
              padding: 0,
            }}
          >
            ✕
          </button>
        </div>

        {/* Prompt stage */}
        {stage === "prompt" && (
          <>
            <p
              style={{
                margin: "0 0 16px",
                fontFamily: "var(--fd)",
                fontSize: 18,
                fontWeight: 400,
                color: "var(--primary)",
              }}
            >
              How likely are you to recommend <em>Fraud Immunity Lab</em>?
            </p>
            <button
              onClick={() => setStage("rating")}
              style={{
                width: "100%",
                padding: "10px 0",
                backgroundColor: "var(--primary)",
                color: "var(--white)",
                border: "none",
                borderRadius: 8,
                cursor: "pointer",
                fontFamily: "var(--fb)",
                fontSize: 14,
                fontWeight: 600,
              }}
            >
              Share feedback
            </button>
          </>
        )}

        {/* Rating stage */}
        {stage === "rating" && (
          <>
            <p style={{ margin: "0 0 4px", fontSize: 14, fontWeight: 500, color: "var(--dark)" }}>
              On a scale of 0–10, how likely are you to recommend us?
            </p>
            <p style={{ margin: "0 0 14px", fontSize: 12, color: "var(--mid)" }}>
              0 = Not at all · 10 = Extremely likely
            </p>
            <div style={{ display: "grid", gridTemplateColumns: "repeat(11, 1fr)", gap: 4 }}>
              {Array.from({ length: 11 }, (_, i) => {
                const active = hovered !== null ? i === hovered : i === rating;
                const fill = i >= 9 ? "#27b97c" : i >= 7 ? "#c8982a" : "#e03448";
                return (
                  <button
                    key={i}
                    onClick={() => selectRating(i)}
                    onMouseEnter={() => setHovered(i)}
                    onMouseLeave={() => setHovered(null)}
                    style={{
                      padding: "6px 0",
                      border: active ? `2px solid ${fill}` : "1.5px solid var(--primary-10)",
                      borderRadius: 6,
                      backgroundColor: active ? fill : "transparent",
                      color: active ? "var(--white)" : "var(--dark)",
                      cursor: "pointer",
                      fontFamily: "var(--fb)",
                      fontSize: 12,
                      fontWeight: 600,
                      transition: "all 0.12s ease",
                    }}
                  >
                    {i}
                  </button>
                );
              })}
            </div>
          </>
        )}

        {/* Comment stage */}
        {stage === "comment" && (
          <>
            <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 14 }}>
              <span
                style={{
                  fontFamily: "var(--fd)",
                  fontSize: 28,
                  fontWeight: 400,
                  color: ratingColor,
                }}
              >
                {rating}
              </span>
              <span
                style={{
                  fontFamily: "var(--fb)",
                  fontSize: 11,
                  fontWeight: 500,
                  textTransform: "uppercase",
                  letterSpacing: "2px",
                  color: ratingColor,
                }}
              >
                {ratingLabel}
              </span>
            </div>
            <p style={{ margin: "0 0 8px", fontSize: 14, color: "var(--dark)", fontWeight: 500 }}>
              {rating! >= 9
                ? "What do you love most about the platform?"
                : rating! >= 7
                ? "What would make this a 10?"
                : "What's the biggest issue you're facing?"}
            </p>
            <textarea
              value={comment}
              onChange={(e) => setComment(e.target.value)}
              placeholder="Optional — share your thoughts"
              maxLength={500}
              rows={3}
              style={{
                width: "100%",
                padding: "10px 12px",
                borderRadius: 8,
                border: "1.5px solid var(--primary-10)",
                fontFamily: "var(--fb)",
                fontSize: 13,
                color: "var(--dark)",
                resize: "vertical",
                boxSizing: "border-box",
                outline: "none",
              }}
            />
            <div style={{ display: "flex", gap: 8, marginTop: 12 }}>
              <button
                onClick={() => setStage("rating")}
                style={{
                  flex: 1,
                  padding: "9px 0",
                  border: "1.5px solid var(--primary-10)",
                  borderRadius: 8,
                  background: "transparent",
                  cursor: "pointer",
                  fontFamily: "var(--fb)",
                  fontSize: 13,
                  color: "var(--mid)",
                }}
              >
                Back
              </button>
              <button
                onClick={submit}
                disabled={submitting}
                style={{
                  flex: 2,
                  padding: "9px 0",
                  border: "none",
                  borderRadius: 8,
                  backgroundColor: submitting ? "var(--primary-60)" : "var(--primary)",
                  color: "var(--white)",
                  cursor: submitting ? "not-allowed" : "pointer",
                  fontFamily: "var(--fb)",
                  fontSize: 13,
                  fontWeight: 600,
                }}
              >
                {submitting ? "Sending…" : "Submit feedback"}
              </button>
            </div>
          </>
        )}

        {/* Submitted stage */}
        {stage === "submitted" && (
          <div style={{ textAlign: "center", padding: "8px 0" }}>
            <div style={{ fontSize: 28, marginBottom: 8 }}>✓</div>
            <p
              style={{
                margin: "0 0 4px",
                fontFamily: "var(--fd)",
                fontSize: 18,
                fontWeight: 400,
                color: "var(--primary)",
              }}
            >
              Thank you
            </p>
            <p style={{ margin: 0, fontSize: 13, color: "var(--mid)" }}>
              Your feedback helps us improve the platform.
            </p>
          </div>
        )}
      </div>
    </div>
  );
}

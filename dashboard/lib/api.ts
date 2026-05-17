/**
 * Typed API client for the Fraud Immunity Lab FastAPI backend.
 *
 * Server-side calls (RSC): pass `token` from the httpOnly cookie.
 * Client-side calls: omit `token`; the browser sends the cookie automatically
 * (same-origin only; cross-origin requires the Next.js proxy pattern).
 */

// Server-side uses API_URL; client-side uses NEXT_PUBLIC_API_URL.
const SERVER_BASE = process.env.API_URL ?? "http://localhost:8000";
const CLIENT_BASE =
  process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

function base(): string {
  return typeof window === "undefined" ? SERVER_BASE : CLIENT_BASE;
}

function headers(token?: string): HeadersInit {
  const h: Record<string, string> = { "Content-Type": "application/json" };
  if (token) h["Authorization"] = `Bearer ${token}`;
  return h;
}

// ── Domain types ───────────────────────────────────────────────────────────────

export interface ScoreComponents {
  detection_coverage: number;
  false_positive_health: number;
  model_freshness: number;
  scenario_diversity: number;
}

export interface ImmunityScoreResponse {
  tenant_id: string;
  score: number;
  components: ScoreComponents;
  computed_at_ms: number;
  cache_hit: boolean;
  version: string;
}

export interface ScoreHistoryPoint {
  score: number;
  components: ScoreComponents;
  recorded_at_ms: number;
}

export interface ScoreHistoryResponse {
  tenant_id: string;
  days: number;
  points: ScoreHistoryPoint[];
  point_count: number;
}

export interface AttackTypeCoverage {
  attack_type: string;
  last_tested_ms: number | null;
  scenario_count: number;
  detection_recall: number | null;
  hard_rule_6_passed: boolean | null;
  recommended: boolean;
}

export interface ScenarioCoverageResponse {
  tenant_id: string;
  window_days: number;
  tested_count: number;
  untested_count: number;
  coverage_fraction: number;
  attack_types: AttackTypeCoverage[];
  generated_at_ms: number;
}

export interface FraudRing {
  ring_id: string;
  risk_score: number;
  synthetic: boolean;
  detected_at_ms: number;
  signals: string[];
  member_ids: string[];
}

export interface FraudRingsResponse {
  tenant_id: string;
  rings: FraudRing[];
  count: number;
}

export interface AlertEvent {
  alert_id: string;
  attack_type: string;
  severity: "high" | "medium" | "low";
  risk_score: number;
  account_token: string;
  detected_at_ms: number;
  synthetic: boolean;
  tenant_id: string;
}

// ── Fetch helpers ──────────────────────────────────────────────────────────────

async function get<T>(path: string, token?: string): Promise<T> {
  const res = await fetch(`${base()}${path}`, {
    headers: headers(token),
    cache: "no-store",
  });
  if (!res.ok) throw new Error(`API ${path} → ${res.status}`);
  return res.json() as Promise<T>;
}

// ── Public API ─────────────────────────────────────────────────────────────────

export async function fetchImmunityScore(
  _tenantId: string,
  token?: string
): Promise<ImmunityScoreResponse> {
  return get<ImmunityScoreResponse>("/immunity-score", token);
}

export async function fetchScoreHistory(
  days: number = 30,
  _tenantId: string = "default",
  token?: string
): Promise<ScoreHistoryResponse> {
  return get<ScoreHistoryResponse>(
    `/immunity-score/history?days=${days}`,
    token
  );
}

export async function fetchScenarioCoverage(
  _tenantId: string,
  token?: string
): Promise<ScenarioCoverageResponse> {
  return get<ScenarioCoverageResponse>("/immunity-score/scenarios", token);
}

export async function fetchFraudRings(
  _tenantId: string,
  token?: string
): Promise<FraudRingsResponse> {
  return get<FraudRingsResponse>("/fraud-rings", token);
}

// ── WebSocket URL ──────────────────────────────────────────────────────────────

export function alertsWsUrl(tenantId: string): string {
  const apiUrl = CLIENT_BASE;
  const wsBase = apiUrl.replace(/^http/, "ws");
  return `${wsBase}/ws/alerts?tenant_id=${encodeURIComponent(tenantId)}`;
}

// ── Health ─────────────────────────────────────────────────────────────────────

export interface HealthResponse {
  status: string;
  version: string;
}

export async function fetchHealth(): Promise<HealthResponse> {
  return get<HealthResponse>("/health");
}

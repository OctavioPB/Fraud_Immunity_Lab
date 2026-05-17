/**
 * Client-side auth utilities.
 *
 * `tenant_id` is stored in a non-httpOnly cookie so JS can read it for
 * the WebSocket connection and display. The `access_token` is httpOnly
 * and never accessible from JS.
 */

export function getTenantId(): string {
  if (typeof document === "undefined") return "default";
  const match = document.cookie.match(/(?:^|;\s*)tenant_id=([^;]+)/);
  return match ? decodeURIComponent(match[1]) : "default";
}

export async function logout(): Promise<void> {
  await fetch("/api/auth/logout", { method: "POST" });
  window.location.href = "/login";
}

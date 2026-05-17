import { NextRequest, NextResponse } from "next/server";

const API_BASE = process.env.API_URL ?? "http://localhost:8000";

export async function POST(req: NextRequest): Promise<NextResponse> {
  const body = (await req.json()) as {
    username: string;
    password: string;
    tenant_id?: string;
  };

  let data: { access_token: string; tenant_id: string };
  try {
    const res = await fetch(`${API_BASE}/auth/token`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        username: body.username,
        password: body.password,
        tenant_id: body.tenant_id ?? "default",
      }),
    });
    if (!res.ok) {
      return NextResponse.json({ error: "Invalid credentials" }, { status: 401 });
    }
    data = (await res.json()) as { access_token: string; tenant_id: string };
  } catch {
    return NextResponse.json(
      { error: "API unavailable — check that the backend is running" },
      { status: 503 }
    );
  }

  const response = NextResponse.json({ success: true, tenant_id: data.tenant_id });
  const cookieOpts = {
    secure: process.env.NODE_ENV === "production",
    sameSite: "strict" as const,
    maxAge: 8 * 3600,
    path: "/",
  };
  response.cookies.set("access_token", data.access_token, {
    ...cookieOpts,
    httpOnly: true,
  });
  response.cookies.set("tenant_id", data.tenant_id, {
    ...cookieOpts,
    httpOnly: false, // readable by JS for WebSocket + display
  });
  return response;
}

import type { SessionResponse } from "@schemas";
import { NextRequest, NextResponse } from "next/server";

export const dynamic = "force-dynamic";

const SESSION_SECONDS = 12 * 60 * 60;

// Receives the Google ID token from the browser, has the API verify it, and stores
// our session token in an httpOnly cookie so page scripts can never read it.
export async function POST(req: NextRequest) {
  const { id_token } = (await req.json().catch(() => ({}))) as { id_token?: string };
  if (!id_token) return NextResponse.json({ error: "Missing token" }, { status: 400 });

  const api = process.env.API_URL ?? "http://localhost:8010";
  const res = await fetch(`${api}/v1/auth/google`, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({ id_token }),
    cache: "no-store",
  }).catch(() => null);

  if (!res) return NextResponse.json({ error: "API unreachable" }, { status: 502 });
  if (!res.ok) return NextResponse.json({ error: "Sign-in failed" }, { status: res.status });

  const session = (await res.json()) as SessionResponse;
  const out = NextResponse.json({ email: session.user.email });
  out.cookies.set("session", session.access_token, {
    httpOnly: true,
    sameSite: "lax",
    secure: req.nextUrl.protocol === "https:",
    path: "/",
    maxAge: SESSION_SECONDS,
  });
  return out;
}

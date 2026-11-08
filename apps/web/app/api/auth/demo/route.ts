import type { SessionResponse } from "@schemas";
import { NextRequest, NextResponse } from "next/server";

export const dynamic = "force-dynamic";

// Demo sign-in. The API only answers when DEMO_MODE=true, and the web app only offers the
// button in that case. Same cookie handling as the Google sign-in route.
export async function POST(req: NextRequest) {
  if (process.env.DEMO_MODE !== "true") {
    return NextResponse.json({ error: "Not found" }, { status: 404 });
  }
  const api = process.env.API_URL ?? "http://localhost:8010";
  const res = await fetch(`${api}/v1/auth/demo`, { method: "POST", cache: "no-store" }).catch(
    () => null,
  );
  if (!res) return NextResponse.json({ error: "API unreachable" }, { status: 502 });
  if (!res.ok) return NextResponse.json({ error: "Sign-in failed" }, { status: res.status });

  const session = (await res.json()) as SessionResponse;
  const out = NextResponse.json({ email: session.user.email });
  out.cookies.set("session", session.access_token, {
    httpOnly: true,
    sameSite: "lax",
    secure: req.nextUrl.protocol === "https:",
    path: "/",
    maxAge: 12 * 60 * 60,
  });
  return out;
}

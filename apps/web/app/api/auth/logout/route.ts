import { NextResponse } from "next/server";

export const dynamic = "force-dynamic";

export function POST() {
  const out = NextResponse.json({ ok: true });
  out.cookies.set("session", "", { httpOnly: true, sameSite: "lax", path: "/", maxAge: 0 });
  return out;
}

import { NextRequest, NextResponse } from "next/server";

export const dynamic = "force-dynamic";

// Browser -> this route -> API. The session lives in an httpOnly cookie, so page scripts
// never see it. Only the API's /v1 routes are reachable through here.
// Bodies are passed on as raw bytes, so file uploads (PDF, photos) arrive unchanged.
async function forward(req: NextRequest, ctx: { params: Promise<{ path: string[] }> }) {
  const { path } = await ctx.params;
  if (path[0] !== "v1") return NextResponse.json({ detail: "Not found" }, { status: 404 });

  const api = process.env.API_URL ?? "http://localhost:8010";
  const token = req.cookies.get("session")?.value;
  const hasBody = req.method !== "GET" && req.method !== "HEAD";

  // A browser fetch() with a string body and no header sends text/plain, which the API refuses
  // for JSON. Treat that as JSON; real file types (pdf, jpeg, png) are passed through as they are.
  const sent = req.headers.get("content-type");
  const contentType = !sent || sent.startsWith("text/plain") ? "application/json" : sent;

  const raw = hasBody ? await req.arrayBuffer() : undefined;

  const res = await fetch(`${api}/${path.join("/")}${req.nextUrl.search}`, {
    method: req.method,
    headers: {
      "content-type": contentType,
      ...(token ? { authorization: `Bearer ${token}` } : {}),
    },
    body: raw && raw.byteLength > 0 ? raw : undefined,
    cache: "no-store",
  }).catch(() => null);

  if (!res) {
    return NextResponse.json({ detail: "The service is not reachable. Please try again." }, { status: 502 });
  }
  return new NextResponse(await res.text(), {
    status: res.status,
    headers: { "content-type": res.headers.get("content-type") ?? "application/json" },
  });
}

export { forward as DELETE, forward as GET, forward as POST, forward as PUT };

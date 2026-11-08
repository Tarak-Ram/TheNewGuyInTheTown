import { NextRequest } from "next/server";
import { afterEach, beforeEach, expect, test, vi } from "vitest";
import { DELETE, GET, POST, PUT } from "./route";

type Handler = typeof POST;
type Init = NonNullable<ConstructorParameters<typeof NextRequest>[1]>;

const fetchMock = vi.fn();

beforeEach(() => {
  fetchMock.mockReset();
  // A fresh Response each time: a body can only be read once.
  fetchMock.mockImplementation(async () => new Response('{"ok":true}', { status: 200 }));
  vi.stubGlobal("fetch", fetchMock);
});
afterEach(() => vi.unstubAllGlobals());

function call(handler: Handler, path: string, init: Init = {}) {
  const req = new NextRequest(`http://localhost:3000/api/proxy/${path}`, init);
  return handler(req, { params: Promise.resolve({ path: path.split("?")[0].split("/") }) });
}

function sent() {
  const [url, init] = fetchMock.mock.calls[0];
  return { url: String(url), init: init as RequestInit & { headers: Record<string, string> } };
}

test("a plain fetch() with a JSON string is forwarded as JSON (the browser sends text/plain)", async () => {
  await call(POST, "v1/places/validate", {
    method: "POST",
    headers: { "content-type": "text/plain;charset=UTF-8" },
    body: JSON.stringify({ address: "Wipro Circle" }),
  });
  expect(sent().init.headers["content-type"]).toBe("application/json");
});

test("a request with no content type is forwarded as JSON", async () => {
  await call(POST, "v1/plans", { method: "POST", body: "{}" });
  expect(sent().init.headers["content-type"]).toBe("application/json");
});

test("an explicit JSON content type is kept", async () => {
  await call(POST, "v1/plans", {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: "{}",
  });
  expect(sent().init.headers["content-type"]).toBe("application/json");
});

test("a PDF upload keeps its type and arrives byte for byte", async () => {
  const bytes = new Uint8Array([0x25, 0x50, 0x44, 0x46, 0x2d, 0x00, 0xff, 0x80, 0x0a]);
  await call(PUT, "v1/agreements/abc/file?token=t", {
    method: "PUT",
    headers: { "content-type": "application/pdf" },
    body: bytes,
  });
  const { init } = sent();
  expect(init.headers["content-type"]).toBe("application/pdf");
  expect(new Uint8Array(init.body as ArrayBuffer)).toEqual(bytes);
});

test("the session cookie becomes a bearer token, and is never sent without a cookie", async () => {
  await call(GET, "v1/me", { headers: { cookie: "session=abc123" } });
  expect(sent().init.headers.authorization).toBe("Bearer abc123");

  fetchMock.mockClear();
  await call(GET, "v1/me");
  expect(sent().init.headers.authorization).toBeUndefined();
});

test("the query string is passed on", async () => {
  await call(GET, "v1/plans/1/pgs?area_id=xyz");
  expect(sent().url).toBe("http://localhost:8010/v1/plans/1/pgs?area_id=xyz");
});

test("only /v1 routes can be reached through the proxy", async () => {
  const res = await call(GET, "admin/secrets");
  expect(res.status).toBe(404);
  expect(fetchMock).not.toHaveBeenCalled();
});

test("an API error is passed through unchanged", async () => {
  fetchMock.mockResolvedValue(
    new Response('{"detail":"We could not find that address in Hyderabad."}', {
      status: 422,
      headers: { "content-type": "application/json" },
    }),
  );
  const res = await call(POST, "v1/places/validate", { method: "POST", body: "{}" });
  expect(res.status).toBe(422);
  expect((await res.json()).detail).toContain("could not find that address");
});

test("an unreachable API gives a friendly message", async () => {
  fetchMock.mockRejectedValue(new Error("connect ECONNREFUSED"));
  const res = await call(GET, "v1/me");
  expect(res.status).toBe(502);
  expect((await res.json()).detail).toContain("not reachable");
});

test("GET requests carry no body", async () => {
  await call(GET, "v1/plans");
  expect(sent().init.body).toBeUndefined();
});

test("DELETE is passed through with its query string and the session", async () => {
  await call(DELETE, "v1/me?confirm=DELETE", {
    method: "DELETE",
    headers: { cookie: "session=abc123" },
  });
  const { url, init } = sent();
  expect(url).toBe("http://localhost:8010/v1/me?confirm=DELETE");
  expect(init.method).toBe("DELETE");
  expect(init.headers.authorization).toBe("Bearer abc123");
  expect(init.body).toBeUndefined();
});

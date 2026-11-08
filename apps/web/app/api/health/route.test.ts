import { expect, test } from "vitest";
import { GET } from "./route";

test("web health returns ok", async () => {
  const res = GET();
  expect(res.status).toBe(200);
  expect(await res.json()).toEqual({ status: "ok", service: "web" });
});

import path from "node:path";
import { fileURLToPath } from "node:url";

const here = path.dirname(fileURLToPath(import.meta.url));

/** @type {import('next').NextConfig} */
const nextConfig = {
  output: "standalone",
  // Trace from the repo root so the shared packages/ folder is bundled.
  outputFileTracingRoot: path.join(here, "../.."),
  // Allow importing the shared TypeScript contracts from packages/schemas.
  experimental: { externalDir: true },
};

export default nextConfig;

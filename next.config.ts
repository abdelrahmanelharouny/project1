import type { NextConfig } from "next";
import createNextIntlPlugin from "next-intl/plugin";

// P1 i18n: next-intl without i18n routing — the active locale lives in the
// NEXT_LOCALE cookie and message catalogs are merged from messages/<locale>/.
const withNextIntl = createNextIntlPlugin("./src/i18n/request.ts");

const nextConfig: NextConfig = {
  output: "standalone",
  // Isolated build dir (e.g. NEXT_DIST_DIR=.next-build-check bunx next build)
  // lets CI/ops run a production build without clobbering a running dev
  // server's .next directory. Defaults to the standard .next.
  distDir: process.env.NEXT_DIST_DIR || ".next",
  // Type errors now FAIL the build: the codebase is tsc-clean (P0 Phase 1)
  // and `bunx tsc --noEmit` is a blocking CI gate. Do not re-enable.
  typescript: {
    ignoreBuildErrors: false,
  },
  reactStrictMode: false,
  devIndicators: false,
  // Next 16 dev origin protection: the sandbox serves the app via 127.0.0.1
  // (direct) and the gateway host (preview panel). Without these, HMR and
  // lazy-chunk fetches from those origins are blocked and the client-side
  // workspace chunk never loads (eternal "Loading CropTwist workspace…").
  allowedDevOrigins: ["127.0.0.1", "localhost"],
  // Fallback proxy: when the app is reached directly on :3000 (bypassing the
  // Caddy gateway), forward /api/v1/* to the CropTwist FastAPI mini-service.
  // Behind the gateway, Caddy handles this via ?XTransformPort=3030 and Next
  // never sees these requests.
  async rewrites() {
    return [
      {
        source: "/api/v1/:path*",
        destination: "http://127.0.0.1:3030/api/v1/:path*",
      },
    ];
  },
};

export default withNextIntl(nextConfig);

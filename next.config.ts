import type { NextConfig } from "next";
import createNextIntlPlugin from "next-intl/plugin";

// P1 i18n: next-intl without i18n routing — the active locale lives in the
// NEXT_LOCALE cookie and message catalogs are merged from messages/<locale>/.
const withNextIntl = createNextIntlPlugin("./src/i18n/request.ts");

const nextConfig: NextConfig = {
  output: "standalone",
  /* config options here */
  typescript: {
    ignoreBuildErrors: true,
  },
  reactStrictMode: false,
  devIndicators: false,
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

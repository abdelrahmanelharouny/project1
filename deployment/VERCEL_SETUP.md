# Vercel setup

The Vercel project serves only the Next.js frontend from this monorepo; FastAPI and workers remain separate. It does not provision a backend, database, credentials, or a provider deployment from source control.

## Project settings

Create or review the Vercel project with these exact values:

- **Root Directory:** `.` (repository root)
- **Framework Preset:** Next.js
- **Install Command:** `bun install --frozen-lockfile`
- **Build Command:** `bun run build`
- **Output Directory:** leave the Next.js default; do not point it at `.next/standalone`
- **Runtime:** Node.js 22.x, matching `package.json` engines and the standalone Docker runner. **Package/build tool:** Bun `1.3.4`, matching the lockfile and Docker builder

The build script keeps the existing standalone Docker layout while still running a normal `next build` for Vercel. Do not replace it with a static export: the frontend uses Next route handlers for the existing cookie session flow.

## Required environment variable

Set `CROPTWIST_API_ORIGIN` in the Vercel project for every environment that can serve the app. It must be an absolute `https://` origin on Vercel; HTTP is allowed only for local/non-Vercel execution as an origin containing only scheme, host, and optional port. Examples:

```text
https://api.example.com
https://api.example.com:8443
```

The value must not contain a path prefix, query string, fragment, username, password, bearer token, API key, or other credentials. It is a server-only value. Never rename it to `NEXT_PUBLIC_CROPTWIST_API_ORIGIN` and never place secrets in a public environment variable.

Vercel builds fail closed when this value is missing. Local development and the standalone Docker image retain the loopback fallback `http://127.0.0.1:3030` only outside Vercel; set the variable explicitly when a container must reach a separate backend host.

## Git deployment gate

Preview and production Git deployments are intentionally disabled until the owner confirms the project is eligible and approves an isolated preview. Keep the Vercel project’s Git deployment settings disabled for the relevant branches; the checked-in `vercel.json` uses `"deploymentEnabled": { "*": false }` so every Git branch is off by default.

If an owner explicitly authorizes an isolated preview, enable only that preview path in the Vercel project UI, verify the API origin and cookie/session behavior, then disable the preview setting again. Do not enable production Git deployments as part of this change. No Vercel deployment is performed by this repository change.

## Hobby-plan caution

Vercel Hobby is for non-commercial personal use. Vercel’s documented Hobby limits include 100 GB fast data transfer, 10 GB origin transfer, 1 million function invocations, 4 CPU hours, 360 GB-hours, 5,000 image transformations, one concurrent deployment, a 45-minute build limit, and a 120-second external rewrite timeout. Confirm current plan and fair-use eligibility with the owner before enabling any hosted preview.

Sources: [Hobby plan](https://vercel.com/docs/plans/hobby), [Limits](https://vercel.com/docs/limits), and [Fair use guidelines](https://vercel.com/docs/limits/fair-use-guidelines).

## Runtime compatibility

Vercel officially supports Node.js 22.x and honors `package.json`'s `engines.node` setting. This project now pins the major runtime to 22.x and keeps Bun 1.3.4 for dependency installation/build only. The standalone runtime also uses Node 22: the locally observed Bun 1.3.4/Next.js 16.4.6 CommonJS-wrapper failure must not be shipped as a healthy runtime. [1]

[1]: https://vercel.com/docs/functions/runtimes/node-js/node-js-versions "Vercel Supported Node.js Versions"

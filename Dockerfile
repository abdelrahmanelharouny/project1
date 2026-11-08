# FieldShift web — Next.js 16 (App Router) standalone image.
#
# Multi-stage: deps -> builder -> runner.
# `bun run build` executes INSIDE the image build only (never in the dev
# sandbox). next.config.ts sets output: "standalone", and the package.json
# "build" script already copies .next/static and public/ into
# .next/standalone/, so the runner layer needs no manual copying beyond the
# safety copies below.

FROM oven/bun:1 AS deps
WORKDIR /app
# Lockfile-driven install; bun blocks lifecycle (postinstall) scripts unless
# they are allowlisted in trustedDependencies, so this is reproducible.
# prisma is present in package.json but unused by the app (src/lib/db.ts has
# no importers), so no `prisma generate` step is required here.
COPY package.json bun.lock ./
RUN bun install --frozen-lockfile

FROM oven/bun:1 AS builder
WORKDIR /app
COPY --from=deps /app/node_modules ./node_modules
COPY . .
ENV NEXT_TELEMETRY_DISABLED=1
# Runs: next build && cp static+public into .next/standalone
RUN bun run build

FROM oven/bun:1-slim AS runner
WORKDIR /app
ENV NODE_ENV=production \
    PORT=3000 \
    HOSTNAME=0.0.0.0 \
    NEXT_TELEMETRY_DISABLED=1

# Non-root runtime user (explicit USER root in case the base switches users).
USER root
RUN groupadd --system --gid 10001 nextjs \
 && useradd --system --uid 10001 --gid nextjs --home-dir /app --shell /usr/sbin/nologin nextjs

# Standalone server (server.js, node_modules subset, .next/static, public/)
COPY --from=builder --chown=nextjs:nextjs /app/.next/standalone ./
# Safety copies: idempotent with the build script's own cp steps.
COPY --from=builder --chown=nextjs:nextjs /app/.next/static ./.next/static
COPY --from=builder --chown=nextjs:nextjs /app/public ./public

USER nextjs
EXPOSE 3000

# Matches package.json "start" (NODE_ENV=production bun .next/standalone/server.js)
CMD ["bun", "server.js"]

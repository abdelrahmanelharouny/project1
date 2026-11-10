#!/usr/bin/env bash
# CropTwist — one-command stack bootstrap.
#
# Recovers and starts the complete local stack after a sandbox wipe (or
# brings it up from scratch). Idempotent: every step is skipped when its
# artifact already exists, so re-running on a healthy stack is a cheap
# no-op + verification. The script distinguishes three situations and says
# which one it is in:
#   - START      : service/artifact already present -> skip (verify only)
#   - REBUILD    : dependency/env missing -> reinstall it
#   - MIGRATE    : apply alembic migrations (always run; idempotent at head)
#
# Usage:
#   bash scripts/rebuild_stack.sh              # full stack: pg+api+bridge+web
#   bash scripts/rebuild_stack.sh --pg-only    # postgres only (backup cron)
#   bash scripts/rebuild_stack.sh --dry-run    # print the plan, change nothing
#   bash scripts/rebuild_stack.sh --help
#
# The 9-step playbook (previously executed by hand 3x after sandbox wipes):
#   1. Postgres 16.10 + PostGIS 3.5.0 binaries via in-repo micromamba
#   2. initdb the cluster (first run only; NEVER re-inits over existing data)
#   3. Start postgres on 127.0.0.1:5433 (socket dir /tmp) + create DB/PostGIS
#   4. Python venv + requirements.txt (first run only)
#   5. alembic upgrade head (idempotent; no destructive operations)
#   6. Seed the demo workspace (idempotent library function)
#   7. Daemonize uvicorn on 127.0.0.1:3030
#   8. LLM bridge (bun) on 127.0.0.1:3035
#   9. Frontend (next dev) on 127.0.0.1:3000
#
# Safety: no destructive database operations of any kind. initdb only runs
# when $PGDATA has no PG_VERSION (missing environment recovery); it never
# deletes or recreates an existing cluster. All state lives INSIDE the repo
# (db/, .venv, .env) so it survives sandbox resets. Nothing here is needed
# in production — use docker-compose or a managed Postgres
# (docs/architecture/deployment.md, docs/operations/STACK_BOOTSTRAP.md).

set -euo pipefail

# ---------------------------------------------------------------------------
# Layout (in-repo, wipe-resistant)
# ---------------------------------------------------------------------------
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"   # -> repo root
API_DIR="$ROOT/mini-services/fieldshift-api"
BRIDGE_DIR="$ROOT/mini-services/llm-bridge"
DB_DIR="$ROOT/db"
PGENV="$DB_DIR/pgenv"
PGDATA="$DB_DIR/pgdata"
MAMBA_ROOT="$DB_DIR/mamba-root"
MICROMAMBA="$DB_DIR/bin/micromamba"
VENV="$API_DIR/.venv"
DAEMON="$API_DIR/scripts/daemonize.py"

# Configurable ports/paths (env overrides; sane defaults for the sandbox)
PGPORT="${CROPTWIST_DB_PORT:-5433}"
PGHOST="${CROPTWIST_DB_HOST:-127.0.0.1}"
API_PORT="${CROPTWIST_API_PORT:-3030}"
BRIDGE_PORT="${CROPTWIST_LLM_BRIDGE_PORT:-3035}"
WEB_PORT="${CROPTWIST_WEB_PORT:-3000}"
DBNAME="${CROPTWIST_DB_NAME:-croptwist}"
WEB_LOG="${CROPTWIST_WEB_LOG:-$ROOT/dev.log}"
BRIDGE_LOG="${CROPTWIST_BRIDGE_LOG:-$BRIDGE_DIR/bridge.log}"

usage() {
  sed -n '2,30p' "${BASH_SOURCE[0]}" | sed 's/^# \{0,1\}//'
}

PG_ONLY=false
DRY_RUN=false
while [[ $# -gt 0 ]]; do
  case "$1" in
    --pg-only) PG_ONLY=true ;;
    --dry-run) DRY_RUN=true ;;
    --help|-h) usage; exit 0 ;;
    *) echo "ERROR: unknown option '$1' (see --help)" >&2; exit 2 ;;
  esac
  shift
done

step() { printf '\n=== [%s] %s ===\n' "$1" "$2"; }
# run <label> <cmd...> — execute unless --dry-run (then just print the plan)
run() {
  local label="$1"; shift
  if $DRY_RUN; then echo "[dry-run] $label: $*"; else "$@"; fi
}
skip_or_run() { # skip_or_run <noun> <exists-probe-result> <rebuild-cmd...>
  local noun="$1" exists="$2"; shift 2
  if [[ "$exists" == "yes" ]]; then
    echo "$noun present, skipping."
  elif $DRY_RUN; then
    echo "[dry-run] $noun missing — would rebuild: $*"
  else
    echo "$noun missing — rebuilding..."
    "$@"
  fi
}

if [[ ! -x "$MICROMAMBA" ]]; then
  echo "FATAL: micromamba not found at $MICROMAMBA (it is committed in-repo)." >&2
  exit 1
fi
if ! command -v bun >/dev/null 2>&1; then
  echo "FATAL: bun not on PATH (required for the LLM bridge and frontend)." >&2
  exit 1
fi
if ! command -v python3 >/dev/null 2>&1; then
  echo "FATAL: python3 not on PATH." >&2
  exit 1
fi
if $DRY_RUN; then
  echo "*** DRY-RUN — printing the plan, changing nothing ***"
  echo "layout: root=$ROOT api=$API_DIR bridge=$BRIDGE_DIR"
  echo "ports : pg=$PGPORT api=$API_PORT bridge=$BRIDGE_PORT web=$WEB_PORT db=$DBNAME"
fi

# ---------------------------------------------------------------------------
# .env — gitignored, so a sandbox wipe deletes it. Recreate if missing.
# ---------------------------------------------------------------------------
if [[ ! -f "$API_DIR/.env" ]]; then
  if $DRY_RUN; then
    echo "[dry-run] .env missing — would recreate $API_DIR/.env"
  else
    step "env" "recreating gitignored .env (lost in sandbox wipe)"
    cat > "$API_DIR/.env" <<'ENV'
CROPTWIST_DEV_MODE=true
CROPTWIST_ENVIRONMENT=development
CROPTWIST_DB_PGDATA_DIR=/home/z/my-project/db/pgdata
CROPTWIST_DB_PORT=5433
CROPTWIST_DB_SOCKET_DIR=/tmp
CROPTWIST_LLM_BRIDGE_URL=http://127.0.0.1:3035
ENV
    echo ".env recreated."
  fi
else
  echo ".env present, skipping."
fi
export CROPTWIST_DB_PGDATA="$PGDATA"
export CROPTWIST_DB_PORT="$PGPORT"
export CROPTWIST_DB_SOCKET_DIR=/tmp

# ---------------------------------------------------------------------------
# 1. Postgres binaries  (REBUILD only when pgenv is missing)
# ---------------------------------------------------------------------------
step 1 "postgres binaries (micromamba -> $PGENV)"
if [[ -x "$PGENV/bin/pg_ctl" ]]; then
  echo "pgenv present, skipping."
elif $DRY_RUN; then
  echo "[dry-run] pgenv missing — would run: micromamba create -p $PGENV postgresql=16.10 postgis=3.5.0"
else
  echo "pgenv missing — rebuilding..."
  # A previous layout symlinked db/pgdata & db/pgenv to /home/z/fieldshift-pg
  # (wiped by sandbox resets). Replace dangling symlinks with real in-repo dirs.
  [[ -L "$PGDATA" ]] && rm -f "$PGDATA"
  [[ -L "$PGENV" ]] && rm -f "$PGENV"
  MAMBA_ROOT_PREFIX="$MAMBA_ROOT" "$MICROMAMBA" create -y -p "$PGENV" \
    -c conda-forge postgresql=16.10 postgis=3.5.0
fi

# ---------------------------------------------------------------------------
# 2. Cluster init (RECOVER only when the data dir is empty — never re-init
#    over an existing cluster; that would destroy persistent data)
# ---------------------------------------------------------------------------
step 2 "initdb cluster ($PGDATA)"
if [[ -f "$PGDATA/PG_VERSION" ]]; then
  echo "cluster already initialized, skipping."
elif $DRY_RUN; then
  echo "[dry-run] no PG_VERSION — would initdb -D $PGDATA -U postgres (first-run recovery)"
else
  echo "no PG_VERSION — first-run initdb (recovery of a missing environment)..."
  "$PGENV/bin/initdb" -D "$PGDATA" -U postgres -E UTF8 \
    --auth-local=trust --auth-host=trust
fi

# ---------------------------------------------------------------------------
# 3. Start postgres + ensure database/PostGIS (idempotent helper)
# ---------------------------------------------------------------------------
step 3 "start postgres on $PGHOST:$PGPORT + ensure db '$DBNAME'"
if $DRY_RUN; then
  echo "[dry-run] would run ensure_db.py (start postgres if down; CREATE DATABASE/EXTENSION IF NOT EXISTS)"
else
  python3 "$API_DIR/scripts/ensure_db.py"
fi

if $PG_ONLY; then
  step "done" "pg-only mode: postgres is up on $PGHOST:$PGPORT"
  if ! $DRY_RUN; then
    "$PGENV/bin/pg_isready" -h "$PGHOST" -p "$PGPORT" -U postgres
  fi
  exit 0
fi

# ---------------------------------------------------------------------------
# 4. Python venv (REBUILD only when uvicorn is missing)
# ---------------------------------------------------------------------------
step 4 "python venv ($VENV)"
if [[ -x "$VENV/bin/uvicorn" ]]; then
  echo "venv present, skipping."
elif $DRY_RUN; then
  echo "[dry-run] venv missing — would create venv + pip install -r requirements.txt"
else
  echo "venv missing — rebuilding..."
  python3 -m venv "$VENV"
  "$VENV/bin/pip" install --quiet --upgrade pip
  "$VENV/bin/pip" install --quiet -r "$API_DIR/requirements.txt"
fi

# ---------------------------------------------------------------------------
# 5. Migrations (always "run" — alembic upgrade head is idempotent at head)
# ---------------------------------------------------------------------------
step 5 "alembic upgrade head"
if $DRY_RUN; then
  echo "[dry-run] would run: alembic upgrade head (in $API_DIR)"
else
  (cd "$API_DIR" && "$VENV/bin/alembic" upgrade head)
fi

# ---------------------------------------------------------------------------
# 6. Seed demo workspace (idempotent)
# ---------------------------------------------------------------------------
step 6 "seed demo workspace"
if $DRY_RUN; then
  echo "[dry-run] would run ensure_demo_workspace(db) via venv python (idempotent)"
else
  (cd "$API_DIR" && "$VENV/bin/python" - <<'PY'
from app.core.database import SessionLocal
from app.dev.seed import ensure_demo_workspace

db = SessionLocal()
try:
    info = ensure_demo_workspace(db)
    db.commit()
    print("seed:", info)
finally:
    db.close()
PY
  )
fi

# ---------------------------------------------------------------------------
# 7. Daemonize the API (double-fork: survives sandbox process reaping)
# ---------------------------------------------------------------------------
api_up() {
  curl -fs -o /dev/null --max-time 3 "http://$PGHOST:$API_PORT/api/v1/health" 2>/dev/null || \
  curl -fs -o /dev/null --max-time 3 "http://$PGHOST:$API_PORT/health" 2>/dev/null
}
API_LOG="${CROPTWIST_API_LOG:-$API_DIR/api.log}"
step 7 "daemonize uvicorn on 127.0.0.1:$API_PORT"
if ! $DRY_RUN && api_up; then
  echo "API already serving on :$API_PORT, skipping."
elif $DRY_RUN; then
  echo "[dry-run] would check :$API_PORT/health; if down, daemonize uvicorn app.main:app --port $API_PORT"
else
  : > "$API_LOG"
  # uvicorn needs CWD=$API_DIR so `app.main:app` is importable.
  (cd "$API_DIR" && python3 "$DAEMON" --log "$API_LOG" \
    "$VENV/bin/uvicorn" app.main:app \
    --host "$PGHOST" --port "$API_PORT")
  echo "daemonized (log: $API_LOG); waiting for /health ..."
  for _ in $(seq 1 45); do
    api_up && break
    sleep 1
  done
  api_up || { echo "API failed to become healthy — see $API_LOG" >&2; exit 1; }
fi

# ---------------------------------------------------------------------------
# 8. LLM bridge (bun --hot) on 127.0.0.1:$BRIDGE_PORT
# ---------------------------------------------------------------------------
bridge_up() { curl -fs -o /dev/null --max-time 3 "http://$PGHOST:$BRIDGE_PORT/health" 2>/dev/null; }
step 8 "llm bridge on 127.0.0.1:$BRIDGE_PORT"
if [[ ! -d "$BRIDGE_DIR/node_modules/z-ai-web-dev-sdk" ]]; then
  run "bridge deps" bash -c "cd '$BRIDGE_DIR' && bun install"
else
  echo "bridge node_modules present, skipping install."
fi
if ! $DRY_RUN && bridge_up; then
  echo "bridge already serving on :$BRIDGE_PORT, skipping."
elif $DRY_RUN; then
  echo "[dry-run] would check :$BRIDGE_PORT/health; if down, daemonize 'bun run dev' (bun --hot index.ts)"
else
  : > "$BRIDGE_LOG"
  (cd "$BRIDGE_DIR" && python3 "$DAEMON" --log "$BRIDGE_LOG" bun run dev)
  echo "daemonized (log: $BRIDGE_LOG); waiting for /health ..."
  for _ in $(seq 1 20); do
    bridge_up && break
    sleep 1
  done
  bridge_up || { echo "bridge failed to become healthy — see $BRIDGE_LOG" >&2; exit 1; }
fi

# ---------------------------------------------------------------------------
# 9. Frontend (next dev) on 127.0.0.1:$WEB_PORT
# ---------------------------------------------------------------------------
web_up() { curl -fs -o /dev/null --max-time 5 "http://$PGHOST:$WEB_PORT/" 2>/dev/null; }
step 9 "frontend on 127.0.0.1:$WEB_PORT"
if [[ ! -x "$ROOT/node_modules/.bin/next" ]]; then
  run "web deps" bash -c "cd '$ROOT' && bun install --frozen-lockfile"
else
  echo "web node_modules present, skipping install."
fi
if ! $DRY_RUN && web_up; then
  echo "frontend already serving on :$WEB_PORT, skipping."
elif $DRY_RUN; then
  echo "[dry-run] would check :$WEB_PORT/; if down, daemonize 'next dev --webpack -p $WEB_PORT' (log: $WEB_LOG)"
else
  : > "$WEB_LOG"
  (cd "$ROOT" && python3 "$DAEMON" --log "$WEB_LOG" \
    "$ROOT/node_modules/.bin/next" dev --webpack -p "$WEB_PORT")
  echo "daemonized (log: $WEB_LOG); waiting for :$WEB_PORT (cold compile can take ~60s) ..."
  for _ in $(seq 1 90); do
    web_up && break
    sleep 2
  done
  web_up || { echo "frontend failed to become healthy — see $WEB_LOG" >&2; exit 1; }
fi

# ---------------------------------------------------------------------------
# Verification
# ---------------------------------------------------------------------------
step "verify" "health + demo login + bridge + web"
if $DRY_RUN; then
  echo "[dry-run] would verify: pg_isready, api /api/v1/health, demo login + /farms, bridge /health, web GET /"
  echo "*** DRY-RUN COMPLETE — nothing was changed ***"
  exit 0
fi
"$PGENV/bin/pg_isready" -h "$PGHOST" -p "$PGPORT" -U postgres
curl -fs --max-time 5 "http://$PGHOST:$API_PORT/api/v1/health" >/dev/null 2>&1 || \
curl -fs --max-time 5 "http://$PGHOST:$API_PORT/health" >/dev/null 2>&1 || {
  echo "API health check failed — inspect logs:" >&2
  exit 1
}
TOKEN=$(curl -fs -X POST "http://$PGHOST:$API_PORT/api/v1/auth/login" \
  -H 'Content-Type: application/json' \
  -d '{"email":"demo@croptwist.local","password":"croptwist-demo-2026"}' \
  | "$VENV/bin/python" -c 'import sys,json; print(json.load(sys.stdin)["token"])')
curl -fs -o /dev/null --max-time 10 -H "Authorization: Bearer $TOKEN" \
  "http://$PGHOST:$API_PORT/api/v1/farms"
bridge_up || { echo "bridge health check failed — see $BRIDGE_LOG" >&2; exit 1; }
web_up    || { echo "web health check failed — see $WEB_LOG" >&2; exit 1; }
echo "CropTwist stack OK: pg :$PGPORT, api :$API_PORT, bridge :$BRIDGE_PORT, web :$WEB_PORT"

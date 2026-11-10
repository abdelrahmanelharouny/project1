#!/usr/bin/env bash
# CropTwist — one-command stack bootstrap (sandbox-specific).
#
# Restores the full local stack after a sandbox wipe (or brings it up from
# scratch). Idempotent: every step is skipped when its artifact already
# exists, so re-running on a healthy stack is a cheap no-op + verification.
#
#   bash scripts/rebuild_stack.sh             # full stack (pg + api + seed)
#   bash scripts/rebuild_stack.sh --pg-only   # postgres only (for backup cron)
#
# What it does (the 7-step playbook, previously executed by hand 3x):
#   1. Postgres 16.10 + PostGIS 3.5.0 binaries via in-repo micromamba
#   2. initdb the cluster (first run only)
#   3. Start postgres on 127.0.0.1:5433 (socket dir /tmp) + create DB/PostGIS
#   4. Python venv + requirements.txt (first run only)
#   5. alembic upgrade head
#   6. Seed the demo workspace (idempotent library function)
#   7. Daemonize uvicorn on 127.0.0.1:3030 (survives tool-call process reaping)
#
# All state lives INSIDE the repo (db/, .venv, .env) so it survives sandbox
# resets that wipe paths outside /home/z/my-project. Nothing here is committed
# (see .gitignore). Production must NOT use this script — use docker-compose
# or a managed Postgres (docs/architecture/deployment.md).

set -euo pipefail

# ---------------------------------------------------------------------------
# Layout (in-repo, wipe-resistant)
# ---------------------------------------------------------------------------
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"   # -> repo root
API_DIR="$ROOT/mini-services/fieldshift-api"
DB_DIR="$ROOT/db"
PGENV="$DB_DIR/pgenv"
PGDATA="$DB_DIR/pgdata"
MAMBA_ROOT="$DB_DIR/mamba-root"
MICROMAMBA="$DB_DIR/bin/micromamba"
VENV="$API_DIR/.venv"

PGPORT="${CROPTWIST_DB_PORT:-5433}"
PGHOST="127.0.0.1"
API_PORT="${CROPTWIST_API_PORT:-3030}"
DBNAME="${CROPTWIST_DB_NAME:-croptwist}"

PG_ONLY=false
[[ "${1:-}" == "--pg-only" ]] && PG_ONLY=true

step() { printf '\n=== [%s] %s ===\n' "$1" "$2"; }

if [[ ! -x "$MICROMAMBA" ]]; then
  echo "FATAL: micromamba not found at $MICROMAMBA (it is committed in-repo)." >&2
  exit 1
fi

# ---------------------------------------------------------------------------
# .env — gitignored, so a sandbox wipe deletes it. Recreate if missing.
# ---------------------------------------------------------------------------
if [[ ! -f "$API_DIR/.env" ]]; then
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
export CROPTWIST_DB_PGDATA="$PGDATA"
export CROPTWIST_DB_PORT="$PGPORT"
export CROPTWIST_DB_SOCKET_DIR=/tmp

# ---------------------------------------------------------------------------
# 1. Postgres binaries
# ---------------------------------------------------------------------------
step 1 "postgres binaries (micromamba -> $PGENV)"
if [[ ! -x "$PGENV/bin/pg_ctl" ]]; then
  # A previous layout symlinked db/pgdata & db/pgenv to /home/z/fieldshift-pg
  # (wiped by sandbox resets). Replace dangling symlinks with real in-repo dirs.
  [[ -L "$PGDATA" ]] && rm -f "$PGDATA"
  [[ -L "$PGENV" ]] && rm -f "$PGENV"
  MAMBA_ROOT_PREFIX="$MAMBA_ROOT" "$MICROMAMBA" create -y -p "$PGENV" \
    -c conda-forge postgresql=16.10 postgis=3.5.0
else
  echo "pgenv present, skipping."
fi

# ---------------------------------------------------------------------------
# 2. Cluster init (first run only)
# ---------------------------------------------------------------------------
step 2 "initdb cluster ($PGDATA)"
if [[ ! -f "$PGDATA/PG_VERSION" ]]; then
  "$PGENV/bin/initdb" -D "$PGDATA" -U postgres -E UTF8 \
    --auth-local=trust --auth-host=trust
else
  echo "cluster already initialized, skipping."
fi

# ---------------------------------------------------------------------------
# 3. Start postgres + ensure database/PostGIS (idempotent helper)
# ---------------------------------------------------------------------------
step 3 "start postgres on $PGHOST:$PGPORT + ensure db '$DBNAME'"
python3 "$API_DIR/scripts/ensure_db.py"

if $PG_ONLY; then
  step "done" "pg-only mode: postgres is up on $PGHOST:$PGPORT"
  "$PGENV/bin/pg_isready" -h "$PGHOST" -p "$PGPORT" -U postgres
  exit 0
fi

# ---------------------------------------------------------------------------
# 4. Python venv
# ---------------------------------------------------------------------------
step 4 "python venv ($VENV)"
if [[ ! -x "$VENV/bin/uvicorn" ]]; then
  python3 -m venv "$VENV"
  "$VENV/bin/pip" install --quiet --upgrade pip
  "$VENV/bin/pip" install --quiet -r "$API_DIR/requirements.txt"
else
  echo "venv present, skipping."
fi

# ---------------------------------------------------------------------------
# 5. Migrations
# ---------------------------------------------------------------------------
step 5 "alembic upgrade head"
cd "$API_DIR"
"$VENV/bin/alembic" upgrade head

# ---------------------------------------------------------------------------
# 6. Seed demo workspace (idempotent)
# ---------------------------------------------------------------------------
step 6 "seed demo workspace"
"$VENV/bin/python" - <<'PY'
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

# ---------------------------------------------------------------------------
# 7. Daemonize the API (double-fork: survives sandbox process reaping)
# ---------------------------------------------------------------------------
step 7 "daemonize uvicorn on 127.0.0.1:$API_PORT"
if curl -fs -o /dev/null --max-time 3 "http://$PGHOST:$API_PORT/health" 2>/dev/null || \
   curl -fs -o /dev/null --max-time 3 "http://$PGHOST:$API_PORT/api/v1/health" 2>/dev/null; then
  echo "API already serving on :$API_PORT, skipping."
else
  "$VENV/bin/python" "$API_DIR/scripts/daemonize.py" \
    "$VENV/bin/uvicorn" app.main:app \
    --host "$PGHOST" --port "$API_PORT"
  echo "daemonized; waiting for /health ..."
  for _ in $(seq 1 30); do
    if curl -fs -o /dev/null --max-time 2 "http://$PGHOST:$API_PORT/api/v1/health" 2>/dev/null || \
       curl -fs -o /dev/null --max-time 2 "http://$PGHOST:$API_PORT/health" 2>/dev/null; then
      break
    fi
    sleep 1
  done
fi

# ---------------------------------------------------------------------------
# Verification
# ---------------------------------------------------------------------------
step "verify" "health + demo login + AI recommendations"
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
echo "CropTwist stack OK (pg $PGPORT, api $API_PORT, bridge 3035, web 3000)"

#!/usr/bin/env bash
#
# FieldShift — sandbox stack launcher (idempotent).
#
# Starts the pieces of the development stack that are not already running.
# Every subcommand first CHECKS, then starts only what is missing, so it is
# safe to run repeatedly.
#
# Usage:
#   scripts/start-stack.sh pg|api|web|all
#   scripts/start-stack.sh rebuild          # rebuild the toolchain from scratch
#
# Subcommands:
#   pg     Ensure the user-space PostgreSQL 16 + PostGIS 3.5 cluster is up
#          (127.0.0.1:5433, unix socket /tmp, database `fieldshift`).
#   api    Ensure the FastAPI backend answers on 127.0.0.1:3030; if not,
#          start it via scripts/daemonize.py (uvicorn, log to
#          /home/z/my-project/fieldshift-api.log).
#   web    Ensure something answers on :3000; if not and a standalone Next
#          build exists, start it via scripts/daemonize.py; otherwise print
#          the dev-server hint.
#   all    pg + api + web, in dependency order.
#   rebuild Rebuild the toolchain from scratch (documented here; implemented
#          below as a real subcommand):
#
#            # 1. PostgreSQL 16.10 + PostGIS 3.5.0 user-space environment
#            export MAMBA_ROOT_PREFIX=/home/z/fieldshift-pg/mamba-root
#            /home/z/my-project/db/bin/micromamba create -y \
#              -p /home/z/fieldshift-pg/pgenv -c conda-forge \
#              postgresql=16.10 postgis=3.5.0
#            # 2. Fresh cluster (initdb) — only when pgdata is absent
#            /home/z/fieldshift-pg/pgenv/bin/initdb -D /home/z/fieldshift-pg/pgdata \
#              -U postgres -E UTF8
#            # 3. Start cluster + create `fieldshift` + PostGIS extension
#            cd /home/z/my-project/mini-services/fieldshift-api
#            FIELDSHIFT_DB_PGDATA=/home/z/fieldshift-pg/pgdata \
#              python3 scripts/ensure_db.py
#            # 4. API virtualenv + pinned dependencies
#            python3 -m venv /home/z/fieldshift-api-venv
#            /home/z/fieldshift-api-venv/bin/pip install --no-cache-dir \
#              -r requirements.txt
#            # 5. Migrate to head
#            /home/z/fieldshift-api-venv/bin/alembic upgrade head
#
# The frontend has no rebuild step here: `bun install && bun run build` at the
# repository root produces .next/standalone (see /home/z/my-project/Dockerfile).

set -euo pipefail

REPO_ROOT="/home/z/my-project"
API_DIR="${REPO_ROOT}/mini-services/fieldshift-api"
API_LOG="${REPO_ROOT}/fieldshift-api.log"
DAEMONIZE="${API_DIR}/scripts/daemonize.py"

PG_ROOT="/home/z/fieldshift-pg"
PGDATA="${PG_ROOT}/pgdata"
PGENV_BIN="${PG_ROOT}/pgenv/bin"
PG_LOG="${PG_ROOT}/pg.log"
PG_PORT="5433"
PG_USER="postgres"
PG_DB="fieldshift"

API_PORT="3030"
WEB_PORT="3000"
API_VENV="/home/z/fieldshift-api-venv"
STANDALONE_SERVER="/home/z/fieldshift-app/.next/standalone/server.js"

log() { printf '[start-stack] %s\n' "$*"; }

http_ok() {  # http_ok <url> -> 0 when HTTP 200
  curl -fsS -o /dev/null --max-time 3 "$1" 2>/dev/null
}

# ---------------------------------------------------------------------------
# pg — user-space PostgreSQL cluster
# ---------------------------------------------------------------------------
pg_ready() {
  [ -x "${PGENV_BIN}/pg_isready" ] && "${PGENV_BIN}/pg_isready" -h 127.0.0.1 -p "${PG_PORT}" -U "${PG_USER}" >/dev/null 2>&1
}

ensure_pg() {
  if pg_ready; then
    log "pg: PostgreSQL already accepting connections on :${PG_PORT}"
  else
    if [ ! -x "${PGENV_BIN}/pg_ctl" ]; then
      log "pg: ${PGENV_BIN}/pg_ctl not found — run 'scripts/start-stack.sh rebuild' first."
      exit 1
    fi
    if [ ! -d "${PGDATA}" ]; then
      log "pg: data dir ${PGDATA} missing — running initdb"
      mkdir -p "${PG_ROOT}"
      "${PGENV_BIN}/initdb" -D "${PGDATA}" -U "${PG_USER}" -E UTF8 >> "${PG_LOG}" 2>&1
    fi
    log "pg: starting cluster on :${PG_PORT}"
    "${PGENV_BIN}/pg_ctl" -D "${PGDATA}" \
      -o "-p ${PG_PORT} -c listen_addresses=127.0.0.1 -c unix_socket_directories=/tmp" \
      -l "${PG_LOG}" start >> "${PG_LOG}" 2>&1
    pg_ready || { log "pg: failed to start — see ${PG_LOG}"; exit 1; }
  fi

  # Database + PostGIS extension (idempotent; mirrors scripts/ensure_db.py).
  if ! "${PGENV_BIN}/psql" -h 127.0.0.1 -p "${PG_PORT}" -U "${PG_USER}" -d postgres -tAc \
      "SELECT 1 FROM pg_database WHERE datname='${PG_DB}'" 2>/dev/null | grep -q 1; then
    log "pg: creating database ${PG_DB}"
    "${PGENV_BIN}/psql" -h 127.0.0.1 -p "${PG_PORT}" -U "${PG_USER}" -d postgres \
      -c "CREATE DATABASE ${PG_DB} ENCODING 'UTF8'" >> "${PG_LOG}" 2>&1
  fi
  "${PGENV_BIN}/psql" -h 127.0.0.1 -p "${PG_PORT}" -U "${PG_USER}" -d "${PG_DB}" \
    -c "CREATE EXTENSION IF NOT EXISTS postgis" >> "${PG_LOG}" 2>&1
  log "pg: ready (postgresql://127.0.0.1:${PG_PORT}/${PG_DB}, postgis enabled)"
}

# ---------------------------------------------------------------------------
# api — FastAPI backend on 127.0.0.1:3030
# ---------------------------------------------------------------------------
api_ok() { http_ok "http://127.0.0.1:${API_PORT}/api/v1/health"; }

uvicorn_bin() {
  if [ -x "${API_VENV}/bin/uvicorn" ]; then
    echo "${API_VENV}/bin/uvicorn"
  elif [ -x "${API_DIR}/.venv/bin/uvicorn" ]; then
    echo "${API_DIR}/.venv/bin/uvicorn"
  else
    echo ""
  fi
}

ensure_api() {
  if api_ok; then
    log "api: healthy on :${API_PORT}"
    return 0
  fi
  local uv
  uv="$(uvicorn_bin)"
  if [ -z "${uv}" ]; then
    log "api: no uvicorn found (expected ${API_VENV}/bin/uvicorn or ${API_DIR}/.venv/bin/uvicorn)."
    log "api: create the venv and install pinned deps first:"
    log "api:   python3 -m venv ${API_VENV} && ${API_VENV}/bin/pip install -r ${API_DIR}/requirements.txt"
    return 1
  fi
  log "api: starting via daemonize.py (uvicorn app.main:app on :${API_PORT})"
  python3 "${DAEMONIZE}" sh -c \
    "cd '${API_DIR}' && exec '${uv}' app.main:app --host 127.0.0.1 --port ${API_PORT} >> '${API_LOG}' 2>&1"
  for _ in $(seq 1 30); do
    if api_ok; then log "api: healthy on :${API_PORT}"; return 0; fi
    sleep 1
  done
  log "api: did not become healthy within 30s — see ${API_LOG}"
  return 1
}

# ---------------------------------------------------------------------------
# web — Next.js on :3000
# ---------------------------------------------------------------------------
web_ok() { http_ok "http://127.0.0.1:${WEB_PORT}/"; }

ensure_web() {
  if web_ok; then
    log "web: answering on :${WEB_PORT}"
    return 0
  fi
  if [ -f "${STANDALONE_SERVER}" ]; then
    log "web: starting standalone server via daemonize.py"
    local web_root
    web_root="$(dirname "$(dirname "$(dirname "${STANDALONE_SERVER}")")")"  # .next/standalone -> repo root of the build
    python3 "${DAEMONIZE}" env PORT="${WEB_PORT}" HOSTNAME=0.0.0.0 NODE_ENV=production \
      sh -c "cd '${web_root}' && exec node '${STANDALONE_SERVER}' >> '${REPO_ROOT}/fieldshift-web.log' 2>&1"
    for _ in $(seq 1 30); do
      if web_ok; then log "web: healthy on :${WEB_PORT}"; return 0; fi
      sleep 1
    done
    log "web: did not become healthy within 30s — see ${REPO_ROOT}/fieldshift-web.log"
    return 1
  fi
  log "web: nothing on :${WEB_PORT} and ${STANDALONE_SERVER} does not exist."
  log "web: only the dev-server path is available in this checkout — start it with:"
  log "web:   cd ${REPO_ROOT} && bun run dev"
  return 0
}

# ---------------------------------------------------------------------------
# rebuild — rebuild the user-space toolchain (documented at the top of file)
# ---------------------------------------------------------------------------
rebuild() {
  local micromamba="${REPO_ROOT}/db/bin/micromamba"
  [ -x "${micromamba}" ] || micromamba="micromamba"
  export MAMBA_ROOT_PREFIX="${PG_ROOT}/mamba-root"
  if [ ! -x "${PGENV_BIN}/pg_ctl" ]; then
    log "rebuild: creating postgresql=16.10 postgis=3.5.0 env at ${PG_ROOT}/pgenv"
    "${micromamba}" create -y -p "${PG_ROOT}/pgenv" -c conda-forge \
      postgresql=16.10 postgis=3.5.0
  else
    log "rebuild: pgenv already present, skipping micromamba create"
  fi
  mkdir -p "${PG_ROOT}"
  if [ ! -d "${PGDATA}" ]; then
    log "rebuild: initdb at ${PGDATA}"
    "${PGENV_BIN}/initdb" -D "${PGDATA}" -U "${PG_USER}" -E UTF8
  else
    log "rebuild: ${PGDATA} already exists, skipping initdb"
  fi
  log "rebuild: ensure_db.py (start cluster, create ${PG_DB}, enable postgis)"
  ( cd "${API_DIR}" && FIELDSHIFT_DB_PGDATA="${PGDATA}" python3 scripts/ensure_db.py )
  if [ ! -x "${API_VENV}/bin/python" ]; then
    log "rebuild: creating API virtualenv at ${API_VENV}"
    python3 -m venv "${API_VENV}"
  fi
  log "rebuild: pip install -r requirements.txt"
  "${API_VENV}/bin/pip" install --no-cache-dir -r "${API_DIR}/requirements.txt"
  log "rebuild: alembic upgrade head"
  ( cd "${API_DIR}" && FIELDSHIFT_DATABASE_URL="postgresql+psycopg2://${PG_USER}@127.0.0.1:${PG_PORT}/${PG_DB}" \
      "${API_VENV}/bin/alembic" upgrade head )
  log "rebuild: done — now run 'scripts/start-stack.sh all'"
}

# ---------------------------------------------------------------------------
# entrypoint
# ---------------------------------------------------------------------------
cmd="${1:-all}"
case "${cmd}" in
  pg)      ensure_pg ;;
  api)     ensure_api ;;
  web)     ensure_web ;;
  all)     ensure_pg; ensure_api; ensure_web ;;
  rebuild) rebuild ;;
  *)
    printf 'Usage: %s pg|api|web|all|rebuild\n' "$0"
    exit 2
    ;;
esac

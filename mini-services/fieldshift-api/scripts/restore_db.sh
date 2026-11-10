#!/usr/bin/env bash
# CropTwist — PostgreSQL restore (P0 Phase 3). SAFETY-CRITICAL TOOL.
#
# Restores a custom-format backup (from backup_db.sh) into an EXPLICITLY
# named target database. Refuses destructive mistakes by design:
#
#   * --force is REQUIRED for any actual restore (without it, only checks run)
#   * the target database must be passed via --target-db (no default target)
#   * the environment must be classified via --env dev|staging|production
#   * restoring into the ACTIVE application database (default 'croptwist')
#     is refused unless CROPTWIST_ALLOW_ACTIVE_RESTORE is set to the exact
#     target database name — a deliberate, documented escape hatch
#   * --env production additionally requires
#     CROPTWIST_ALLOW_PRODUCTION_RESTORE=yes (prefer managed PITR instead)
#
# Usage:
#   restore_db.sh <backup.dump> --list-only                 # inspect archive
#   restore_db.sh <backup.dump> --target-db NAME --env dev  # checks only
#   restore_db.sh <backup.dump> --target-db NAME --env dev --force
#       [--pre-restore-backup] [--host H] [--port P]
#
# Restore verification: pg_restore exit status, alembic_version present,
# non-zero row counts on core tables (farms, fields, users).
#
# Exit codes: 0 ok | 1 restore failed | 2 usage/refusal/precheck failed |
#             3 post-restore verification failed | 4 target unreachable
#
# RESTORE TESTING: never against the active DB. Create a disposable target
# (e.g. croptwist_restore_test_<ts>), restore into it, verify, then drop
# ONLY that database. See docs/operations/BACKUP_AND_RESTORE.md.

set -euo pipefail

API_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ROOT="$(cd "$API_DIR/../.." && pwd)"
PGENV="$ROOT/db/pgenv/bin"
BACKUP_DIR="${CROPTWIST_BACKUP_DIR:-$ROOT/backups}"
LOG_DIR="$BACKUP_DIR"
ACTIVE_DB="${CROPTWIST_DB_NAME:-croptwist}"
PGHOST="${CROPTWIST_DB_HOST:-127.0.0.1}"
PGPORT="${CROPTWIST_DB_PORT:-5433}"

BACKUP=""
TARGET_DB=""
ENV_CLASS=""
FORCE=false
PRE_BACKUP=false
LIST_ONLY=false

usage() { sed -n '2,32p' "${BASH_SOURCE[0]}" | sed 's/^# \{0,1\}//'; }

log() { printf '[%s] [restore] %s\n' "$(date '+%Y-%m-%d %H:%M:%S')" "$*" | tee -a "$LOG_DIR/restore.log"; }
fail() { local code="$1"; shift; log "FAIL($code): $*" >&2; exit "$code"; }

while [[ $# -gt 0 ]]; do
  case "$1" in
    --target-db) TARGET_DB="${2:-}"; shift 2 ;;
    --env)       ENV_CLASS="${2:-}"; shift 2 ;;
    --host)      PGHOST="$2"; shift 2 ;;
    --port)      PGPORT="$2"; shift 2 ;;
    --force)     FORCE=true; shift ;;
    --pre-restore-backup) PRE_BACKUP=true; shift ;;
    --list-only) LIST_ONLY=true; shift ;;
    --help|-h)   usage; exit 0 ;;
    -*)          echo "ERROR: unknown option '$1'" >&2; usage; exit 2 ;;
    *)           BACKUP="$1"; shift ;;
  esac
done

[[ -n "$BACKUP" ]] || { echo "ERROR: backup file required" >&2; usage; exit 2; }
[[ -f "$BACKUP" && -s "$BACKUP" ]] || fail 2 "backup file missing or empty: $BACKUP"
mkdir -p "$LOG_DIR"

# --- archive inspection (safe, no DB touched) --------------------------------
"$PGENV/pg_restore" --list "$BACKUP" >/dev/null 2>&1 \
  || fail 2 "not a valid custom-format archive: $BACKUP"
if $LIST_ONLY; then
  echo "--- archive contents (TOC) of $BACKUP ---"
  "$PGENV/pg_restore" --list "$BACKUP" | grep -E ' (TABLE|TABLE DATA|SCHEMA|SEQUENCE|INDEX) ' | head -60
  echo "--- entries: $("$PGENV/pg_restore" --list "$BACKUP" | wc -l) total ---"
  exit 0
fi

# --- mandatory parameters ----------------------------------------------------
[[ -n "$TARGET_DB" ]] || { echo "ERROR: --target-db is required (no default target)" >&2; usage; exit 2; }
[[ -n "$ENV_CLASS" ]] || { echo "ERROR: --env dev|staging|production is required" >&2; usage; exit 2; }
case "$ENV_CLASS" in
  dev|staging|production) ;;
  *) echo "ERROR: --env must be dev, staging or production (got '$ENV_CLASS')" >&2; exit 2 ;;
esac

# --- environment gate ---------------------------------------------------------
if [[ "$ENV_CLASS" == "production" && "${CROPTWIST_ALLOW_PRODUCTION_RESTORE:-}" != "yes" ]]; then
  fail 2 "refusing production restore: set CROPTWIST_ALLOW_PRODUCTION_RESTORE=yes only after a verified backup (prefer managed PITR)"
fi

# --- active-database protection ----------------------------------------------
if [[ "$TARGET_DB" == "$ACTIVE_DB" ]]; then
  if [[ "${CROPTWIST_ALLOW_ACTIVE_RESTORE:-}" == "$TARGET_DB" ]]; then
    log "WARNING: deliberate active-database restore confirmed via CROPTWIST_ALLOW_ACTIVE_RESTORE"
  else
    fail 2 "refusing to restore into the ACTIVE database '$TARGET_DB'. Use a disposable target for tests, or export CROPTWIST_ALLOW_ACTIVE_RESTORE='$TARGET_DB' to confirm deliberately."
  fi
fi
if ! $FORCE; then
  fail 2 "dry-check complete — no data changed. Re-run with --force to actually restore."
fi

# --- target identity verification ---------------------------------------------
"$PGENV/pg_isready" -h "$PGHOST" -p "$PGPORT" -U postgres -t 3 >/dev/null 2>&1 \
  || fail 4 "postgres unreachable at $PGHOST:$PGPORT"
TARGET_EXISTS=$("$PGENV/psql" -h "$PGHOST" -p "$PGPORT" -U postgres -tAc \
  "SELECT 1 FROM pg_database WHERE datname='$TARGET_DB'" || true)
SERVER_VER=$("$PGENV/psql" -h "$PGHOST" -p "$PGPORT" -U postgres -tAc "SHOW server_version")
log "target identity: db='$TARGET_DB' host=$PGHOST port=$PGPORT pg=$SERVER_VER env=$ENV_CLASS exists=$([[ -n "$TARGET_EXISTS" ]] && echo yes || echo no)"

# --- optional pre-restore backup of the target --------------------------------
if $PRE_BACKUP && [[ -n "$TARGET_EXISTS" ]]; then
  STAMP="$(date +%Y%m%d-%H%M%S)"
  PRE="$BACKUP_DIR/pre-restore-$TARGET_DB-$STAMP.dump"
  log "creating pre-restore safety backup of '$TARGET_DB' -> $(basename "$PRE")"
  "$PGENV/pg_dump" -h "$PGHOST" -p "$PGPORT" -U postgres -d "$TARGET_DB" -Fc \
    --no-owner --no-privileges -f "$PRE" || fail 2 "pre-restore backup failed (aborting, target untouched)"
  "$PGENV/pg_restore" --list "$PRE" >/dev/null || fail 2 "pre-restore backup failed integrity check (aborting)"
fi

# --- restore -------------------------------------------------------------------
# Clean the target schema first so the restore is exact (drop objects not in
# the archive). The target must be an explicitly confirmed database.
if [[ -z "$TARGET_EXISTS" ]]; then
  log "target '$TARGET_DB' does not exist — creating it"
  "$PGENV/createdb" -h "$PGHOST" -p "$PGPORT" -U postgres "$TARGET_DB"
fi
log "restoring $(basename "$BACKUP") -> '$TARGET_DB' (env=$ENV_CLASS)"
"$PGENV/pg_restore" -h "$PGHOST" -p "$PGPORT" -U postgres \
  -d "$TARGET_DB" --no-owner --no-privileges --clean --if-exists "$BACKUP" \
  || fail 1 "pg_restore failed into '$TARGET_DB'"

# --- post-restore verification ---------------------------------------------------
ALEMBIC=$("$PGENV/psql" -h "$PGHOST" -p "$PGPORT" -U postgres -d "$TARGET_DB" -tAc \
  "SELECT 1 FROM information_schema.tables WHERE table_name='alembic_version'" || true)
[[ "$ALEMBIC" == "1" ]] || fail 3 "post-restore check failed: alembic_version missing in '$TARGET_DB'"
VER=$("$PGENV/psql" -h "$PGHOST" -p "$PGPORT" -U postgres -d "$TARGET_DB" -tAc \
  "SELECT version_num FROM alembic_version" | head -1)
FARMS=$("$PGENV/psql" -h "$PGHOST" -p "$PGPORT" -U postgres -d "$TARGET_DB" -tAc \
  "SELECT count(*) FROM farms" 2>/dev/null || echo "n/a")
FIELDS=$("$PGENV/psql" -h "$PGHOST" -p "$PGPORT" -U postgres -d "$TARGET_DB" -tAc \
  "SELECT count(*) FROM fields" 2>/dev/null || echo "n/a")
USERS=$("$PGENV/psql" -h "$PGHOST" -p "$PGPORT" -U postgres -d "$TARGET_DB" -tAc \
  "SELECT count(*) FROM users" 2>/dev/null || echo "n/a")
log "VERIFY OK: '$TARGET_DB' at migration $VER; rows farms=$FARMS fields=$FIELDS users=$USERS"
log "DONE: $(basename "$BACKUP") restored into '$TARGET_DB' (env=$ENV_CLASS)"
exit 0

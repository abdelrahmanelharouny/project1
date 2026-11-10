#!/usr/bin/env bash
# CropTwist — PostgreSQL backup (P0 Phase 3).
#
# Creates a PostgreSQL CUSTOM-FORMAT dump (pg_dump -Fc) of the 'croptwist'
# database, verifies archive integrity with `pg_restore --list`, records a
# sha256 checksum sidecar, appends to a log, and prunes old backups
# (keep last KEEP=N, checksum sidecars pruned with their dumps).
#
#   bash scripts/backup_db.sh                      # default keep=7
#   KEEP=14 bash scripts/backup_db.sh              # custom retention
#   bash scripts/backup_db.sh --verify <file.dump> # verify an existing archive
#
# Output: $BACKUP_DIR/croptwist-<YYYYmmdd-HHMMSS>.dump (+ .sha256 sidecar)
# Log:    $BACKUP_DIR/backup.log   (never contains credentials)
#
# Exit codes: 0 ok | 1 dump failed | 2 integrity/verification failed |
#             3 checksum failed | 4 cluster unreachable after bootstrap
#
# If the cluster is down, it bootstraps postgres-only via rebuild_stack.sh
# --pg-only (binaries/init are idempotent; no API/seed work happens).
#
# NOTE: sandbox-specific defaults. Production must use managed snapshots/
# PITR (docs/architecture/deployment.md) — this script targets the local
# in-repo cluster on 127.0.0.1:5433 (trust auth; no credentials handled).

set -euo pipefail

API_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ROOT="$(cd "$API_DIR/../.." && pwd)"
DB_DIR="$ROOT/db"
PGENV="$DB_DIR/pgenv/bin"
BACKUP_DIR="${CROPTWIST_BACKUP_DIR:-$ROOT/backups}"
KEEP="${KEEP:-7}"
DBNAME="${CROPTWIST_DB_NAME:-croptwist}"
PGPORT="${CROPTWIST_DB_PORT:-5433}"
PGHOST="${CROPTWIST_DB_HOST:-127.0.0.1}"
LOG="$BACKUP_DIR/backup.log"

log() { printf '[%s] [backup] %s\n' "$(date '+%Y-%m-%d %H:%M:%S')" "$*" | tee -a "$LOG"; }
fail() { local code="$1"; shift; log "FAIL($code): $*" >&2; exit "$code"; }
trap 'fail 1 "unexpected error at line $LINENO"' ERR

mkdir -p "$BACKUP_DIR"

# --- optional mode: verify an existing archive ------------------------------
if [[ "${1:-}" == "--verify" ]]; then
  [[ -n "${2:-}" ]] || fail 2 "usage: backup_db.sh --verify <file.dump>"
  FILE="$2"
  [[ -s "$FILE" ]] || fail 2 "missing or empty file: $FILE"
  "$PGENV/pg_restore" --list "$FILE" >/dev/null 2>&1 \
    || fail 2 "archive integrity check failed (pg_restore --list): $FILE"
  log "VERIFY OK: $(basename "$FILE") ($(du -h "$FILE" | cut -f1))"
  exit 0
fi

# --- ensure the cluster is reachable; bootstrap pg-only if it is not --------
if ! "$PGENV/pg_isready" -h "$PGHOST" -p "$PGPORT" -U postgres -t 3 >/dev/null 2>&1; then
  log "postgres down on $PGHOST:$PGPORT — bootstrapping (pg-only)..."
  bash "$API_DIR/scripts/rebuild_stack.sh" --pg-only >/dev/null
fi
"$PGENV/pg_isready" -h "$PGHOST" -p "$PGPORT" -U postgres -t 3 >/dev/null 2>&1 \
  || fail 4 "postgres still unreachable after bootstrap attempt"

STAMP="$(date +%Y%m%d-%H%M%S)"
OUT="$BACKUP_DIR/croptwist-$STAMP.dump"

# --- dump (custom format: compact, pg_restore-compatible, verifiable) -------
# Direct -f output (no pipe) so pg_dump's exit status cannot be masked.
# --no-owner/--no-privileges keep the archive role-agnostic for restores.
"$PGENV/pg_dump" -h "$PGHOST" -p "$PGPORT" -U postgres \
  -d "$DBNAME" -Fc --no-owner --no-privileges -f "$OUT" \
  || fail 1 "pg_dump failed for db '$DBNAME' (no archive written)"

# --- verification chain ------------------------------------------------------
[[ -s "$OUT" ]] || fail 2 "archive is empty: $OUT"
"$PGENV/pg_restore" --list "$OUT" >/dev/null 2>&1 \
  || fail 2 "archive integrity check failed (pg_restore --list): $OUT"
TABLES=$("$PGENV/pg_restore" --list "$OUT" | grep -c ' TABLE ' || true)

# --- checksum sidecar --------------------------------------------------------
if command -v sha256sum >/dev/null 2>&1; then
  ( cd "$BACKUP_DIR" && sha256sum "$(basename "$OUT")" > "$(basename "$OUT").sha256" ) \
    || fail 3 "sha256 checksum failed"
  CHECKSUM_LINE=$(cat "$OUT.sha256")
else
  CHECKSUM_LINE="(sha256sum unavailable — skipped)"
fi

# --- retention: keep the newest $KEEP dumps (+ their checksum sidecars) ------
ls -1t "$BACKUP_DIR"/croptwist-*.dump 2>/dev/null | tail -n +$((KEEP + 1)) | while read -r old; do
  rm -f "$old" "$old.sha256"
  log "pruned $old (retention KEEP=$KEEP)"
done

SIZE=$(du -h "$OUT" | cut -f1)
COUNT=$(ls -1 "$BACKUP_DIR"/croptwist-*.dump 2>/dev/null | wc -l)
log "OK $OUT ($SIZE, $TABLES table entries, $COUNT dumps retained)"
log "    sha256: $CHECKSUM_LINE"
exit 0

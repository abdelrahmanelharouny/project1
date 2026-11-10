#!/usr/bin/env bash
# CropTwist — sandbox Postgres backup (P0 / audit E6).
#
# Dumps the local 'croptwist' database to /home/z/my-project/backups/ and
# prunes old dumps (keep last KEEP=N). Designed to be invoked by the backup
# cron job; also safe to run by hand:
#
#   bash scripts/backup_db.sh
#
# If the cluster is down, it bootstraps postgres-only via rebuild_stack.sh
# --pg-only (binaries/init are idempotent; no API/seed work happens).
#
# NOTE: sandbox-specific. Production must use managed snapshots/PITR
# (docs/architecture/deployment.md).

set -euo pipefail

API_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ROOT="$(cd "$API_DIR/../.." && pwd)"
DB_DIR="$ROOT/db"
PGENV="$DB_DIR/pgenv/bin"
BACKUP_DIR="$ROOT/backups"
KEEP=7
DBNAME="${CROPTWIST_DB_NAME:-croptwist}"
PGPORT="${CROPTWIST_DB_PORT:-5433}"
PGHOST="127.0.0.1"

mkdir -p "$BACKUP_DIR"

# --- ensure the cluster is reachable; bootstrap pg-only if it is not -------
if ! "$PGENV/pg_isready" -h "$PGHOST" -p "$PGPORT" -U postgres -t 3 >/dev/null 2>&1; then
  echo "[backup] postgres down on :$PGPORT — bootstrapping (pg-only)..."
  bash "$API_DIR/scripts/rebuild_stack.sh" --pg-only >/dev/null
fi

STAMP="$(date +%Y%m%d-%H%M%S)"
OUT="$BACKUP_DIR/croptwist-$STAMP.sql.gz"

# --- dump (custom format via plain SQL + gzip: portable, human-inspectable) -
PGPASSWORD='' "$PGENV/pg_dump" -h "$PGHOST" -p "$PGPORT" -U postgres \
  -d "$DBNAME" --no-owner --no-privileges | gzip -6 > "$OUT"

SIZE=$(du -h "$OUT" | cut -f1)

# --- integrity check: the gzip stream must decompress cleanly --------------
gzip -t "$OUT"

# --- retention: keep the newest $KEEP dumps ---------------------------------
ls -1t "$BACKUP_DIR"/croptwist-*.sql.gz 2>/dev/null | tail -n +$((KEEP + 1)) | while read -r old; do
  rm -f "$old"
  echo "[backup] pruned $old"
done

COUNT=$(ls -1 "$BACKUP_DIR"/croptwist-*.sql.gz 2>/dev/null | wc -l)
echo "[backup] OK $OUT ($SIZE, $COUNT dumps retained)"

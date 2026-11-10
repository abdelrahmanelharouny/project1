# Backup & Restore Operations

Applies to the CropTwist PostgreSQL cluster used by the FastAPI backend
(`mini-services/fieldshift-api`). Scripts:

- `mini-services/fieldshift-api/scripts/backup_db.sh`
- `mini-services/fieldshift-api/scripts/restore_db.sh`

Both are sandbox-local by default (in-repo cluster on `127.0.0.1:5433`,
trust auth, database `croptwist`). For production, use managed snapshots /
PITR instead (see `docs/architecture/deployment.md`); the restore script's
safety gates still apply conceptually.

---

## 1. Backup

### Command

```bash
bash mini-services/fieldshift-api/scripts/backup_db.sh          # keep last 7
KEEP=14 bash mini-services/fieldshift-api/scripts/backup_db.sh  # custom retention
bash mini-services/fieldshift-api/scripts/backup_db.sh --verify <file.dump>
```

### What it does

1. Ensures the cluster is reachable; if down, bootstraps postgres-only via
   `rebuild_stack.sh --pg-only` (idempotent; never touches data).
2. `pg_dump -Fc` (**PostgreSQL custom format**) into
   `<repo>/backups/croptwist-<YYYYmmdd-HHMMSS>.dump` — written directly
   with `-f` (no pipes) so a dump failure can never be masked.
3. Verification chain — the script **fails safely** and never reports
   success after a failed dump:
   - non-empty file (`-s` check),
   - archive readable (`pg_restore --list`),
   - table-entry count logged.
4. Writes a sha256 checksum sidecar `<file>.sha256`.
5. Appends to `<repo>/backups/backup.log` (timestamps, sizes, checksums —
   **never credentials**; the local cluster uses trust auth and the script
   does not handle or print any secrets).
6. Retention: prunes dumps beyond `KEEP` (default 7) **including their
   checksum sidecars**.

### Environment variables

| Variable | Default | Purpose |
|---|---|---|
| `CROPTWIST_DB_NAME` | `croptwist` | database to dump |
| `CROPTWIST_DB_PORT` | `5433` | cluster port |
| `CROPTWIST_DB_HOST` | `127.0.0.1` | cluster host |
| `CROPTWIST_BACKUP_DIR` | `<repo>/backups` | output directory |
| `KEEP` | `7` | retention count |

### Exit codes

`0` ok · `1` dump failed · `2` integrity/verification failed · `3`
checksum failed · `4` cluster unreachable after bootstrap attempt.

### Scheduling

The production-style schedule in this environment is a daily 02:00
(Africa/Cairo) backup cron job (keep-7). The cron calls exactly the
command above; the first backup of every retention window is
restore-probed (see §3).

---

## 2. Restore

`restore_db.sh` is **safety-critical**. Its gates, in order:

1. **Explicit archive** — the `.dump` path is a required argument and is
   validated (`pg_restore --list`) before anything else happens.
2. **`--list-only`** — inspect the archive TOC without touching any DB.
3. **No default target** — `--target-db NAME` is mandatory.
4. **Environment classification** — `--env dev|staging|production` is
   mandatory; `production` additionally requires
   `CROPTWIST_ALLOW_PRODUCTION_RESTORE=yes` (prefer managed PITR instead).
5. **Active-database protection** — restoring into the active app DB
   (`croptwist`) is **refused** unless
   `CROPTWIST_ALLOW_ACTIVE_RESTORE=croptwist` is exported (a deliberate,
   logged escape hatch — never an accident).
6. **Mandatory confirmation** — without `--force` the script performs all
   checks and exits 2 with "no data changed".
7. **Target identity logging** — host, port, server version, target name
   and existence are logged before the restore.
8. **Optional pre-restore backup** (`--pre-restore-backup`) — safety dump
   of the target first, integrity-checked, aborts on failure.

```bash
# checks only (no writes)
bash scripts/restore_db.sh backups/croptwist-20261110-214841.dump \
    --target-db croptwist_restore_test_p0 --env dev

# actual restore
bash scripts/restore_db.sh backups/croptwist-20261110-214841.dump \
    --target-db croptwist_restore_test_p0 --env dev --force \
    --pre-restore-backup
```

Post-restore verification: `pg_restore` exit status, `alembic_version`
present + head reported, row counts of core tables (`farms`, `fields`,
`users`). Exit codes: `0` ok · `1` restore failed · `2`
usage/refusal/precheck · `3` post-restore verification · `4` target
unreachable.

---

## 3. Restore testing procedure (verified 2026-11-10)

**Rule: restore tests use a disposable database only; the active DB is
never the target.**

```bash
cd /home/z/my-project
# 1. disposable target
./db/pgenv/bin/createdb -h 127.0.0.1 -p 5433 -U postgres croptwist_restore_test_p0
# 2. restore + verify (script logs identity, verifies alembic head + counts)
cd mini-services/fieldshift-api
bash scripts/restore_db.sh ../../backups/croptwist-<STAMP>.dump \
    --target-db croptwist_restore_test_p0 --env dev --force
# 3. representative integrity checks (compare against live db)
../../db/pgenv/bin/psql -h 127.0.0.1 -p 5433 -U postgres -d croptwist_restore_test_p0 \
    -c "SELECT count(*) FROM observations;"
# 4. cleanup — ONLY the disposable database
cd /home/z/my-project
./db/pgenv/bin/dropdb -h 127.0.0.1 -p 5433 -U postgres croptwist_restore_test_p0
```

**Last verified run** (2026-11-10, archive `croptwist-20261110-214841.dump`,
468 KB, 169 TOC entries): restore into `croptwist_restore_test_p0` →
migration `0017_ai_recommendations`; row counts identical to live
(`farms=1 fields=2 users=1 observations=3285`); farm identity string
identical. All refusal paths exercised (no-`--force`, active-DB, production
env). Disposable DB dropped afterwards; live DB and API untouched.

## 4. Known limitations

- The sandbox cluster uses **trust auth** (no passwords). The scripts
  therefore handle no credentials; production equivalents must inject
  credentials via `~/.pgpass` or env and MUST NOT print them.
- `backup_db.sh` dumps the whole `croptwist` database. There is no
  per-tenant selective restore (restore is whole-database).
- Retention is count-based, not size/time-range based.
- The daily cron keeps 7 backups ≈ 7 days of point-in-time copies; PITR
  with WAL archiving is NOT implemented locally (production requirement).
- `restore_db.sh` refuses (rather than handles) restoring into a
  different-majority-version server; dumps/restores are same-version
  (16.10) in this environment.

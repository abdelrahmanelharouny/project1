# Supabase PostgreSQL and PostGIS setup

**Status: code and local compatibility prepared; no hosted Supabase project accessed or provisioned.** Published extension availability is not evidence of an owner's actual PostgreSQL/PostGIS version. Record actual hosted versions, privileges and TLS results with the read-only probe before declaring compatibility. The checked-in Alembic graph remains unchanged at `0023_p07_field_reports`; its deferred autogeneration discrepancy is still a release gate.

## 1. Provision a fresh Free staging project

In the owner's Supabase dashboard, select an organization on the **Free** plan and confirm the two-active-project allowance. Create staging only if quota permits, with no paid compute, branch, IPv4 add-on, custom domain, PITR, trial or billing activation. Do not paste its password into this repository. Keep a separate project for production if later authorized; local disposable databases are sufficient for migration verification now. Free capacity and recovery restrictions are recorded in [FREE_TIER_LIMITS.md](FREE_TIER_LIMITS.md). [1]

Before creating application tables, turn **Enable Data API off** under the Data API integration overview. CropTwist's existing tenant/field authorization lives in FastAPI, not Supabase RLS. Automatically exposing migrated `public` tables would bypass it. Keep Data API disabled until an independently approved RLS/API plan exists; no Supabase browser SDK is required for this integration. [2]

## 2. Install PostGIS without relocating existing spatial data

On a **fresh** target, use Database → Extensions, search `postgis`, enable it in the dedicated `extensions` schema. Supabase explicitly advises against installing it in `public`. Its reference table and functions must not become an unintended Data API surface. The existing first Alembic migration issues `CREATE EXTENSION IF NOT EXISTS postgis`; pre-enabling it in `extensions` makes that a no-op and retains geometry features. [3]

If PostGIS already exists in a different schema, **stop**. Do not drop/recreate, relocate, edit `pg_extension`, or cascade-delete dependencies. Such remediation needs an owner-approved backup/recovery procedure; this task does not perform it. Never replace geometry, SRIDs, GiST indexes or geography-based area calculations with numeric coordinate shortcuts.

## 3. Separate database roles and connection modes

Use an administrative migration role only for reviewed schema operations. Create a separate login such as `croptwist_app` through a protected owner provisioning step. Give it `CONNECT` on the database, `USAGE` on `public,extensions`, application-table `SELECT,INSERT,UPDATE,DELETE`, required sequence `USAGE,SELECT`, and access to spatial functions/types and `extensions.spatial_ref_sys` as needed. Do not grant superuser, `CREATEDB`, `CREATEROLE`, schema `CREATE`, table `TRUNCATE`, or membership in the administrative role. Set matching default DML/sequence privileges **for the actual migration object owner**, not merely the currently logged-in role.

`deployment/supabase/application-role.sql` is a password-free manual provisioning template, not an automatically executed migration. Review its database/object-owner assumptions before using it.

Review the exact application object inventory before granting: do not blindly grant all privileges on Supabase's `auth` or `storage` schemas. The runtime role needs read access to `public.alembic_version` for readiness, and normal DML for the existing startup registry/knowledge/plan-catalog seeds. Verify create/alter/drop operations fail for that role in a disposable target while normal application transactions and spatial queries pass.

Use the Connect dialog's **Session pooler**, port 5432, for an IPv4-only persistent FastAPI host. Custom pooled usernames use `croptwist_app.PROJECT_REF`; copy the host, do not derive it from region. Direct PostgreSQL is IPv6 on Free. Use direct access for native migration/backup sessions where available; the session pooler is the cardless IPv4 fallback and requires an actual connection test. Do not buy IPv4 or use transaction pooler 6543: session state/search path and migration behavior have not been approved there. [4]

Configure `CROPTWIST_DATABASE_URL`, `...DATABASE_SSLMODE=verify-full`, `...DATABASE_SSLROOTCERT`, and `...DATABASE_SEARCH_PATH=public,extensions`. Download the CA from Database settings, mount it as a protected runtime file, and enable SSL enforcement in the dashboard. `sslmode=require` alone does not verify the server. Use pool size 2 and zero overflow initially; account for all API/worker/platform clients under Nano's documented 60 database connections and 200 pooler clients. [4] [5]

## 4. Read-only compatibility evidence

Use the backend virtualenv from the repository root:

```bash
mini-services/fieldshift-api/.venv/bin/python deployment/scripts/database.py probe
```

The script reads the configured target, requires verified TLS for non-disposable targets, performs read-only checks and logs no credentials. It reports PostgreSQL, installed PostGIS and extension schema, effective search path, a real SRID/spatial-area query, applied revision and database size. `deployment/supabase/verify.sql` supplies additional read-only version/TLS/permission checks; its last revision query is for an already migrated target.

Record hosted `SHOW server_version`, `PostGIS_Full_Version()`, extension version/schema, effective search path, actual SSL session and role privileges. Compare to local verification evidence in [VERIFICATION.md](VERIFICATION.md). Local PostgreSQL 16/PostGIS tests are compatibility evidence, **not** hosted Supabase-version evidence; hosted major/minor/extension versions must be measured.

## 5. Review migrations before any remote upgrade

The wrapper does not alter `migrations/env.py`, migration files, metadata registration or the deferred discrepancy. It carries validated libpq connection arguments into Alembic and escapes ConfigParser's percent interpolation at its tool boundary so URL-encoded passwords work. Never use a raw URL printed in a command/log; load values securely through environment variables.

```bash
# Read-only/offline SQL generation; use an absolute protected local output path.
mini-services/fieldshift-api/.venv/bin/python deployment/scripts/database.py \
  plan --output /tmp/croptwist-reviewed-plan.sql
```

Review the complete SQL, including historical data transformations/seeds, indexes, foreign keys and drop statements. The printed `plan_sha256` binds exact migration/tool source, target endpoint/login/database and connection options. `sql_sha256` records the review artifact separately: historical migration 0020 emits random UUIDs/timestamps, so fresh SQL seed literals vary without a source change. Store both hashes with the owner approval, base/HEAD and target ID. The full base-to-head artifact is conservative; online upgrade applies pending revisions only.

Take an encrypted off-site dump and object backup first, test restore into a disposable target, and resolve the known Alembic drift through its separate approved workstream before a release. **Explicit owner approval for the exact target, source fingerprint and data impact is required**, particularly for destructive operations. Flags are technical safeguards, not permission.

Only after that approval, the owner/operator can use:

```bash
mini-services/fieldshift-api/.venv/bin/python deployment/scripts/database.py \
  upgrade --owner-approved --approved-plan-sha256 APPROVED_SOURCE_TARGET_HASH
```

There is no reset, downgrade, stamp or destructive restore command in this tooling. Never apply remote migrations as an API startup command. No remote upgrade was run here.

For local verification only, use a loopback database named `croptwist_deploy_*`, provision PostGIS in `extensions`, generate the plan, then run `upgrade --disposable --approved-plan-sha256 HASH`. The flag refuses non-loopback/non-disposable names. Do not use the broader pytest conftest against a hosted database: it creates/migrates test objects and has hardcoded loopback bootstrap assumptions.

## 6. Auth, storage and recovery

Keep the existing application authentication. Supabase Auth is only a documented potential verified-identity adapter, not a replacement for `Principal`, membership, role, field checks or session ownership. Keep private buckets private if future Storage work is approved. Free's 50 MB upload limit cannot be assumed compatible with existing 512 MiB raster objects, and reports currently need a separate durable artifact abstraction. Do not run these features on an ephemeral host and claim retained files. [1]

Free provides no included automatic backups or PITR. Export logical schema/data and separately back up every storage object with checksums. Validate recovery before onboarding real data. See [ROLLBACK.md](ROLLBACK.md) and [AUTH_STORAGE_WORKERS.md](AUTH_STORAGE_WORKERS.md). [6]

## References

[1]: https://supabase.com/pricing "Supabase Free Plan"
[2]: https://supabase.com/docs/guides/database/hardening-data-api "Supabase Data API Hardening"
[3]: https://supabase.com/docs/guides/database/extensions/postgis "Supabase PostGIS Extension"
[4]: https://supabase.com/docs/guides/database/connecting-to-postgres "Supabase PostgreSQL Connections and TLS"
[5]: https://supabase.com/docs/guides/platform/compute-add-ons "Supabase Nano Connection Limits"
[6]: https://supabase.com/docs/guides/platform/backups "Supabase Free Backup Guidance"

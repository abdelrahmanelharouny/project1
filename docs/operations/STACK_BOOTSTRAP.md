# Stack Bootstrap Operations

One command recovers and starts the complete CropTwist stack after a
sandbox wipe or environment rebuild:

```bash
bash mini-services/fieldshift-api/scripts/rebuild_stack.sh
```

## CLI

```bash
bash scripts/rebuild_stack.sh              # full stack: pg + api + bridge + web
bash scripts/rebuild_stack.sh --pg-only    # postgres only (used by backup cron)
bash scripts/rebuild_stack.sh --dry-run    # print the plan, change nothing
bash scripts/rebuild_stack.sh --help
```

Options combine (`--pg-only --dry-run` prints the pg-only plan).

## The 9-step playbook

| Step | Action | When it runs |
|---|---|---|
| 1 | PostgreSQL 16.10 + PostGIS 3.5.0 binaries via in-repo micromamba (`db/pgenv`) | only if `db/pgenv/bin/pg_ctl` missing |
| 2 | `initdb` cluster into `db/pgdata` | only if `PG_VERSION` missing (**never** re-inits over an existing cluster) |
| 3 | Start postgres on `127.0.0.1:5433` (socket dir `/tmp`), create `croptwist` DB + PostGIS extension | idempotent (`ensure_db.py`) |
| 4 | Python venv + pinned `requirements.txt` (`mini-services/fieldshift-api/.venv`) | only if `uvicorn` missing |
| 5 | `alembic upgrade head` | always (no-op at head) |
| 6 | Seed demo workspace (idempotent library call) | always (no-op when present) |
| 7 | Daemonize uvicorn `:3030` (`api.log`) | only if health probe fails |
| 8 | LLM bridge `bun --hot` `:3035` (`bridge.log`) | only if health probe fails |
| 9 | Frontend `next dev --webpack` `:3000` (`dev.log`) | only if health probe fails |

The script says which situation it is in for every step:
`present, skipping` (START), `missing — rebuilding` (REBUILD), always-run
migrations (MIGRATE), or first-run recovery (`no PG_VERSION — first-run
initdb`).

## Safety properties (verified)

- **No destructive operations.** There is no code path that drops a
  database, deletes `db/pgdata`, or recreates a cluster over existing
  data. `initdb` runs only on an empty data directory.
- **Idempotent.** Re-running on a healthy stack is a cheap verification
  pass (all steps report "present, skipping" and the verify section
  re-checks every service).
- **Persistent state lives inside the repo** (`db/pgdata`, `db/pgenv`,
  `.venv`, `.env`) so it survives sandbox resets; all of it is gitignored
  and none of it is required to exist for the script to rebuild it.
- **`.env` self-heals** — recreated with development defaults when missing.
- **Logs per service**: `api.log`, `bridge.log`, `dev.log` (frontend) are
  truncated at each (re)start and live next to the service. `daemonize.py
  --log` provides the double-fork survival + log redirect.

## Verified executions (2026-11-10)

1. **Full recovery from a wiped sandbox** (no `db/pgenv`, no `db/pgdata`,
   no venv, no bridge `node_modules`): completed end-to-end; final line
   `CropTwist stack OK: pg :5433, api :3030, bridge :3035, web :3000`.
   Demo login + `/farms` verified inside the script.
2. **Idempotent re-run**: steps 1–6 reported "present, skipping"; services
   were not restarted (health probes passed); stack OK again.
3. **`--dry-run`**: printed the exact plan (what is missing vs present)
   and changed nothing.

## Environment variables

| Variable | Default | Purpose |
|---|---|---|
| `CROPTWIST_DB_PORT` | `5433` | postgres port |
| `CROPTWIST_DB_HOST` | `127.0.0.1` | bind/connect host |
| `CROPTWIST_API_PORT` | `3030` | FastAPI port |
| `CROPTWIST_LLM_BRIDGE_PORT` | `3035` | bridge port (bridge itself hardcodes 3035; use for probes) |
| `CROPTWIST_WEB_PORT` | `3000` | frontend port |
| `CROPTWIST_DB_NAME` | `croptwist` | application database |
| `CROPTWIST_WEB_LOG` | `<repo>/dev.log` | frontend log |
| `CROPTWIST_API_LOG` | `<api>/api.log` | API log |
| `CROPTWIST_BRIDGE_LOG` | `<bridge>/bridge.log` | bridge log |

## Requirements

- `python3` on PATH (3.12 in this environment)
- `bun` on PATH (bridge + frontend) — checked up-front with a clear error
- micromamba binary at `db/bin/micromamba` (committed in-repo)
- Internet access on first run (conda-forge + PyPI + bun registry);
  later runs are fully offline

## Known limitations

- Sandbox/dev oriented. Production should use the Dockerfiles /
  docker-compose or a managed Postgres (`docs/architecture/deployment.md`);
  this script intentionally has no production mode.
- The frontend step runs `next dev` (development server), not a production
  build; CI builds production bundles.
- Ports are probe-checked; if a *different* process occupies a port, the
  step reports "already serving, skipping" — check the health endpoints if
  you suspect a foreign process.
- The script does not stop services; there is no `--stop`. Kill PIDs or
  `pkill -f 'uvicorn|bun --hot|next dev'` manually if needed.

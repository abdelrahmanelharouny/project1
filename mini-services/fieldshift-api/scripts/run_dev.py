"""Dev launcher: ensure postgres, run migrations, exec uvicorn --reload.

Invoked by `bun run dev` inside mini-services/fieldshift-api. Auto-restart on
file change is provided by uvicorn's watchfiles reloader.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from scripts.ensure_db import ensure_database, ensure_postgres  # noqa: E402


def main() -> None:
    ensure_postgres()
    ensure_database()

    import subprocess

    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    alembic = os.path.join(root, ".venv", "bin", "alembic")
    mig = subprocess.run([alembic, "upgrade", "head"], cwd=root)
    if mig.returncode != 0:
        raise RuntimeError("Migrations failed; not starting API.")

    uvicorn = os.path.join(root, ".venv", "bin", "uvicorn")
    os.execv(uvicorn, [
        uvicorn, "app.main:app",
        "--host", "127.0.0.1",
        "--port", os.environ.get("FIELDSHIFT_API_PORT", "3030"),
        "--reload",
    ])


if __name__ == "__main__":
    main()

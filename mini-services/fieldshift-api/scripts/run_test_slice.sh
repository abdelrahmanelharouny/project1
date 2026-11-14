#!/usr/bin/env bash
# Run integration slices only against an explicitly isolated local test DB.
# Database reset/drop is deliberately not performed by this helper.
set -euo pipefail
ROOT=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
cd "$ROOT"
PY=${CROPTWIST_TEST_PYTHON:-"$ROOT/.venv/bin/python"}
export CROPTWIST_TEST_DB_URL=${CROPTWIST_TEST_DB_URL:-postgresql+psycopg2://postgres@127.0.0.1:5433/croptwist_test}
"$PY" - <<'PY'
import os
from urllib.parse import urlsplit
url = urlsplit(os.environ['CROPTWIST_TEST_DB_URL'])
name = url.path.lstrip('/')
if (url.scheme not in {'postgresql', 'postgresql+psycopg2'}
    or url.hostname not in {'127.0.0.1', 'localhost', '::1'}
    or not name.startswith('croptwist_') or not name.endswith('test')
    or not name.replace('_', '').isalnum()):
    raise SystemExit('Refusing destructive test fixtures: select a local disposable croptwist_*test database.')
print('Isolated test DSN validated; this runner never drops databases.')
PY
exec "$PY" -m pytest "$@" -p no:cacheprovider

#!/usr/bin/env bash
# P04 verification helper: fresh test DB per slice (the sandbox overlay
# transiently exhausts inodes during truncate storms; dropping the test DB
# between slices keeps file churn bounded).
set -u
cd /home/z/my-project/mini-services/fieldshift-api
PY=.venv/bin/python
$PY - <<'EOF'
import psycopg2
conn = psycopg2.connect(host='127.0.0.1', port=5433, user='postgres', dbname='postgres')
conn.autocommit = True
cur = conn.cursor()
for attempt in range(30):
    try:
        cur.execute('DROP DATABASE IF EXISTS croptwist_test')
        break
    except psycopg2.OperationalError:
        import time; time.sleep(2)
print('fresh test db ready')
conn.close()
EOF
exec $PY -m pytest "$@" -p no:cacheprovider -q

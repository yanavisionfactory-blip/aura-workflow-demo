#!/usr/bin/env bash
set -euo pipefail
# This PostgreSQL instance exists only for the lifetime of the benchmark container.
for assurance_pg_bin in /usr/lib/postgresql/*/bin; do :; done
install -d -o postgres -g postgres /tmp/aura-live-test
runuser -u postgres -- "$assurance_pg_bin/initdb" -D /tmp/aura-live-test -A trust >/dev/null
runuser -u postgres -- "$assurance_pg_bin/pg_ctl" -D /tmp/aura-live-test -o '-h 127.0.0.1 -p 55432' -w start >/dev/null
trap 'runuser -u postgres -- "$assurance_pg_bin/pg_ctl" -D /tmp/aura-live-test -m fast stop >/dev/null' EXIT
"$assurance_pg_bin/createdb" -h 127.0.0.1 -p 55432 -U postgres aura_live_test
export AURA_TEST_POSTGRES_URL='postgresql+psycopg://postgres@127.0.0.1:55432/aura_live_test'
export DATABASE_URL="$AURA_TEST_POSTGRES_URL"
# Hard whole-process deadline; clean exit prevents restart-driven duplicate benchmarks.
set +e
timeout 1200 python -m app.load_evaluation --live --concurrency 2 --samples 30 --report /tmp/live-load-report.json
assurance_exit=$?
set -e
printf 'AURA_BENCHMARK_EXIT %s\n' "$assurance_exit"
exit 0

#!/bin/bash
# finalize_build.sh — regenerate the object-store summary and rebuild the WAR
# after integration + postprocess. Yeast-specific SQL patches (if any are found
# during the first build) get added here as numbered patch_*.sql calls BEFORE
# the summary step, the same way docker/flymine/scripts/finalize_build.sh does.
#
# Usage:
#   finalize_build              # summariseObjectStore + WAR
#   finalize_build --skip-war   # summary only
#
# Reads DB connection from /root/.intermine/yeastmine.properties.
set -euo pipefail

SKIP_WAR=0
for a in "$@"; do
    case "$a" in
        --skip-war) SKIP_WAR=1 ;;
        --help|-h) sed -n '2,12p' "$0"; exit 0 ;;
    esac
done

PROPS=${PROPS:-/root/.intermine/yeastmine.properties}
PG_HOST=$(awk -F= '/^db.production.datasource.serverName/{print $2}' "$PROPS")
PG_DB=$(awk -F= '/^db.production.datasource.databaseName/{print $2}' "$PROPS")
PG_USER=$(awk -F= '/^db.production.datasource.user/{print $2}' "$PROPS")
PG_PASS=$(awk -F= '/^db.production.datasource.password/{print $2}' "$PROPS")
PG_PORT=${PG_PORT:-5432}

if [ -z "$PG_HOST" ] || [ -z "$PG_DB" ]; then
    echo "ERROR: could not read DB connection from $PROPS" >&2
    exit 1
fi
export PGPASSWORD="$PG_PASS"
echo "==> Target DB: ${PG_DB} on ${PG_HOST}"

# --- Future: yeast-specific patch_*.sql calls go here (before summarise) ---
# HERE=$(dirname "$(readlink -f "$0")")
# psql -h "$PG_HOST" -p "$PG_PORT" -U "$PG_USER" -d "$PG_DB" -v ON_ERROR_STOP=1 -f "$HERE/patch_xxx.sql"

cd /root/yeastmine

echo "==> :webapp:summariseObjectStore"
./gradlew :webapp:summariseObjectStore --no-daemon --console=plain

if [ $SKIP_WAR -eq 1 ]; then
    echo "==> --skip-war set; not building WAR."
    exit 0
fi

echo "==> :webapp:war"
./gradlew :webapp:war --no-daemon --console=plain
echo "==> Done. WAR at /root/yeastmine/webapp/build/libs/"

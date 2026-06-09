#!/bin/bash
# finalize_build.sh — orchestrates the SQL fallback patches + WAR rebuild so
# the deployed UI reflects the patched DB.
#
# ============================================================================
# CRITICAL ORDERING: run the SQL patches BEFORE :dbmodel:postprocess.
# ============================================================================
# `create-attribute-indexes` (step 11 of 15 post-processes in project.xml)
# builds case-insensitive b-trees on lower(name), lower(symbol), lower(secondary
# identifier), etc. across every entity table. Each of those tables has ~6
# indexes that get rewritten by every UPDATE in the patch SQL.
#
# If the patches run AFTER `create-attribute-indexes`, every row touched (gene:
# 165K, allele: 330K, transposableelementinsertionsite: 395K, …) rewrites all
# 6+ indexes. Slow.
#
# If the patches run BEFORE `create-attribute-indexes`, the UPDATEs hit
# unindexed tables (fast) and create-attribute-indexes builds the b-trees once,
# from the patched values. No drop/recreate dance, no index thrash.
#
# Canonical operator sequence for a cold build:
#   ./project_build … <integrate phase>
#   finalize_build --sql-only          ← run the patches here
#   ./gradlew :dbmodel:postprocess     ← create-attribute-indexes sees patched data
#   finalize_build --skip-war          ← regenerate summariseObjectStore (idempotent SQL re-run)
#   ./gradlew :webapp:war              ← OR call `finalize_build` (default) which does these last two
#
# For an already-built DB (today's hot-fix path), `finalize_build` is also safe
# to run as a single command — index rewrite is cheap on 26 chromosome rows /
# small entity tables, just slow on the multi-hundred-K ones. Idempotent guards
# (`WHERE … IS NULL`) ensure re-runs are no-ops.
#
# ============================================================================
# Why a script instead of post-processes
# ============================================================================
# InterMine post-processes are Java-only and don't expose hooks for arbitrary
# SQL. Calling psql from a wrapper sidesteps that, runs in seconds, and is
# idempotent.
#
# Run inside the build container (flymine-build) so RDS creds + the patched
# image are in scope.
#
# Sequence (default mode):
#   1. patch_chromosome_names.sql       — chromosome.name/.symbol from primaryidentifier
#   2. patch_attribute_fallbacks.sql    — aberration/balancer/gene/etc. NULL-attribute fallbacks
#   3. :webapp:summariseObjectStore      — regenerate the per-class field summary
#   4. :webapp:war                       — bake summary + UI config into the WAR
#
# Usage:
#   /root/scripts/finalize_build.sh                  # full sequence
#   /root/scripts/finalize_build.sh --skip-war       # patches + summary only
#   /root/scripts/finalize_build.sh --sql-only       # patches only (use BEFORE postprocess)
#
# Env (read from /root/flymine/flymine.properties via awk):
#   RDS_HOST RDS_PORT RDS_USER RDS_PASSWORD RDS_DB_NAME

set -euo pipefail

SKIP_WAR=0
SQL_ONLY=0
for a in "$@"; do
    case "$a" in
        --skip-war) SKIP_WAR=1 ;;
        --sql-only) SQL_ONLY=1; SKIP_WAR=1 ;;
        --help|-h)  sed -n '2,25p' "$0"; exit 0 ;;
    esac
done

PROPS=${PROPS:-/root/.intermine/flymine.properties}
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
PSQL=(psql -h "$PG_HOST" -p "$PG_PORT" -U "$PG_USER" -d "$PG_DB" -v ON_ERROR_STOP=1)

HERE=$(dirname "$(readlink -f "$0")")

echo "==> 1/4 patch_chromosome_names.sql"
"${PSQL[@]}" -f "$HERE/patch_chromosome_names.sql"

echo "==> 2/4 patch_attribute_fallbacks.sql"
"${PSQL[@]}" -f "$HERE/patch_attribute_fallbacks.sql"

echo "==> 2.5/4 patch_intermineobject_blob.sql (mirror per-class patches into the serialized blob)"
"${PSQL[@]}" -f "$HERE/patch_intermineobject_blob.sql"

if [ $SQL_ONLY -eq 1 ]; then
    echo "==> --sql-only set; skipping gradle steps."
    exit 0
fi

cd /root/flymine

echo "==> 3/4 :webapp:summariseObjectStore"
./gradlew :webapp:summariseObjectStore --no-daemon --console=plain

if [ $SKIP_WAR -eq 1 ]; then
    echo "==> --skip-war set; not building WAR."
    exit 0
fi

echo "==> 4/4 :webapp:war"
./gradlew :webapp:war --no-daemon --console=plain

# ============================================
# Post-WAR patch: rewrite head.cdn.location in the packaged WAR so the
# templates.do page (and every other view that pulls JS/CSS via
# `${head.cdn.location}/...`) hits the local Caddy on multitenant rather
# than `cdn.intermine.org`. Without this the page blocks on external CDN
# fetches and can take 10+ minutes to render.
#
# The replacement target matches the ALB rule + Caddy mirror set up
# 2026-06-07: `https://flymine.alliancegenome.org/cdn/*` forwards to
# the wormmine-cdn target group (caddy on 172.31.59.87:8888) which
# already mirrors the upstream cdn.intermine.org tree.
#
# The file lives at `WEB-INF/global.web.properties` inside the WAR;
# extract just that one, sed, re-add. Python's `zipfile` ships in the
# base image (no apk install needed).
# ============================================
WAR=$(ls -t /root/flymine/webapp/build/libs/*.war 2>/dev/null | head -1)
if [ -n "$WAR" ]; then
    # ----- 4a: rewrite head.cdn.location -----
    echo "==> patching head.cdn.location in $WAR"
    python3 - "$WAR" <<'PY'
import sys, zipfile, shutil
war = sys.argv[1]
entry = "WEB-INF/global.web.properties"
with zipfile.ZipFile(war, "r") as zf:
    txt = zf.read(entry).decode("utf-8")
patched = txt.replace(
    "head.cdn.location = https://cdn.intermine.org",
    "head.cdn.location = https://flymine.alliancegenome.org/cdn",
)
if patched == txt:
    print("  no upstream cdn URL found — already patched or template changed.")
    sys.exit(0)
tmp = war + ".tmp"
with zipfile.ZipFile(war, "r") as src, zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED) as dst:
    for item in src.infolist():
        data = src.read(item.filename)
        if item.filename == entry:
            data = patched.encode("utf-8")
        dst.writestr(item, data)
shutil.move(tmp, war)
print("  head.cdn.location -> flymine.alliancegenome.org/cdn")
PY

    # ----- 4b: inject objectstoresummary.properties -----
    # `:webapp:summariseObjectStore` silently fails on Sequence.residues
    # Clob, leaving the WAR without the file the begin.do page needs.
    # gen_objectstoresummary.py hand-rolls it from raw row counts; we then
    # splice it into the WAR alongside the other WEB-INF resources so the
    # webapp finds it on classpath.
    echo "==> generating + injecting objectstoresummary.properties"
    if ! python3 -c "import psycopg2" 2>/dev/null; then
        python3 -m pip install --quiet --break-system-packages psycopg2-binary || true
    fi
    python3 "$HERE/gen_objectstoresummary.py" \
        --out /tmp/objectstoresummary.properties
    python3 - "$WAR" /tmp/objectstoresummary.properties <<'PY'
import sys, zipfile, shutil
war, src_props = sys.argv[1], sys.argv[2]
entry = "WEB-INF/objectstoresummary.properties"
with open(src_props, "rb") as fh:
    payload = fh.read()
tmp = war + ".tmp"
with zipfile.ZipFile(war, "r") as src, zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED) as dst:
    seen = False
    for item in src.infolist():
        if item.filename == entry:
            seen = True
            dst.writestr(item, payload)
        else:
            dst.writestr(item, src.read(item.filename))
    if not seen:
        dst.writestr(entry, payload)
shutil.move(tmp, war)
print(f"  injected {len(payload)} bytes -> {entry}")
PY
fi

echo "==> Done. WAR is at /root/flymine/webapp/build/libs/webapp.war"

#!/usr/bin/env bash
# weekly_build.sh — scheduled YeastMine build on the build host (AllianceMineDev).
#
# Runs Friday 22:00 America/Los_Angeles from yeastmine-weekly-build.timer. Steps:
#   1. next rc (pinned for every step), extract data, refresh stale files
#   2. project_build (integrate + postprocess) into yeastmine_<release>_rc<N>
#   3. search + autocomplete indexes into the STANDBY Solr cores (yeastmine-*-next)
#   4. object-store summary + WAR (mail fix baked in) -> data/wars/<db>.war
#   5. checks against the live build (check_build.py)
#   6. only if checks pass: publish WAR + manifest to S3; the deploy agent on the
#      multitenant host picks it up, swaps it in and verifies (deploy_agent.sh)
#   7. retention: keep the newest $KEEP rc databases, never the live one
#
# Manual run:   weekly_build.sh            (same as the timer)
#               weekly_build.sh --no-publish   build + checks only
# Status:       $WEEKLY/runs/<stamp>/build.log, status.json; s3://.../last-build-status.json
set -uo pipefail

YM_DIR=${YM_DIR:-/home/ec2-user/yeastmine-build/agr_intermine_builder/docker/yeastmine}
WEEKLY=${WEEKLY:-/home/ec2-user/yeastmine-build/weekly}
S3=${S3:-s3://agr-db-backups/yeastmine/weekly}
SOLR=${SOLR:-http://172.31.59.87:8983/solr}
KEEP=${KEEP:-4}
AMFMS=${AMFMS:-/home/ec2-user/agr_intermine_builder/docker/alliancemine/data/fms}
UA="Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36"
PUBLISH=1; [ "${1:-}" = "--no-publish" ] && PUBLISH=0

STAMP=$(date -u +%Y%m%dT%H%MZ)
RUN=$WEEKLY/runs/$STAMP; mkdir -p "$RUN"
exec > >(tee -a "$RUN/build.log") 2>&1
exec 9>"$WEEKLY/.lock"; flock -n 9 || { echo "another weekly build is running"; exit 1; }

RC=""; DB=""
say()    { echo "[$(date -u +%FT%TZ)] $*"; }
status() {  # state detail
    say "RESULT $1: $2"
    python3 -c 'import json,sys; print(json.dumps(dict(zip(["run","rc","db","state","detail","when"], sys.argv[1:]))))' \
        "$STAMP" "$RC" "$DB" "$1" "$2" "$(date -u +%FT%TZ)" > "$RUN/status.json"
    aws s3 cp --quiet "$RUN/status.json" "$S3/last-build-status.json" || say "WARN: could not write status to S3"
}
fail() { status FAILED "$1"; exit 1; }

cd "$YM_DIR" || fail "no $YM_DIR"
set -a; . ./.env; set +a
PSQL() { docker run --rm -i -e PGPASSWORD="$RDS_PASSWORD" postgres:15 \
           psql -h "$RDS_HOST" -p "${RDS_PORT:-5432}" -U "$RDS_USER" -v ON_ERROR_STOP=1 -At "$@"; }
RUNC() {  # run a command in a fresh build container with this build's pinned rc
    docker compose run --rm -T -e RC_NUMBER="$RC" "$@" yeastmine-builder "${CMD[@]}"; }

# ---- preflight --------------------------------------------------------------------------
status RUNNING "preflight"
[ -n "${MAIL_HOST:-}" ] && [ -n "${MAIL_SMTP_USER:-}" ] && [ -n "${MAIL_SERVER_PASSWORD:-}" ] \
    || fail "MAIL_* not set in $YM_DIR/.env - the WAR would ship with password reset broken"
for c in yeastmine-search-next yeastmine-autocomplete-next; do
    curl -s --max-time 30 "$SOLR/admin/cores?action=STATUS&core=$c&wt=json" | grep -q "\"name\":\"$c\"" \
        || fail "standby Solr core $c missing (run install_deploy_agent.sh on the multitenant host)"
done
[ "$(df --output=avail -k "$YM_DIR/data" | tail -1)" -gt $((20*1024*1024)) ] || fail "under 20 GB free on the build disk"
LIVE_DB=$(aws s3 cp --quiet "$S3/live.json" - 2>/dev/null | python3 -c 'import json,sys; print(json.load(sys.stdin)["db"])' 2>/dev/null)
[ -n "$LIVE_DB" ] || fail "cannot read $S3/live.json (written by the deploy agent install)"
REL_S=$(echo "$YEASTMINE_RELEASE" | tr '.-' '__'); PREFIX="yeastmine_${REL_S}_rc"
MAXRC=$(echo "SELECT coalesce(max(substring(datname from '_rc([0-9]+)\$')::int),0) FROM pg_database WHERE datname ~ '^${PREFIX}[0-9]+\$';" | PSQL -d postgres) \
    || fail "cannot query RDS"
RC=$((MAXRC + 1)); DB="${PREFIX}${RC}"
say "release $YEASTMINE_RELEASE -> building $DB (live: $LIVE_DB)"

# ---- 1. data -----------------------------------------------------------------------------
status RUNNING "extract data"
CMD=(python3 /root/scripts/extract_data.py); RUNC || fail "extract_data failed"
D="$YM_DIR/data/intermine"
cp -f "$AMFMS/ORTHOLOGY-ALLIANCE_COMBINED.tsv" "$D/yeast_orthologs/diopt/ORTHOLOGY-ALLIANCE_COMBINED.tsv" \
    || fail "orthology refresh failed"
for o in "go-basic.obo http://purl.obolibrary.org/obo/go/go-basic.obo" \
         "goslim_yeast.obo http://current.geneontology.org/ontology/subsets/goslim_yeast.obo" \
         "psi-mi.obo http://purl.obolibrary.org/obo/mi.obo"; do
    set -- $o
    curl -sfL -A "$UA" --max-time 600 -o "$D/ontology/$1.new" "$2" && [ -s "$D/ontology/$1.new" ] \
        && head -c 200 "$D/ontology/$1.new" | grep -q "format-version" \
        && mv "$D/ontology/$1.new" "$D/ontology/$1" && say "  $1: $(stat -c %s "$D/ontology/$1") bytes" \
        || { rm -f "$D/ontology/$1.new"; fail "download of $1 failed or is not OBO"; }
done

# Release label shown in the site header: build date (US Pacific, the schedule's zone) and the
# GO release of the ontology just downloaded ("data-version: releases/2026-07-26").
BUILD_DATE=$(TZ=America/Los_Angeles date +%F)
GO_VERSION=$(grep -m1 '^data-version:' "$D/ontology/go-basic.obo" | awk '{print $2}' | awk -F/ '{print $NF}')
[ -n "$GO_VERSION" ] || fail "no data-version in go-basic.obo"
export YEASTMINE_RELEASE_LABEL="$YEASTMINE_RELEASE (built $BUILD_DATE, GO $GO_VERSION)"
say "release label: $YEASTMINE_RELEASE_LABEL"

# ---- 2. integrate + postprocess ------------------------------------------------------------
status RUNNING "project_build $DB"
CMD=(bash -c "cd /root/yeastmine && ./project_build -b -v localhost /root/data/dump/yeastmine")
RUNC 2>&1 | tee "$RUN/project_build.log"; [ "${PIPESTATUS[0]}" -eq 0 ] || fail "project_build failed (see project_build.log)"
grep -q -E "BUILD FAILED|ERROR: .*failed" "$RUN/project_build.log" && fail "project_build reported a failure"

# ---- 3. search indexes into the standby cores ---------------------------------------------
# 5.x reads the Solr URLs from resource files; point them at the -next cores in this container only.
for step in create-search-index create-autocomplete-index; do
    status RUNNING "$step -> standby core"
    CMD=(bash -c "cd /root/yeastmine \
        && sed -i -E 's#(/solr/yeastmine-search)[[:space:]]*\$#\1-next#' dbmodel/resources/keyword_search.properties \
        && sed -i -E 's#(/solr/yeastmine-autocomplete)[[:space:]]*\$#\1-next#' dbmodel/resources/objectstoresummary.config.properties \
        && grep -h solrurl dbmodel/resources/keyword_search.properties dbmodel/resources/objectstoresummary.config.properties \
        && ./gradlew postprocess -Pprocess=$step --no-daemon --console=plain")
    RUNC 2>&1 | tee "$RUN/$step.log"; [ "${PIPESTATUS[0]}" -eq 0 ] || fail "$step failed"
    grep -q "POSTPROCESS $step FAILED" "$RUN/$step.log" && fail "$step reported FAILED"
    grep -q -- "-next" "$RUN/$step.log" || fail "$step did not target the standby core"
done

# ---- 4. summary + WAR ------------------------------------------------------------------------
status RUNNING "summary + WAR"
CMD=(finalize_build); RUNC 2>&1 | tee "$RUN/finalize.log"; [ "${PIPESTATUS[0]}" -eq 0 ] || fail "finalize_build failed"
WAR="$YM_DIR/data/wars/$DB.war"; [ -s "$WAR" ] || fail "no WAR at $WAR"

# ---- 5. checks -------------------------------------------------------------------------------
status RUNNING "checks against $LIVE_DB"
COUNTS="SELECT regexp_replace(class,'^org\\.intermine\\.model\\.bio\\.',''), count(*) FROM intermineobject GROUP BY 1;"
echo "$COUNTS" | PSQL -d "$DB" -F $'\t' > "$RUN/counts_new.tsv" || fail "count query on $DB failed"
echo "$COUNTS" | PSQL -d "$LIVE_DB" -F $'\t' > "$RUN/counts_live.tsv" || fail "count query on $LIVE_DB failed"
for c in yeastmine-search yeastmine-search-next yeastmine-autocomplete yeastmine-autocomplete-next; do
    printf '%s\t%s\n' "$c" "$(curl -s --max-time 60 "$SOLR/admin/cores?action=STATUS&core=$c&wt=json" \
        | python3 -c 'import json,sys; s=json.load(sys.stdin)["status"]; print(list(s.values())[0]["index"]["numDocs"])')"
done > "$RUN/solr.tsv"
python3 "$WEEKLY/bin/check_build.py" --new "$RUN/counts_new.tsv" --live "$RUN/counts_live.tsv" \
    --solr "$RUN/solr.tsv" --war "$WAR" --db "$DB" --label "$YEASTMINE_RELEASE_LABEL" \
    --out "$RUN/checks.json" || fail "checks failed (see checks.json)"

# ---- 6. publish --------------------------------------------------------------------------------
if [ $PUBLISH -eq 1 ]; then
    status RUNNING "publish to S3"
    SHA=$(sha256sum "$WAR" | cut -d' ' -f1)
    aws s3 cp --quiet "$WAR" "$S3/builds/$DB/yeastmine.war" || fail "WAR upload failed"
    python3 - "$DB" "$RC" "$YEASTMINE_RELEASE" "$SHA" "$S3/builds/$DB/yeastmine.war" "$STAMP" "$RUN/checks.json" \
        "$YEASTMINE_RELEASE_LABEL" "$BUILD_DATE" "$GO_VERSION" > "$RUN/manifest.json" <<'PY'
import json, sys
db, rc, rel, sha, war, stamp, checks, label, build_date, go = sys.argv[1:]
print(json.dumps({"db": db, "rc": int(rc), "release": rel, "label": label, "build_date": build_date,
                  "go_version": go, "war": war, "sha256": sha, "built": stamp,
                  "checks": json.load(open(checks))}, indent=1))
PY
    aws s3 cp --quiet "$RUN/manifest.json" "$S3/builds/$DB/manifest.json" \
        && aws s3 cp --quiet "$RUN/manifest.json" "$S3/ready.json" || fail "manifest upload failed"
fi

# ---- 7. retention --------------------------------------------------------------------------------
status RUNNING "retention (keep newest $KEEP)"
echo "SELECT datname FROM pg_database WHERE datname ~ '^${PREFIX}[0-9]+(:.*)?\$' ORDER BY substring(datname from '_rc([0-9]+)')::int DESC;" \
    | PSQL -d postgres > "$RUN/rc_dbs.txt"
KEEP_LIST=$(grep -v ':' "$RUN/rc_dbs.txt" | head -"$KEEP")
while read -r d; do
    base=${d%%:*}
    if echo "$KEEP_LIST" | grep -qx "$base" || [ "$base" = "$LIVE_DB" ] || [ "$base" = "$DB" ]; then continue; fi
    say "  dropping $d"
    echo "SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname='$d'; DROP DATABASE IF EXISTS \"$d\";" \
        | PSQL -d postgres >/dev/null || say "  WARN: could not drop $d"
    rm -f "$YM_DIR/data/wars/$base.war"
    aws s3 rm --quiet --recursive "$S3/builds/$base/" || true
done < "$RUN/rc_dbs.txt"

status $([ $PUBLISH -eq 1 ] && echo PUBLISHED || echo BUILT) "$DB passed checks$([ $PUBLISH -eq 1 ] && echo '; waiting for the deploy agent')"

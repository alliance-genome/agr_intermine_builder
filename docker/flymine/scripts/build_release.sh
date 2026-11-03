#!/bin/bash
# build_release.sh - unattended FlyMine release build on the build host (run from flymine-deploy/).
# First used for v1-2026-10 (FB2026_03). Stops at the first failing step; RESUME_AT=<step> skips
# the steps before it (steps: data, xrefs, integrate, sqlpatch, postprocess, finalize).
#
#   nohup scripts/build_release.sh > build-release.log 2>&1 &
#
# Preconditions: .env has FLYMINE_RELEASE/FB_RELEASE/RC_NUMBER/COPY_PROFILE_DB=false/MAIL_*; builddb
# already ran (run_builddb_*.sh guard); chado-pg restore running or done; the per-release Solr cores
# exist on multitenant (empty).
set -uo pipefail
cd "${FLYMINE_DIR:-/home/ec2-user/flymine-deploy}" || exit 1
set -a; . ./.env; set +a
: "${FLYMINE_RELEASE:?}" "${FB_RELEASE:?}" "${RC_NUMBER:?}"
DMEL_REL=${DMEL_REL:-r6.69}
SOLR=http://172.31.59.87:8983/solr
CORE_S=flymine-search-$FLYMINE_RELEASE; CORE_A=flymine-autocomplete-$FLYMINE_RELEASE
STEPS="data xrefs integrate sqlpatch postprocess finalize"
LOGD=logs-$FLYMINE_RELEASE; mkdir -p "$LOGD"
say()  { echo "[$(date -u +%FT%TZ)] $*"; }
die()  { say "STOPPED: $*"; exit 1; }
# run_step <s>: false for steps before RESUME_AT
run_step() { local s=$1; if [ -n "${RESUME_AT:-}" ]; then for x in $STEPS; do [ "$x" = "$RESUME_AT" ] && break; [ "$x" = "$s" ] && { say "skip $s (RESUME_AT=$RESUME_AT)"; return 1; }; done; fi; return 0; }

# The image bakes .../solr/flymine-search[-autocomplete] into the dbmodel resources that the
# index post-processes and the WAR read; point them at this release's cores in each container.
SOLR_FIX="cd /root/flymine && for f in dbmodel/resources/keyword_search.properties dbmodel/resources/objectstoresummary.config.properties; do \
 sed -i -E 's#(/solr/flymine-search)[[:space:]]*\$#\\1-$FLYMINE_RELEASE#; s#(/solr/flymine-autocomplete)[[:space:]]*\$#\\1-$FLYMINE_RELEASE#' \$f; done; \
 grep -h solrurl dbmodel/resources/keyword_search.properties dbmodel/resources/objectstoresummary.config.properties"
RUNC() { docker compose run --rm -T -e FB_RELEASE="$FB_RELEASE" \
           -e SOLR_INDEX_URL="$SOLR/$CORE_S" -e SOLR_AUTOCOMPLETE_URL="$SOLR/$CORE_A" flymine-builder "$@"; }

say "FlyMine $FLYMINE_RELEASE rc$RC_NUMBER ($FB_RELEASE, dmel $DMEL_REL); Solr $CORE_S / $CORE_A"

# ---- wait for the chado restore + data fetch ---------------------------------------------------
until grep -q '^RESTORE_EXIT=' chado-restore-${FB_RELEASE,,}.log 2>/dev/null; do sleep 120; done
grep -q '^RESTORE_EXIT=0$' chado-restore-${FB_RELEASE,,}.log || die "chado restore failed ($(grep RESTORE_EXIT chado-restore-${FB_RELEASE,,}.log))"
say "chado restore done: $(docker exec chado-pg psql -U chado -d chado -Atc 'select count(*) from feature') features, $(grep -c ERROR chado-restore-${FB_RELEASE,,}.log) ERROR lines"
while docker ps --format '{{.Names}}' | grep -q flymine-extract; do sleep 60; done

if run_step data; then
    say "== data: fix layout ($FB_RELEASE)"
    FB_RELEASE=$FB_RELEASE DMEL_REL=$DMEL_REL bash scripts/fix_flymine_data.sh > "$LOGD/fix-data.log" 2>&1 || die "fix_flymine_data.sh failed"
    grep -q WARN "$LOGD/fix-data.log" && say "  fix-data warnings: $(grep -c WARN "$LOGD/fix-data.log") (see $LOGD/fix-data.log)"
fi
if run_step xrefs; then
    say "== xrefs: gene dbxrefs from chado"
    bash scripts/extract_gene_dbxrefs.sh > "$LOGD/xrefs.log" 2>&1 || die "extract_gene_dbxrefs.sh failed"
    say "  $(head -1 "$LOGD/xrefs.log")"
fi
if run_step integrate; then
    say "== integrate (29 sources)"
    RUNC env START_AT="${START_AT:-}" bash /root/data/full_integrate_v1_2026_10.sh > "$LOGD/integrate.log" 2>&1
    grep -q FULL_INTEGRATE_DONE "$LOGD/integrate.log" || die "integrate: $(grep -E 'FULL_INTEGRATE_STOPPED_AT' "$LOGD/integrate.log")"
    say "  $(grep -c '= OK' "$LOGD/integrate.log") sources OK"
fi
if run_step sqlpatch; then
    say "== SQL patches"
    RUNC /root/scripts/finalize_build.sh --sql-only > "$LOGD/sqlpatch.log" 2>&1 || die "finalize --sql-only failed"
fi
if run_step postprocess; then
    # parse the XML (a grep also picks up steps that are commented out, e.g. populate-child-features)
    PP=$(python3 -c 'import sys,xml.etree.ElementTree as E; print(" ".join(p.get("name") for p in E.parse(sys.argv[1]).getroot().iter("post-process")))' source/flymine/project.xml)
    say "  post-process steps: $PP"
    for p in $PP; do                        # one JVM per step: a single-JVM postprocess leaks RDS connections
        [ -n "${PP_START_AT:-}" ] && [ "$p" != "$PP_START_AT" ] && [ -z "${pp_go:-}" ] && { say "  skip $p"; continue; }; pp_go=1
        say "== postprocess $p"
        RUNC bash -c "$SOLR_FIX && ./gradlew :dbmodel:postprocess -Pprocess=$p --stacktrace --no-daemon --console=plain" \
            > "$LOGD/pp-$p.log" 2>&1 || die "postprocess $p failed (see $LOGD/pp-$p.log)"
        grep -q "BUILD SUCCESSFUL" "$LOGD/pp-$p.log" || die "postprocess $p: no BUILD SUCCESSFUL"
    done
fi
if run_step finalize; then
    say "== finalize (summary + WAR + objectstoresummary + mail bake)"
    # the WAR is built inside the (--rm) container; copy it to the mounted data dir or it is lost
    WARNAME=flymine-$FLYMINE_RELEASE-rc$RC_NUMBER.war
    RUNC bash -c "$SOLR_FIX && /root/scripts/finalize_build.sh && mkdir -p /root/data/wars \
        && cp /root/flymine/webapp/build/libs/webapp.war /root/data/wars/$WARNAME" > "$LOGD/finalize.log" 2>&1 || die "finalize failed"
    [ -s "data/wars/$WARNAME" ] || die "no WAR at data/wars/$WARNAME"
    say "  WAR: data/wars/$WARNAME ($(du -h "data/wars/$WARNAME" | cut -f1), sha256 $(sha256sum "data/wars/$WARNAME" | cut -c1-16))"
fi
for c in $CORE_S $CORE_A; do say "  solr $c: $(curl -s "$SOLR/admin/cores?action=STATUS&core=$c&wt=json" | python3 -c 'import json,sys; print(list(json.load(sys.stdin)["status"].values())[0]["index"]["numDocs"])') docs"; done
say "BUILD_RELEASE_DONE $FLYMINE_RELEASE rc$RC_NUMBER"

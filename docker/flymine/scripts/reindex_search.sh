#!/usr/bin/env bash
# reindex_search.sh — rebuild FlyMine's keyword search + autocomplete indexes from a given build
# into STANDBY Solr cores, so production keeps serving the old index until you swap.
#
# Run on the build host (AllianceMineDev) from the flymine deploy directory (~/flymine-deploy):
#   bash reindex_search.sh <rc-number> <standby-suffix>
#   e.g. bash reindex_search.sh 3 v1-2026-08-rc2   -> indexes flymine_<release>_rc3 into
#        flymine-search-v1-2026-08-rc2 / flymine-autocomplete-v1-2026-08-rc2
#
# Then, if the counts look right, swap the standby cores with the ones the WAR uses (atomic,
# no FlyMine restart needed; the old index stays in the standby cores for rollback):
#   S=http://172.31.59.87:8983/solr
#   for k in search autocomplete; do
#     curl -s "$S/admin/cores?action=SWAP&core=flymine-$k-<live-suffix>&other=flymine-$k-<standby-suffix>"
#   done
# Roll back by running the same SWAP again.
#
# Why: switching FlyMine to a new database (rc2 -> rc3, 2026-09) without reindexing left Solr
# pointing at object ids that no longer existed, and every search failed with a 500
# (NullPointerException in SolrKeywordSearchHandler.getSearchHits). Any DB repoint needs this.
# Each post-process runs in its own JVM (a single-JVM postprocess leaks RDS connections).
set -uo pipefail
RC="${1:?rc number, e.g. 3}"
SUFFIX="${2:?standby core suffix, e.g. v1-2026-08-rc2}"
SOLR=${SOLR:-http://172.31.59.87:8983/solr}

for c in "flymine-search-$SUFFIX" "flymine-autocomplete-$SUFFIX"; do
    curl -s --max-time 30 "$SOLR/admin/cores?action=STATUS&core=$c&wt=json" | grep -q "\"name\":\"$c\"" \
        || { echo "standby core $c does not exist on $SOLR"; exit 1; }
done

LOG=reindex-rc$RC-$(date -u +%Y%m%dT%H%M).log
exec > >(tee -a "$LOG") 2>&1
for step in create-search-index create-autocomplete-index; do
    echo "=== $step $(date -u +%T)"
    docker compose run --rm -T -e RC_NUMBER="$RC" flymine-builder bash -c "cd /root/flymine \
      && sed -i -E 's#(/solr/flymine-search)[[:space:]]*\$#\1-$SUFFIX#' dbmodel/resources/keyword_search.properties \
      && sed -i -E 's#(/solr/flymine-autocomplete)[[:space:]]*\$#\1-$SUFFIX#' dbmodel/resources/objectstoresummary.config.properties \
      && grep -h solrurl dbmodel/resources/keyword_search.properties dbmodel/resources/objectstoresummary.config.properties \
      && grep '^db.production.datasource.databaseName' /root/.intermine/flymine.properties \
      && ./gradlew postprocess -Pprocess=$step --no-daemon --console=plain"
    rc=$?
    echo "=== $step exit=$rc $(date -u +%T)"
    grep -q "POSTPROCESS $step FAILED" "$LOG" && { echo "RESULT $step FAILED"; exit 1; }
    [ $rc -eq 0 ] || { echo "RESULT $step FAILED (exit $rc)"; exit 1; }
done
echo "RESULT reindex OK - compare the counts below, then SWAP (see the header of this script)"
curl -s --max-time 30 "$SOLR/admin/cores?action=STATUS&wt=json" \
    | python3 -c "import sys,json; s=json.load(sys.stdin)['status']; [print(k, s[k]['index'].get('numDocs')) for k in sorted(s) if k.startswith('flymine')]"

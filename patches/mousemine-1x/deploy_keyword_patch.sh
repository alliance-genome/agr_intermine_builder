#!/usr/bin/env bash
# deploy_keyword_patch.sh — install the keyword-index reuse patch into mousemine-1x.
# Run on the multitenant host, in a directory holding KeywordSearch.class (built from
# patches/mousemine-1x/KeywordSearch.java). See docs/MOUSEMINE_1X_KEYWORD_INDEX_FIX.md.
#
#   bash deploy_keyword_patch.sh "BLOB: 7506108"      # the stored index id (intermine_metadata
#                                                     # key 'search_directory' in the live DB)
#   bash deploy_keyword_patch.sh --rollback           # remove the patch (restart = full reload again)
#
# Steps: container memory limit 6 -> 8 GB (live), heap -Xmx6g + ExitOnOutOfMemoryError (setenv.sh),
# patched class into WEB-INF/classes (loaded before intermine-api.jar), .index-source marker for
# the index already extracted on disk, restart, verify.
set -euo pipefail
C=mousemine-1x
W=/usr/local/tomcat/webapps/mousemine
CLS=$W/WEB-INF/classes/org/intermine/api/lucene
IDX=$W/keyword_search_index
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

wait_up() {
    for i in $(seq 1 60); do
        [ "$(curl -s --max-time 10 -o /dev/null -w '%{http_code}' http://localhost:8084/mousemine/service/version || true)" = 200 ] \
            && { echo "  serving after ~$((i*5))s"; return 0; }
        sleep 5
    done
    echo "  NOT serving after 5 min"; return 1
}

if [ "${1:-}" = "--rollback" ]; then
    docker exec "$C" rm -f "$CLS/KeywordSearch.class" /usr/local/tomcat/bin/setenv.sh
    docker restart -t 60 "$C" >/dev/null; wait_up
    echo "rolled back (the next search reloads the index from the database: 2+ hours)"; exit 0
fi

SRC="${1:?usage: $0 \"BLOB: <oid>\" | --rollback}"
[ -f "$HERE/KeywordSearch.class" ] || { echo "KeywordSearch.class not found next to this script"; exit 1; }
[ "$(head -c 4 "$HERE/KeywordSearch.class" | od -An -tx1 | tr -d ' ')" = cafebabe ] || { echo "not a class file"; exit 1; }
docker exec "$C" test -f "$IDX/segments.gen" || { echo "no complete index in $IDX - do not deploy yet"; exit 1; }

echo "== 1. memory: container limit 8 GB, heap 6 GB, exit (and auto-restart) on OutOfMemoryError"
docker update --memory 8g --memory-swap 8g "$C" >/dev/null
docker exec "$C" bash -c 'printf "%s\n" "# AGR: larger heap for the 6.5 GB keyword index; exit on OOM so --restart unless-stopped recovers" "CATALINA_OPTS=\"\$CATALINA_OPTS -Xmx6g -XX:+ExitOnOutOfMemoryError\"" > /usr/local/tomcat/bin/setenv.sh'

echo "== 2. patched KeywordSearch.class"
docker exec "$C" mkdir -p "$CLS"
docker cp "$HERE/KeywordSearch.class" "$C:$CLS/KeywordSearch.class"

echo "== 3. marker for the index already on disk"
docker exec "$C" bash -c "cd '$IDX' && { printf '%s\n' '$SRC'; for f in *; do [ -f \"\$f\" ] && printf '%s\t%s\n' \"\$f\" \"\$(stat -c %s \"\$f\")\"; done; } > .index-source.tmp && mv .index-source.tmp .index-source && cat .index-source"

echo "== 4. restart"
docker restart -t 60 "$C" >/dev/null
wait_up

echo "== 5. verify"
docker exec "$C" bash -c 'echo "  max heap: $(( $(jcmd 1 VM.flags | grep -o "MaxHeapSize=[0-9]*" | cut -d= -f2) / 1073741824 )) GB"'
t0=$(date +%s)
code=$(curl -s --max-time 600 -o /tmp/kw_search.json -w '%{http_code}' 'http://localhost:8084/mousemine/service/search?q=Pax6&size=1' || true)
echo "  first search: HTTP $code after $(( $(date +%s) - t0 ))s; totalHits=$(grep -o '"totalHits":[0-9]*' /tmp/kw_search.json | cut -d: -f2)"
docker exec "$C" bash -c "grep -E 'Reusing search index|extracting|Deleting old file' /usr/local/tomcat/intermine.log | tail -3"
rm -f /tmp/kw_search.json

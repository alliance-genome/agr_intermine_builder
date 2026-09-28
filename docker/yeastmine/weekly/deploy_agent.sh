#!/usr/bin/env bash
# deploy_agent.sh — puts a new weekly YeastMine build into production on the multitenant host.
#
# Runs every 30 min from yeastmine-deploy.timer and does nothing unless S3 has a build newer
# than the live one ($S3/ready.json vs $S3/live.json). For a new build:
#   1. download the WAR, check its sha256 and that it points at the new database
#   2. keep the current WAR as the rollback copy
#   3. SWAP the Solr cores (standby -next <-> live; atomic, the old index stays in -next)
#   4. replace the WAR in place (bind-mounted file, same inode), drop the exploded dir, restart
#   5. verify the site; on any failure restore WAR + cores, restart, and never retry that build
# Writes $S3/live.json on success and $S3/last-deploy-status.json either way.
#
# Manual:  deploy_agent.sh             (same as the timer)
#          deploy_agent.sh --rollback  put the previous build back (WAR + Solr cores)
set -uo pipefail

S3=${S3:-s3://agr-db-backups/yeastmine/weekly}
STATE=${STATE:-/home/ec2-user/yeastmine-deploy}
CONTAINER=${CONTAINER:-yeastmine}
PORT=${PORT:-8087}
WAR=${WAR:-/home/ec2-user/mine-wars/yeastmine.war}
SOLR=${SOLR:-http://localhost:8983/solr}
mkdir -p "$STATE/logs"
exec >>"$STATE/logs/deploy-$(date -u +%Y%m).log" 2>&1
exec 9>"$STATE/.lock"; flock -n 9 || exit 0

say() { echo "[$(date -u +%FT%TZ)] $*"; }
jget() { python3 -c 'import json,sys; print(json.load(open(sys.argv[1])).get(sys.argv[2], ""))' "$1" "$2"; }
status() {  # state db detail
    python3 -c 'import json,sys; print(json.dumps(dict(zip(["state","db","detail","when"], sys.argv[1:]))))' \
        "$1" "$2" "$3" "$(date -u +%FT%TZ)" > "$STATE/last-deploy-status.json"
    aws s3 cp --quiet "$STATE/last-deploy-status.json" "$S3/last-deploy-status.json" || true
    say "DEPLOY $1 $2: $3"
}
swap_cores() {
    for k in search autocomplete; do
        curl -sf --max-time 120 "$SOLR/admin/cores?action=SWAP&core=yeastmine-$k&other=yeastmine-$k-next&wt=json" >/dev/null \
            || { say "Solr SWAP yeastmine-$k failed"; return 1; }
    done
}
restart_with() {  # war-file
    cat "$1" > "$WAR" || return 1                 # keep the inode: the container bind-mounts this file
    docker exec "$CONTAINER" rm -rf /usr/local/tomcat/webapps/yeastmine
    docker restart -t 60 "$CONTAINER" >/dev/null
}
verify() {  # expected release (may be empty); returns 0 when the site works
    local i r
    for i in $(seq 1 60); do
        r=$(curl -s --max-time 10 "http://localhost:$PORT/yeastmine/service/version/release" || true)
        case "$r" in \"*) break;; esac; sleep 10
    done
    case "$r" in \"*) ;; *) say "verify: webapp not serving"; return 1;; esac
    [ "$(curl -s --max-time 120 -o /dev/null -w '%{http_code}' "http://localhost:$PORT/yeastmine/begin.do")" = 200 ] \
        || { say "verify: begin.do not 200"; return 1; }
    curl -s --max-time 180 "http://localhost:$PORT/yeastmine/service/search?q=ACT1&size=1" \
        | python3 -c 'import json,sys; d=json.load(sys.stdin); sys.exit(0 if d.get("wasSuccessful", True) and d.get("totalHits",0)>0 else 1)' \
        || { say "verify: keyword search failed"; return 1; }
    curl -s --max-time 120 "http://localhost:$PORT/yeastmine/service/templates?format=json" \
        | python3 -c 'import json,sys; sys.exit(0 if len(json.load(sys.stdin)["templates"])>0 else 1)' \
        || { say "verify: no templates"; return 1; }
    curl -s --max-time 300 -G "http://localhost:$PORT/yeastmine/service/query/results" --data-urlencode 'format=count' \
        --data-urlencode 'query=<query model="genomic" view="Gene.primaryIdentifier"><constraint path="Gene.organism.shortName" op="=" value="S. cerevisiae"/></query>' \
        | python3 -c 'import sys; sys.exit(0 if int(sys.stdin.read().strip() or 0) > 5000 else 1)' \
        || { say "verify: yeast gene count query failed"; return 1; }
    return 0
}

if [ "${1:-}" = "--rollback" ]; then
    [ -s "$STATE/rollback.war" ] || { say "no rollback.war"; exit 1; }
    swap_cores && restart_with "$STATE/rollback.war" && verify \
        && { cp -f "$STATE/previous-live.json" "$STATE/live.json" 2>/dev/null; aws s3 cp --quiet "$STATE/live.json" "$S3/live.json"; status ROLLED_BACK "$(jget "$STATE/live.json" db)" "manual rollback"; exit 0; }
    status ROLLBACK_FAILED "" "manual rollback did not verify - check the container"; exit 1
fi

aws s3 cp --quiet "$S3/ready.json" "$STATE/ready.json" 2>/dev/null || exit 0
aws s3 cp --quiet "$S3/live.json" "$STATE/live.json" 2>/dev/null || { say "no live.json"; exit 1; }
NEW=$(jget "$STATE/ready.json" db); LIVE=$(jget "$STATE/live.json" db)
[ -n "$NEW" ] && [ "$NEW" != "$LIVE" ] || exit 0
[ -f "$STATE/failed-$NEW" ] && exit 0
[ "$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["checks"]["ok"])' "$STATE/ready.json")" = True ] \
    || { status SKIPPED "$NEW" "build did not pass its checks"; touch "$STATE/failed-$NEW"; exit 1; }

say "=== deploying $NEW (live: $LIVE)"
status DEPLOYING "$NEW" "downloading"
aws s3 cp --quiet "$(jget "$STATE/ready.json" war)" "$STATE/new.war" || { status FAILED "$NEW" "WAR download failed"; exit 1; }
[ "$(sha256sum "$STATE/new.war" | cut -d' ' -f1)" = "$(jget "$STATE/ready.json" sha256)" ] \
    || { status FAILED "$NEW" "WAR checksum mismatch"; touch "$STATE/failed-$NEW"; exit 1; }
python3 -c 'import sys,zipfile; print(zipfile.ZipFile(sys.argv[1]).read("WEB-INF/classes/intermine.properties").decode())' "$STATE/new.war" \
    | grep -q "^db.production.datasource.databaseName=$NEW\$" \
    || { status FAILED "$NEW" "WAR does not point at $NEW"; touch "$STATE/failed-$NEW"; exit 1; }
for c in yeastmine-search-next yeastmine-autocomplete-next; do
    curl -s --max-time 30 "$SOLR/admin/cores?action=STATUS&core=$c&wt=json" | grep -q "\"name\":\"$c\"" \
        || { status FAILED "$NEW" "standby core $c missing"; exit 1; }
done

cp -f "$WAR" "$STATE/rollback.war" && cp -f "$STATE/live.json" "$STATE/previous-live.json"
status DEPLOYING "$NEW" "swapping Solr cores + WAR, restarting $CONTAINER"
if swap_cores && restart_with "$STATE/new.war" && verify; then
    python3 -c 'import json,sys; print(json.dumps({"db": sys.argv[1], "previous": sys.argv[2], "deployed": sys.argv[3]}))' \
        "$NEW" "$LIVE" "$(date -u +%FT%TZ)" > "$STATE/live.json"
    aws s3 cp --quiet "$STATE/live.json" "$S3/live.json"
    status DEPLOYED "$NEW" "live (previous $LIVE kept for rollback: deploy_agent.sh --rollback)"
    exit 0
fi

say "deploy of $NEW failed verification - rolling back to $LIVE"
touch "$STATE/failed-$NEW"
swap_cores; restart_with "$STATE/rollback.war"
if verify; then status ROLLED_BACK "$NEW" "failed verification; $LIVE restored"
else status ROLLBACK_FAILED "$NEW" "failed verification AND rollback did not verify - check $CONTAINER now"; fi
exit 1

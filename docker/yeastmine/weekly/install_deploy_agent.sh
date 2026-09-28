#!/usr/bin/env bash
# install_deploy_agent.sh — one-time setup of the weekly YeastMine deploy on the multitenant host.
# Run on the multitenant host as ec2-user (uses sudo) from this directory:
#     bash install_deploy_agent.sh
# Idempotent. It:
#   1. creates the standby Solr cores yeastmine-search-next / yeastmine-autocomplete-next
#      (config copied from the live cores; empty until the first weekly build fills them)
#   2. records the currently live build in s3://.../live.json if none is recorded yet
#   3. installs deploy_agent.sh + the yeastmine-deploy timer (every 30 min)
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
S3=${S3:-s3://agr-db-backups/yeastmine/weekly}
SOLR=http://localhost:8983/solr
STATE=/home/ec2-user/yeastmine-deploy

echo "== 1. standby Solr cores"
for k in search autocomplete; do
    c=yeastmine-$k-next
    if curl -s "$SOLR/admin/cores?action=STATUS&core=$c&wt=json" | grep -q "\"name\":\"$c\""; then
        echo "  $c exists"; continue
    fi
    sudo test -d "/var/solr/data/yeastmine-$k/conf" || { echo "live core yeastmine-$k has no conf dir"; exit 1; }
    sudo mkdir -p "/var/solr/data/$c"
    sudo cp -a "/var/solr/data/yeastmine-$k/conf" "/var/solr/data/$c/conf"
    sudo chown -R solr:solr "/var/solr/data/$c"
    curl -sf "$SOLR/admin/cores?action=CREATE&name=$c&instanceDir=$c&wt=json" >/dev/null
    echo "  created $c"
done

echo "== 2. live build record"
if aws s3 ls "$S3/live.json" >/dev/null 2>&1; then
    echo "  $S3/live.json already present: $(aws s3 cp --quiet "$S3/live.json" -)"
else
    db=$(docker exec yeastmine grep -h '^db.production.datasource.databaseName=' \
            /usr/local/tomcat/webapps/yeastmine/WEB-INF/classes/intermine.properties | cut -d= -f2)
    [ -n "$db" ] || { echo "cannot read the live database from the yeastmine container"; exit 1; }
    printf '{"db": "%s", "previous": "", "deployed": "pre-existing (recorded %s)"}\n' "$db" "$(date -u +%FT%TZ)" \
        | aws s3 cp - "$S3/live.json"
    echo "  recorded live = $db"
fi

echo "== 3. agent + timer"
mkdir -p "$STATE"
install -m 755 "$HERE/deploy_agent.sh" "$STATE/deploy_agent.sh"
sudo install -m 644 "$HERE/systemd/yeastmine-deploy.service" "$HERE/systemd/yeastmine-deploy.timer" /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now yeastmine-deploy.timer
systemctl list-timers --no-pager yeastmine-deploy.timer
echo "done - logs in $STATE/logs/, status in $S3/last-deploy-status.json"

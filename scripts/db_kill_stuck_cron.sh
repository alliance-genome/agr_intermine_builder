#!/bin/bash
# Hourly cron job that cancels stuck queries on the alliancemine and
# wormmine production databases.
#
# Why: large WHERE id IN ($1,...,$400+) queries from the InterMine webapp
# spend 5-30s in the planner. Concurrent users pile them up, exhaust the
# pool, and the webapp serves 500s. This script clears anything still
# active after STUCK_THRESHOLD (default 5m), giving the pool room to
# recover. Real fix is webapp-side (use bag table / array param) but
# that lives upstream.
#
# Logs to /var/log/db-backup/kill-stuck-<timestamp>.log.

set -euo pipefail

REPO_DIR="${REPO_DIR:-/home/ec2-user/agr_intermine_builder_flymine}"
LOG_DIR="${LOG_DIR:-/var/log/db-backup}"
THRESHOLD="${STUCK_THRESHOLD:-5m}"

DBS=(
    alliancemine_8_3_0
    alliancemine_9_0_0_rc18
    wormmine_final
)

mkdir -p "$LOG_DIR"
LOG_FILE="$LOG_DIR/kill-stuck-$(date -u +%Y%m%dT%H%M%SZ).log"
exec >>"$LOG_FILE" 2>&1

echo "==== $(date -uIseconds) START kill-stuck (threshold=$THRESHOLD) ===="
cd "$REPO_DIR"

for db in "${DBS[@]}"; do
    echo "---- $db ----"
    python3 -m src.cli.db_admin kill-queries "$db" \
        --older-than "$THRESHOLD" --yes || \
        echo "  $db: kill-queries returned non-zero (non-fatal)"
done

echo "==== $(date -uIseconds) END kill-stuck ===="

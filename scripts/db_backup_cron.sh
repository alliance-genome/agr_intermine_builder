#!/bin/bash
# Wrapper invoked by cron on AllianceMineDev to back up RDS databases to S3.
#
# Usage:
#   db_backup_cron.sh profiles    # back up profile DBs (daily)
#   db_backup_cron.sh production  # back up production data DBs (weekly)
#
# Both invocations finish with a `backup-prune --keep-days 7`.
#
# The wrapper:
#   1. cd's into the repo (so db_admin auto-loads docker/alliancemine/.env)
#   2. logs all output to /var/log/db-backup/<group>-<date>.log
#   3. exits non-zero if any DB fails (cron will email on non-zero by default)

set -euo pipefail

GROUP="${1:?missing group: profiles | production}"
REPO_DIR="${REPO_DIR:-/home/ec2-user/agr_intermine_builder_flymine}"
LOG_DIR="${LOG_DIR:-/var/log/db-backup}"
KEEP_DAYS="${KEEP_DAYS:-7}"

PROFILE_DBS=(
    alliancemine_userprofile
    wormmine_userprofile
)
PRODUCTION_DBS=(
    alliancemine_8_3_0
    alliancemine_9_0_0_rc18
    wormmine_final
)

case "$GROUP" in
    profiles)   DBS=("${PROFILE_DBS[@]}") ;;
    production) DBS=("${PRODUCTION_DBS[@]}") ;;
    *)          echo "Unknown group: $GROUP (use profiles|production)" >&2; exit 2 ;;
esac

mkdir -p "$LOG_DIR"
LOG_FILE="$LOG_DIR/$GROUP-$(date -u +%Y%m%dT%H%M%SZ).log"
exec >>"$LOG_FILE" 2>&1

echo "==== $(date -uIseconds) START $GROUP ===="
cd "$REPO_DIR"

failed=()
for db in "${DBS[@]}"; do
    echo "---- $db ----"
    if python3 -m src.cli.db_admin backup "$db"; then
        echo "  $db: OK"
    else
        echo "  $db: FAILED"
        failed+=("$db")
    fi
done

echo "---- prune (--keep-days $KEEP_DAYS) ----"
python3 -m src.cli.db_admin backup-prune --keep-days "$KEEP_DAYS" --yes || \
    echo "  prune: FAILED (non-fatal)"

echo "==== $(date -uIseconds) END $GROUP, failed=${#failed[@]} (${failed[*]:-none}) ===="

if [ ${#failed[@]} -gt 0 ]; then
    exit 1
fi

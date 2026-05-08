#!/usr/bin/env bash
# Local backup of all InterMine profile DBs from intermine-postgres RDS.
#
# Streams pg_dump output via SSH (RDS is VPC-only — must hop through dev box)
# to ~/alliance-backups/profile/<UTC-date>/<db>.dump
#
# Usage:
#   ./backup_profile_dbs_local.sh                       # default DB set
#   ./backup_profile_dbs_local.sh -d alliancemine_userprofile,mousemine_userprofile
#   ./backup_profile_dbs_local.sh -o ~/somewhere-else
#   ./backup_profile_dbs_local.sh -v                    # verify-only (pg_restore -l)

set -euo pipefail

SSH_HOST="${SSH_HOST:-AllianceMineDev}"
RDS_HOST="${RDS_HOST:-intermine-postgres.cmnnhlso7wdi.us-east-1.rds.amazonaws.com}"
RDS_USER="${RDS_USER:-postgres}"
ENV_FILE_REMOTE="${ENV_FILE_REMOTE:-/home/ec2-user/agr_intermine_builder/docker/alliancemine/.env}"
OUT_DIR_DEFAULT="${HOME}/alliance-backups/profile/$(date -u +%Y-%m-%d)"
OUT_DIR="$OUT_DIR_DEFAULT"
DBS_DEFAULT="alliancemine_userprofile,wormmine_userprofile,mousemine_userprofile,flymine_profiles_db"
DBS="$DBS_DEFAULT"
VERIFY_ONLY=0

while getopts "d:o:vh" opt; do
  case "$opt" in
    d) DBS="$OPTARG" ;;
    o) OUT_DIR="$OPTARG" ;;
    v) VERIFY_ONLY=1 ;;
    h) sed -n '2,15p' "$0"; exit 0 ;;
    *) exit 1 ;;
  esac
done

log() { printf '[%s] %s\n' "$(date -u +%H:%M:%S)" "$*"; }

mkdir -p "$OUT_DIR"
log "Output dir: $OUT_DIR"
log "DBs: $DBS"

# Fetch RDS_PASSWORD from remote .env file (don't keep it locally)
log "Reading RDS_PASSWORD from $SSH_HOST:$ENV_FILE_REMOTE..."
RDS_PASSWORD=$(ssh "$SSH_HOST" "grep -E '^RDS_PASSWORD=' '$ENV_FILE_REMOTE' | cut -d= -f2-")
[[ -z "$RDS_PASSWORD" ]] && { echo "ERROR: could not read RDS_PASSWORD"; exit 1; }

FAILED=()
IFS=',' read -ra DB_ARRAY <<< "$DBS"

for DB in "${DB_ARRAY[@]}"; do
  DB="${DB// /}"
  OUT_FILE="${OUT_DIR}/${DB}.dump"
  log "=== $DB ==="

  if [[ $VERIFY_ONLY -eq 1 ]]; then
    [[ ! -f "$OUT_FILE" ]] && { log "  MISSING: $OUT_FILE"; FAILED+=("$DB"); continue; }
    SIZE=$(ls -lh "$OUT_FILE" | awk '{print $5}')
    if pg_restore -l "$OUT_FILE" >/dev/null 2>&1; then
      log "  OK ($SIZE) — restorable"
    else
      log "  CORRUPT ($SIZE)"
      FAILED+=("$DB")
    fi
    continue
  fi

  log "  Streaming pg_dump via $SSH_HOST..."
  # -Fc = custom format (compact, parallel-restorable, includes blobs)
  # --no-owner --no-acl = portable across PG users
  if ssh "$SSH_HOST" \
       "PGPASSWORD='${RDS_PASSWORD}' pg_dump -h '${RDS_HOST}' -U '${RDS_USER}' -d '${DB}' -Fc --no-owner --no-acl" \
       > "$OUT_FILE" 2>/tmp/pg_dump.${DB}.err
  then
    SIZE=$(ls -lh "$OUT_FILE" | awk '{print $5}')
    # Verify dump is valid (pg_restore -l reads TOC)
    if pg_restore -l "$OUT_FILE" >/dev/null 2>&1; then
      log "  OK $OUT_FILE ($SIZE)"
    else
      log "  WROTE BUT CORRUPT $OUT_FILE ($SIZE)"
      FAILED+=("$DB")
    fi
  else
    log "  FAIL — see /tmp/pg_dump.${DB}.err on local"
    rm -f "$OUT_FILE"
    FAILED+=("$DB")
  fi
done

# Summary
log "=== Summary ==="
log "OK:    $((${#DB_ARRAY[@]} - ${#FAILED[@]}))/${#DB_ARRAY[@]}"
if [[ ${#FAILED[@]} -gt 0 ]]; then
  log "FAIL:  ${FAILED[*]}"
  exit 1
fi
log "All dumps in $OUT_DIR"
log "Restore example:"
log "  pg_restore -d <target_db> --no-owner --no-acl ${OUT_DIR}/<db>.dump"

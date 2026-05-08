#!/usr/bin/env bash
# Backup all multitenant Tomcat mine containers to ECR + run-flags to S3.
#
# Captures:
#   - Container filesystem (WAR, /etc/hosts, server.xml, manager configs)
#     -> ECR repo agr_<mine>:runtime-<version>(-<stamp>)
#   - docker inspect JSON (run flags, env, port maps, mounts)
#     -> s3://agr-db-backups/runtime-snapshots/<container>/<stamp>.inspect.json
#
# Run on multitenant (172.31.59.87) where docker daemon lives.
# Discovers containers by name pattern. Override via -c.
#
# Usage:
#   ./backup_multitenant_runtimes.sh                      # all matching, push
#   ./backup_multitenant_runtimes.sh -n                   # dry-run
#   ./backup_multitenant_runtimes.sh -c alliancemine-9.0.0   # one container
#   ./backup_multitenant_runtimes.sh -p 'mousemine-*'     # custom pattern

set -euo pipefail

ECR_REGISTRY="${ECR_REGISTRY:-100225593120.dkr.ecr.us-east-1.amazonaws.com}"
AWS_REGION="${AWS_REGION:-us-east-1}"
S3_BUCKET="${S3_BUCKET:-agr-db-backups}"
S3_PREFIX="${S3_PREFIX:-runtime-snapshots}"
PATTERN="${PATTERN:-alliancemine-*|wormmine-*|mousemine-*}"
DRY_RUN=0
ONLY_CONTAINER=""

while getopts "np:c:h" opt; do
  case "$opt" in
    n) DRY_RUN=1 ;;
    p) PATTERN="$OPTARG" ;;
    c) ONLY_CONTAINER="$OPTARG" ;;
    h) sed -n '2,20p' "$0"; exit 0 ;;
    *) exit 1 ;;
  esac
done

log()  { printf '[%s] %s\n' "$(date -u +%H:%M:%S)" "$*"; }
run()  { if [[ $DRY_RUN -eq 1 ]]; then echo "DRY: $*"; else "$@"; fi; }

# Discover running containers
if [[ -n "$ONLY_CONTAINER" ]]; then
  CONTAINERS=("$ONLY_CONTAINER")
else
  mapfile -t CONTAINERS < <(docker ps --format '{{.Names}}' | grep -E "^(${PATTERN//\*/.*})$" || true)
fi

if [[ ${#CONTAINERS[@]} -eq 0 ]]; then
  log "No running containers match pattern: $PATTERN"
  exit 0
fi

log "Targets: ${CONTAINERS[*]}"

# ECR login (once)
if [[ $DRY_RUN -eq 0 ]]; then
  log "ECR login..."
  aws ecr get-login-password --region "$AWS_REGION" \
    | docker login --username AWS --password-stdin "$ECR_REGISTRY" >/dev/null
fi

STAMP=$(date -u +%Y%m%d-%H%M)
FAILED=()

for CONTAINER in "${CONTAINERS[@]}"; do
  log "=== $CONTAINER ==="

  # Derive mine + version from container name (e.g. alliancemine-9.0.0 -> mine=alliancemine, ver=9.0.0)
  MINE="${CONTAINER%%-*}"
  VERSION="${CONTAINER#${MINE}-}"
  [[ -z "$VERSION" || "$VERSION" == "$CONTAINER" ]] && VERSION="latest"
  REPO="${ECR_REGISTRY}/agr_${MINE}"
  ROLLING="${REPO}:runtime-${VERSION}"
  DATED="${REPO}:runtime-${VERSION}-${STAMP}"

  log "  -> $ROLLING + :runtime-${VERSION}-${STAMP}"

  # Skip if container not running
  STATUS=$(docker inspect -f '{{.State.Status}}' "$CONTAINER" 2>/dev/null || echo "missing")
  if [[ "$STATUS" != "running" ]]; then
    log "  SKIP: status=$STATUS"
    FAILED+=("$CONTAINER (not running)")
    continue
  fi

  # 1. Commit FS
  if ! run docker commit -m "${CONTAINER} snapshot ${STAMP}" "$CONTAINER" "$ROLLING"; then
    log "  FAIL: docker commit"
    FAILED+=("$CONTAINER (commit)")
    continue
  fi
  run docker tag "$ROLLING" "$DATED"

  # 2. Push to ECR
  if [[ $DRY_RUN -eq 0 ]]; then
    docker push "$ROLLING" || { FAILED+=("$CONTAINER (push rolling)"); continue; }
    docker push "$DATED"   || { FAILED+=("$CONTAINER (push dated)"); continue; }
  fi

  # 3. Dump run flags to S3
  INSPECT_JSON="/tmp/${CONTAINER}.${STAMP}.inspect.json"
  docker inspect "$CONTAINER" > "$INSPECT_JSON"
  S3_KEY="s3://${S3_BUCKET}/${S3_PREFIX}/${CONTAINER}/${STAMP}.inspect.json"
  if [[ $DRY_RUN -eq 0 ]]; then
    aws s3 cp "$INSPECT_JSON" "$S3_KEY" --region "$AWS_REGION" --no-progress \
      || { FAILED+=("$CONTAINER (s3)"); continue; }
  else
    echo "DRY: aws s3 cp $INSPECT_JSON $S3_KEY"
  fi
  rm -f "$INSPECT_JSON"

  log "  DONE  image=$DATED  flags=$S3_KEY"
done

# Summary
log "=== Summary ==="
log "Stamp: $STAMP"
log "OK:    $((${#CONTAINERS[@]} - ${#FAILED[@]}))/${#CONTAINERS[@]}"
if [[ ${#FAILED[@]} -gt 0 ]]; then
  log "FAIL:  ${FAILED[*]}"
  exit 1
fi

#!/usr/bin/env bash
# Restore a multitenant Tomcat mine container from ECR + S3 inspect JSON.
#
# Pulls the runtime image and replays the original docker run flags
# (port bindings, --add-host, env, mounts) recorded by
# backup_multitenant_runtimes.sh.
#
# Usage:
#   ./restore_multitenant_runtime.sh -c alliancemine-9.0.0           # latest stamp
#   ./restore_multitenant_runtime.sh -c alliancemine-9.0.0 -s 20260501-1930
#   ./restore_multitenant_runtime.sh -c alliancemine-9.0.0 -t runtime-9.0.0-20260501-1930
#   ./restore_multitenant_runtime.sh -c alliancemine-9.0.0 -n        # dry-run, print docker run

set -euo pipefail

ECR_REGISTRY="${ECR_REGISTRY:-100225593120.dkr.ecr.us-east-1.amazonaws.com}"
AWS_REGION="${AWS_REGION:-us-east-1}"
S3_BUCKET="${S3_BUCKET:-agr-db-backups}"
S3_PREFIX="${S3_PREFIX:-runtime-snapshots}"
STAMP=""
TAG=""
DRY_RUN=0
CONTAINER=""

while getopts "c:s:t:nh" opt; do
  case "$opt" in
    c) CONTAINER="$OPTARG" ;;
    s) STAMP="$OPTARG" ;;
    t) TAG="$OPTARG" ;;
    n) DRY_RUN=1 ;;
    h) sed -n '2,15p' "$0"; exit 0 ;;
    *) exit 1 ;;
  esac
done

[[ -z "$CONTAINER" ]] && { echo "ERROR: -c <container> required"; exit 1; }
command -v jq >/dev/null || { echo "ERROR: jq required"; exit 1; }

log() { printf '[%s] %s\n' "$(date -u +%H:%M:%S)" "$*"; }

# Derive mine + version from container name
MINE="${CONTAINER%%-*}"
VERSION="${CONTAINER#${MINE}-}"
REPO="${ECR_REGISTRY}/agr_${MINE}"

# Pick image tag: explicit -t, or runtime-<version>-<stamp>, or rolling runtime-<version>
if [[ -n "$TAG" ]]; then
  IMAGE="${REPO}:${TAG}"
elif [[ -n "$STAMP" ]]; then
  IMAGE="${REPO}:runtime-${VERSION}-${STAMP}"
else
  IMAGE="${REPO}:runtime-${VERSION}"
fi

# Find inspect JSON: explicit stamp, or pick latest in S3
S3_DIR="s3://${S3_BUCKET}/${S3_PREFIX}/${CONTAINER}/"
if [[ -n "$STAMP" ]]; then
  S3_KEY="${S3_DIR}${STAMP}.inspect.json"
else
  log "Finding latest inspect JSON in $S3_DIR"
  STAMP=$(aws s3 ls "$S3_DIR" --region "$AWS_REGION" \
    | awk '{print $4}' | grep '\.inspect\.json$' \
    | sort | tail -1 | sed 's/\.inspect\.json$//') || true
  [[ -z "$STAMP" ]] && { echo "ERROR: no inspect JSON found in $S3_DIR"; exit 1; }
  S3_KEY="${S3_DIR}${STAMP}.inspect.json"
fi

log "Image:   $IMAGE"
log "Flags:   $S3_KEY"

# Refuse if container with same name exists
if docker inspect "$CONTAINER" >/dev/null 2>&1; then
  echo "ERROR: container '$CONTAINER' already exists. docker rm -f $CONTAINER first."
  exit 1
fi

# Fetch inspect JSON
INSPECT_JSON=$(mktemp /tmp/${CONTAINER}.inspect.XXXX.json)
trap 'rm -f "$INSPECT_JSON"' EXIT
aws s3 cp "$S3_KEY" "$INSPECT_JSON" --region "$AWS_REGION" --no-progress >/dev/null

# Build docker run args from inspect JSON
ARGS=(docker run -d --name "$CONTAINER")

# Port bindings: -p hostPort:containerPort
while IFS=$'\t' read -r CONTAINER_PORT HOST_PORT; do
  [[ -n "$HOST_PORT" ]] && ARGS+=(-p "${HOST_PORT}:${CONTAINER_PORT%/*}")
done < <(jq -r '.[0].HostConfig.PortBindings // {} | to_entries[] | "\(.key)\t\(.value[0].HostPort)"' "$INSPECT_JSON")

# ExtraHosts: --add-host
while IFS= read -r EH; do
  [[ -n "$EH" ]] && ARGS+=(--add-host "$EH")
done < <(jq -r '.[0].HostConfig.ExtraHosts // [] | .[]' "$INSPECT_JSON")

# Env vars: -e (skip PATH, JAVA_HOME, etc baked into image)
while IFS= read -r E; do
  case "$E" in
    PATH=*|HOME=*|HOSTNAME=*|JAVA_HOME=*|LANG=*|TERM=*) ;;
    *) [[ -n "$E" ]] && ARGS+=(-e "$E") ;;
  esac
done < <(jq -r '.[0].Config.Env // [] | .[]' "$INSPECT_JSON")

# Memory limit (bytes) if set
MEM=$(jq -r '.[0].HostConfig.Memory // 0' "$INSPECT_JSON")
[[ "$MEM" -gt 0 ]] && ARGS+=(--memory "$MEM")

# Restart policy
RESTART=$(jq -r '.[0].HostConfig.RestartPolicy.Name // ""' "$INSPECT_JSON")
[[ -n "$RESTART" && "$RESTART" != "no" ]] && ARGS+=(--restart "$RESTART")

ARGS+=("$IMAGE")

# Pull image
if [[ $DRY_RUN -eq 0 ]]; then
  log "ECR login..."
  aws ecr get-login-password --region "$AWS_REGION" \
    | docker login --username AWS --password-stdin "$ECR_REGISTRY" >/dev/null
  log "Pulling $IMAGE..."
  docker pull "$IMAGE"
fi

log "Run command:"
printf '  %q ' "${ARGS[@]}"; echo

if [[ $DRY_RUN -eq 1 ]]; then
  log "DRY-RUN — not executing"
  exit 0
fi

read -r -p "Execute? [y/N] " ANS
[[ "$ANS" != "y" && "$ANS" != "Y" ]] && { log "Aborted."; exit 0; }

"${ARGS[@]}"
log "Started $CONTAINER. Verify:"
log "  docker logs -f $CONTAINER"
log "  curl -sS -o /dev/null -w '%{http_code}\\n' http://localhost:<port>/${MINE}/service/version"

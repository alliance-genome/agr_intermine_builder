#!/usr/bin/env bash
#
# build_and_push.sh — stage the operator's local YeastMine fork, build the
# Docker image with source baked in, push to ECR.
#
# Usage:
#   ./scripts/build_and_push.sh               # build + push :latest
#   ./scripts/build_and_push.sh --no-push     # build only (local smoke test)
#   ./scripts/build_and_push.sh --tag v0.1    # custom tag
#
# Env overrides:
#   YEASTMINE_SRC_DIR              — default ${HOME}/Projects/alliance/new_yeastmine/yeastmine
#   YEASTMINE_BIO_SOURCES_SRC_DIR  — default ${HOME}/Projects/alliance/new_yeastmine/yeastmine-bio-sources
#   ECR_ACCOUNT / ECR_REGION / ECR_REPO

set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SRC_MINE="${YEASTMINE_SRC_DIR:-${HOME}/Projects/alliance/new_yeastmine/yeastmine}"
SRC_BIO="${YEASTMINE_BIO_SOURCES_SRC_DIR:-${HOME}/Projects/alliance/new_yeastmine/yeastmine-bio-sources}"
ECR_ACCOUNT="${ECR_ACCOUNT:-100225593120}"
ECR_REGION="${ECR_REGION:-us-east-1}"
ECR_HOST="${ECR_ACCOUNT}.dkr.ecr.${ECR_REGION}.amazonaws.com"
ECR_REPO="${ECR_REPO:-yeastmine-builder}"

TAG="latest"
PUSH=1
while [[ $# -gt 0 ]]; do
    case "$1" in
        --tag) TAG="$2"; shift 2 ;;
        --no-push) PUSH=0; shift ;;
        --help|-h) sed -n '2,20p' "$0"; exit 0 ;;
        *) echo "unknown arg: $1" >&2; exit 2 ;;
    esac
done

for d in "$SRC_MINE" "$SRC_BIO"; do
    if [[ ! -d "$d" ]]; then
        echo "ERROR: source dir does not exist: $d"
        echo "  Set YEASTMINE_SRC_DIR + YEASTMINE_BIO_SOURCES_SRC_DIR if your fork lives elsewhere."
        exit 1
    fi
done

STAGE="${HERE}/source"
echo "==> Staging local fork into ${STAGE} (rsync, excluding build artifacts)..."
mkdir -p "${STAGE}/yeastmine" "${STAGE}/yeastmine-bio-sources"
RSYNC_EXCLUDES=(
    --exclude='.git' --exclude='.gradle' --exclude='build/'
    --exclude='bin/' --exclude='out/' --exclude='*.log'
    --exclude='intermine-*.log' --exclude='.idea/' --exclude='.vscode/'
)
rsync -a --delete "${RSYNC_EXCLUDES[@]}" "${SRC_MINE}/" "${STAGE}/yeastmine/"
rsync -a --delete "${RSYNC_EXCLUDES[@]}" "${SRC_BIO}/"  "${STAGE}/yeastmine-bio-sources/"

SRC_HASH=$(find "${STAGE}" -type f -print0 | sort -z | xargs -0 sha256sum 2>/dev/null \
    | sha256sum | cut -c1-12)
HASH_TAG="src-${SRC_HASH}"
echo "==> Source hash: ${HASH_TAG}"

PLATFORM="linux/amd64"

if [[ ${PUSH} -eq 0 ]]; then
    docker buildx build --platform "${PLATFORM}" --load \
        -t "yeastmine-builder:${TAG}" -t "yeastmine-builder:${HASH_TAG}" "${HERE}"
    echo "==> --no-push set; skipping ECR push."
    docker images yeastmine-builder --format 'table {{.Repository}}:{{.Tag}}\t{{.Size}}\t{{.CreatedAt}}' | head -5
    exit 0
fi

echo "==> ECR login (${ECR_HOST})..."
aws ecr describe-repositories --region "${ECR_REGION}" --repository-names "${ECR_REPO}" >/dev/null 2>&1 \
    || aws ecr create-repository --region "${ECR_REGION}" --repository-name "${ECR_REPO}" >/dev/null
aws ecr get-login-password --region "${ECR_REGION}" \
    | docker login --username AWS --password-stdin "${ECR_HOST}"

docker buildx build --platform "${PLATFORM}" --push \
    -t "${ECR_HOST}/${ECR_REPO}:${TAG}" -t "${ECR_HOST}/${ECR_REPO}:${HASH_TAG}" "${HERE}"

echo "==> Done. Pull on AllianceMineDev:"
echo "    docker pull ${ECR_HOST}/${ECR_REPO}:${TAG} && docker tag ${ECR_HOST}/${ECR_REPO}:${TAG} yeastmine-builder:${TAG}"

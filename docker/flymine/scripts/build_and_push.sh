#!/usr/bin/env bash
#
# build_and_push.sh — stage the operator's local FlyMine fork, build the
# Docker image with source baked in, push to ECR.
#
# Then on AllianceMineDev (or anywhere with ECR pull access):
#   aws ecr get-login-password --region us-east-1 \
#     | docker login --username AWS --password-stdin 100225593120.dkr.ecr.us-east-1.amazonaws.com
#   docker pull 100225593120.dkr.ecr.us-east-1.amazonaws.com/flymine-builder:latest
#   docker compose up -d  # or: docker compose run --rm flymine-builder bash
#
# Why this pattern (vs cloning upstream): the sibling's local fork carries EBI
# Maven URL + GO enrichment fixes plus the full-no-fluff project.xml edits that
# exist nowhere else. See docs/FLYMINE_DOCKER_HANDOFF_REPLIES_2026_05_30.md Q2.
#
# Usage:
#   ./scripts/build_and_push.sh               # build + push :latest
#   ./scripts/build_and_push.sh --no-push     # build only (local test)
#   ./scripts/build_and_push.sh --tag v0.1    # custom tag
#
# Env overrides:
#   FLYMINE_SRC_DIR                — default ${HOME}/Projects/alliance/new_flymine/flymine
#   FLYMINE_BIO_SOURCES_SRC_DIR    — default ${HOME}/Projects/alliance/new_flymine/flymine-bio-sources
#   ECR_ACCOUNT                    — default 100225593120
#   ECR_REGION                     — default us-east-1

set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SRC_FLYMINE="${FLYMINE_SRC_DIR:-${HOME}/Projects/alliance/new_flymine/flymine}"
SRC_BIO="${FLYMINE_BIO_SOURCES_SRC_DIR:-${HOME}/Projects/alliance/new_flymine/flymine-bio-sources}"
ECR_ACCOUNT="${ECR_ACCOUNT:-100225593120}"
ECR_REGION="${ECR_REGION:-us-east-1}"
ECR_HOST="${ECR_ACCOUNT}.dkr.ecr.${ECR_REGION}.amazonaws.com"
ECR_REPO="${ECR_REPO:-flymine-builder}"

TAG="latest"
PUSH=1

while [[ $# -gt 0 ]]; do
    case "$1" in
        --tag) TAG="$2"; shift 2 ;;
        --no-push) PUSH=0; shift ;;
        --help|-h)
            sed -n '2,30p' "$0"
            exit 0
            ;;
        *) echo "unknown arg: $1" >&2; exit 2 ;;
    esac
done

for d in "$SRC_FLYMINE" "$SRC_BIO"; do
    if [[ ! -d "$d" ]]; then
        echo "ERROR: source dir does not exist: $d"
        echo "  Set FLYMINE_SRC_DIR + FLYMINE_BIO_SOURCES_SRC_DIR if your local fork lives elsewhere."
        exit 1
    fi
done

STAGE="${HERE}/source"
echo "==> Staging local fork into ${STAGE} (rsync, excluding build artifacts)..."
mkdir -p "${STAGE}/flymine" "${STAGE}/flymine-bio-sources"
# Strip build / VCS / gradle daemon dirs so the image stays slim and
# nothing operator-laptop-specific sneaks in.
RSYNC_EXCLUDES=(
    --exclude='.git'
    --exclude='.gradle'
    --exclude='build/'
    --exclude='bin/'
    --exclude='out/'
    --exclude='*.log'
    --exclude='intermine-*.log'
    --exclude='.idea/'
    --exclude='.vscode/'
)
rsync -a --delete "${RSYNC_EXCLUDES[@]}" "${SRC_FLYMINE}/" "${STAGE}/flymine/"
rsync -a --delete "${RSYNC_EXCLUDES[@]}" "${SRC_BIO}/" "${STAGE}/flymine-bio-sources/"

# Tag with a content hash so re-builds against identical source resolve to
# the same image, and we can pin AllianceMineDev to a specific build.
SRC_HASH=$(find "${STAGE}" -type f -print0 | sort -z | xargs -0 sha256sum 2>/dev/null \
    | sha256sum | cut -c1-12)
HASH_TAG="src-${SRC_HASH}"
echo "==> Source hash: ${HASH_TAG}"

echo "==> Building flymine-builder:${TAG} + flymine-builder:${HASH_TAG}..."
# AllianceMineDev (the consumer) is linux/amd64; Mac build hosts are arm64.
# Use buildx so the pushed manifest is amd64 regardless of build-host arch.
# --no-push variant uses --load (single-arch) so the local daemon can run it
# for smoke tests.
PLATFORM="linux/amd64"

if [[ ${PUSH} -eq 0 ]]; then
    docker buildx build \
        --platform "${PLATFORM}" \
        --load \
        -t "flymine-builder:${TAG}" \
        -t "flymine-builder:${HASH_TAG}" \
        "${HERE}"
    echo "==> --no-push set; skipping ECR push."
    echo "Local images:"
    docker images flymine-builder --format 'table {{.Repository}}:{{.Tag}}\t{{.Size}}\t{{.CreatedAt}}' | head -5
    exit 0
fi

echo "==> ECR login (${ECR_HOST})..."
aws ecr describe-repositories --region "${ECR_REGION}" --repository-names "${ECR_REPO}" >/dev/null 2>&1 \
    || aws ecr create-repository --region "${ECR_REGION}" --repository-name "${ECR_REPO}" >/dev/null

aws ecr get-login-password --region "${ECR_REGION}" \
    | docker login --username AWS --password-stdin "${ECR_HOST}"

# Push directly from buildx (single push, native amd64 manifest).
docker buildx build \
    --platform "${PLATFORM}" \
    --push \
    -t "${ECR_HOST}/${ECR_REPO}:${TAG}" \
    -t "${ECR_HOST}/${ECR_REPO}:${HASH_TAG}" \
    "${HERE}"

echo
echo "==> Done."
echo "    Pull on AllianceMineDev:"
echo "      aws ecr get-login-password --region ${ECR_REGION} \\"
echo "        | docker login --username AWS --password-stdin ${ECR_HOST}"
echo "      docker pull ${ECR_HOST}/${ECR_REPO}:${TAG}"
echo "      docker tag ${ECR_HOST}/${ECR_REPO}:${TAG} flymine-builder:${TAG}"
echo "      cd /home/ec2-user/agr_intermine_builder/docker/flymine"
echo "      docker compose run --rm flymine-builder bash"

#!/usr/bin/env bash
# Alliance API prefetch on the build host, outside the builder container. Writes the TSVs and the
# SQLite response cache where the container's extract stage reads them (/root/data/api, api-cache),
# so a later `build` runs its API phase from cache.
#
#   tools/api_fetch/run.sh                      # all fetchers, all 9 MODs
#   tools/api_fetch/run.sh --mods SGD --only genes
#
# BIO_SOURCES      alliancemine-bio-sources checkout (default ~/intermine/alliancemine-bio-sources)
# ALLIANCE_RELEASE release to pin (default 9.2.0); fetch_all exits 2 if the API serves another one
# ALLIANCE_API_BASE API root (default https://www.alliancegenome.org/api)
set -euo pipefail
repo=$(cd "$(dirname "$0")/../.." && pwd)
data="$repo/docker/alliancemine/data"
BIO_SOURCES=${BIO_SOURCES:-$HOME/intermine/alliancemine-bio-sources}
export ALLIANCE_RELEASE=${ALLIANCE_RELEASE:-9.2.0}
export ALLIANCE_FETCH_CACHE=${ALLIANCE_FETCH_CACHE:-$data/api-cache}
export ALLIANCE_FMS_CACHE=${ALLIANCE_FMS_CACHE:-$data/fms-cache}
mkdir -p "$data/api" "$ALLIANCE_FETCH_CACHE" "$ALLIANCE_FMS_CACHE"
echo "bio-sources $(git -C "$BIO_SOURCES" rev-parse --abbrev-ref HEAD) $(git -C "$BIO_SOURCES" log --oneline -1)"
echo "release $ALLIANCE_RELEASE, API ${ALLIANCE_API_BASE:-https://www.alliancegenome.org/api}"
exec python3 "$BIO_SOURCES/scripts/fetch_all.py" --out-dir "$data/api" \
    --workers "${ALLIANCE_FETCH_WORKERS:-4}" "$@"

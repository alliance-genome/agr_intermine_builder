#!/usr/bin/env bash
# Compile local InterMine checkouts inside the builder image: every bio-source, then the merged
# model and the alliancemine webapp. No database is touched (no builddb, no integrate).
#
#   tools/model_audit/compile_check.sh            # ~/intermine/{alliancemine,alliancemine-bio-sources}
# Log: runs/compile-check-<UTC time>.log
set -euo pipefail
repo=$(cd "$(dirname "$0")/../.." && pwd)
src=${INTERMINE_SRC:-$HOME/intermine}
log="$repo/runs/compile-check-$(date -u +%Y%m%dT%H%M).log"
mkdir -p "$repo/runs"
cd "$repo/docker/alliancemine"
docker compose run --rm -T --entrypoint /bin/sh \
    -v "$src/alliancemine-bio-sources:/root/alliancemine-bio-sources" \
    -v "$src/alliancemine:/root/alliancemine" \
    -v compile-check-gradle:/root/.gradle -v compile-check-m2:/root/.m2 \
    alliancemine-builder -c '
set -e -o pipefail
envsubst < /root/.intermine/alliancemine.properties.template > /root/.intermine/alliancemine.properties
cd /root/alliancemine-bio-sources && ./gradlew --no-daemon install 2>&1 | grep -vE "^Download " | tail -40
mkdir -p /root/.gradle/daemon/4.9 && ln -sfn /root/alliancemine/dbmodel /root/.gradle/daemon/4.9/dbmodel
cd /root/alliancemine && ./gradlew --no-daemon install 2>&1 | grep -vE "^Download " | tail -40
n=$(grep -c "<class " dbmodel/build/resources/main/genomic_model.xml)
echo "MODEL_CLASSES $n"
[ "$n" -gt 0 ]
' > "$log" 2>&1 && echo "OK $log" || { echo "FAILED $log"; exit 1; }

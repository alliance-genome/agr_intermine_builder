#!/usr/bin/env bash
# AllianceMine rc build on the build host (AllianceMineDev), one step at a time or all of them.
#
#   tools/release/build_rc.sh preflight          # .env, API release, disk, RDS: no rc DB yet
#   tools/release/build_rc.sh update             # pull the 3 checkouts to their build branches
#   tools/release/build_rc.sh image              # docker compose build; cloned SHAs must match GitHub
#   tools/release/build_rc.sh fetch              # Alliance API + FMS fetchers on the host (hours to days)
#   tools/release/build_rc.sh check              # check-downloads against project.xml
#   tools/release/build_rc.sh build              # full 6-stage build into alliancemine_<rel>_rc<RC>
#   tools/release/build_rc.sh resume             # build --start-from project_build --resume (same RC)
#   tools/release/build_rc.sh verify             # SQL post-load checks on the rc database
#   tools/release/build_rc.sh all                # preflight update image fetch check build verify
#
# RC=2 is the default rc number. RELEASE defaults to ALLIANCE_RELEASE in .env (9.2.0). Every step
# logs to runs/<step>-rc<RC>-<UTC time>.log. Run long steps detached:
#   nohup tools/release/build_rc.sh all > runs/all-rc2.out 2>&1 &
set -euo pipefail

repo=$(cd "$(dirname "$0")/../.." && pwd)
builder="$repo/docker/alliancemine"
envfile="$builder/.env"
runs="$repo/runs"
src=${INTERMINE_SRC:-$HOME/intermine}
RC=${RC:-2}
AM_BRANCH=${ALLIANCEMINE_BRANCH:-im2-model-links}
BS_BRANCH=${BIO_SOURCES_BRANCH:-im2-model-links}
BUILDER_BRANCH=${BUILDER_BRANCH:-alliancemine-9.2.0.im2}
mkdir -p "$runs"

envval() { grep -E "^$1=" "$envfile" 2>/dev/null | tail -1 | cut -d= -f2- | tr -d '"' || true; }
die() { echo "FAIL: $*" >&2; exit 1; }
ts() { date -u +%Y%m%dT%H%M; }
compose() { (cd "$builder" && docker compose "$@"); }
# psql inside the builder image; the password travels by name (RDS_PASSWORD is in the container env).
rds_sql() {
    local db=$1 sql=$2
    # shellcheck disable=SC2016  # $RDS_* and $1 $2 expand inside the container shell
    compose run --rm -T --entrypoint bash alliancemine-builder -c \
        'PGPASSWORD="$RDS_PASSWORD" psql -h "$RDS_HOST" -p "${RDS_PORT:-5432}" -U "$RDS_USER" -d "$1" -v ON_ERROR_STOP=0 -tAc "$2"' \
        _ "$db" "$sql" 2>/dev/null | tr -d '\r'
}

[ -f "$envfile" ] || die "$envfile missing"
RELEASE=${RELEASE:-$(envval ALLIANCE_RELEASE)}
[ -n "$RELEASE" ] || die "ALLIANCE_RELEASE is empty in .env and RELEASE is unset"
REL_SANITIZED=${RELEASE//./_}
DB="alliancemine_${REL_SANITIZED}_rc${RC}"
API_BASE=${ALLIANCE_API_BASE:-$(envval ALLIANCE_API_BASE)}
API_BASE=${API_BASE:-https://www.alliancegenome.org/api}

step_preflight() {
    echo "host $(hostname), release $RELEASE, rc $RC, db $DB, API $API_BASE"
    echo "builder $(git -C "$repo" branch --show-current) $(git -C "$repo" rev-parse --short HEAD)"
    [ "$(envval BUILD_TYPE)" = "test" ] || die "BUILD_TYPE in .env must be test for an rc build"
    [ -z "$(envval RC_NUMBER)" ] || die "RC_NUMBER is pinned in .env; remove it, this script passes RC=$RC"
    [ -z "$(envval SOLR_INDEX_URL)" ] || die "SOLR_INDEX_URL is pinned in .env (would reindex that core); remove it"
    [ -z "$(envval SOLR_AUTOCOMPLETE_URL)" ] || die "SOLR_AUTOCOMPLETE_URL is pinned in .env; remove it"
    local api_release
    api_release=$(curl -s --max-time 30 "$API_BASE/releaseInfo" | python3 -c 'import json,sys; print(json.load(sys.stdin).get("releaseVersion",""))' 2>/dev/null || true)
    [ "$api_release" = "$RELEASE" ] || die "API $API_BASE serves release '$api_release', build wants $RELEASE"
    echo "API releaseInfo $api_release ok"
    local free
    free=$(/bin/df -BG --output=avail "$builder/data" 2>/dev/null | tail -1 | tr -dc '0-9')
    [ -n "$free" ] && [ "$free" -ge 150 ] || die "under 150 GB free on $builder/data (have ${free:-?} GB)"
    echo "disk ${free} GB free"
    if docker ps --format '{{.Names}}' | grep -qx alliancemine-builder; then
        die "container alliancemine-builder is running; a build is in progress"
    fi
    if docker image inspect alliancemine-builder:latest >/dev/null 2>&1; then
        local dbs
        dbs=$(rds_sql postgres "select datname from pg_database where datname like 'alliancemine_${REL_SANITIZED}_rc%' order by 1")
        echo "rc databases on RDS: $(echo "$dbs" | tr '\n' ' ')"
        echo "$dbs" | grep -qx "$DB" && die "$DB already exists; pick another RC or use resume"
    else
        echo "no builder image yet; the RDS check runs after the image step"
    fi
    echo "preflight ok"
}

update_checkout() {
    local dir=$1 branch=$2
    [ -d "$dir/.git" ] || die "$dir is not a git checkout"
    [ -z "$(git -C "$dir" status --porcelain --untracked-files=no)" ] || die "$dir has local changes; commit or stash them first"
    git -C "$dir" fetch -q origin
    git -C "$dir" checkout -q "$branch"
    git -C "$dir" pull -q --ff-only origin "$branch"
    echo "$dir: $branch $(git -C "$dir" log --oneline -1)"
}

step_update() {
    update_checkout "$repo" "$BUILDER_BRANCH"
    update_checkout "$src/alliancemine" "$AM_BRANCH"
    update_checkout "$src/alliancemine-bio-sources" "$BS_BRANCH"
}

step_image() {
    ALLIANCEMINE_BRANCH=$AM_BRANCH BIO_SOURCES_BRANCH=$BS_BRANCH compose build --pull alliancemine-builder
    local shas am_sha bs_sha want_am want_bs
    shas=$(compose run --rm -T --entrypoint cat alliancemine-builder /root/clone-shas.txt | tr -d '\r')
    echo "$shas"
    am_sha=$(echo "$shas" | awk '$1=="alliancemine"{print $3}')
    bs_sha=$(echo "$shas" | awk '$1=="alliancemine-bio-sources"{print $3}')
    want_am=$(git ls-remote https://github.com/alliance-genome/alliancemine.git "refs/heads/$AM_BRANCH" | cut -f1)
    want_bs=$(git ls-remote https://github.com/alliance-genome/alliancemine-bio-sources.git "refs/heads/$BS_BRANCH" | cut -f1)
    [ "$am_sha" = "$want_am" ] || die "image has alliancemine $am_sha, GitHub $AM_BRANCH is $want_am"
    [ "$bs_sha" = "$want_bs" ] || die "image has bio-sources $bs_sha, GitHub $BS_BRANCH is $want_bs"
    echo "image matches GitHub heads"
}

step_fetch() {
    # The cache key includes release and API base (bio-sources PR 13), so a new API base starts cold.
    ALLIANCE_RELEASE=$RELEASE ALLIANCE_API_BASE=$API_BASE BIO_SOURCES="$src/alliancemine-bio-sources" \
        "$repo/tools/api_fetch/run.sh" "$@"
}

step_check() {
    compose run --rm -T alliancemine-builder check-downloads
}

step_build() {
    compose run --rm -T -e RC_NUMBER="$RC" alliancemine-builder build
}

step_resume() {
    compose run --rm -T -e RC_NUMBER="$RC" alliancemine-builder build --start-from project_build --resume
}

# Post-load checks from docs/REVIEW_9_2_0_RC1.md. Hard checks fail the step; counts are information.
step_verify() {
    local fails=0
    check() {
        local name=$1 sql=$2 expect=$3 got
        got=$(rds_sql "$DB" "$sql")
        if [ "$got" = "$expect" ]; then echo "PASS $name = $got"; else echo "FAIL $name = ${got:-?} (want $expect)"; fails=$((fails + 1)); fi
    }
    info() { echo "info $1 = $(rds_sql "$DB" "$2" | tr '\n' ' ')"; }
    check "Gene without organism" "select count(*) from gene where organismid is null" 0
    check "Allele.gene dangling" "select count(*) from allele a left join gene g on g.id=a.geneid where a.geneid is not null and g.id is null" 0
    check "Homologue.gene dangling" "select count(*) from homologue h left join gene g on g.id=h.geneid where h.geneid is not null and g.id is null" 0
    check "Allele without primaryIdentifier" "select count(*) from allele where primaryidentifier is null" 0
    check "DiseaseModel without disease" "select count(*) from diseasemodel where diseaseid is null" 0
    check "Publication pubMedId with prefix" "select count(*) from publication where pubmedid like '%:%'" 0
    check "Gene on chromosome 'null'" "select count(*) from gene g join chromosome c on c.id=g.chromosomeid where c.primaryidentifier='null'" 0
    info "Yeast organisms (4932 stays until review item 12 is decided)" "select taxonid, count(*) from organism where taxonid in (4932,559292) group by 1"
    info "DiseaseEvidence orphans (no annotation)" "select count(*) from diseaseevidence e where not exists (select 1 from evidenceontologyannotation x where x.evidence=e.id)"
    info "Samples total / with characteristics" "select (select count(*) from sample), (select count(distinct sample) from characteristicssample)"
    info "Proteins without gene, by taxon" "select o.taxonid, count(*) from protein p join organism o on o.id=p.organismid where not exists (select 1 from genesproteins gp where gp.proteins=p.id) group by 1 order by 1"
    info "Alleles with gene, by organism" "select o.shortname, count(*) from allele a join gene g on g.id=a.geneid join organism o on o.id=g.organismid group by 1 order by 2 desc"
    info "UTR with sequence on 559292" "select count(*) from utr u join organism o on o.id=u.organismid where o.taxonid=559292 and u.sequenceid is not null"
    info "Class counts" "select 'Gene',count(*) from gene union all select 'Allele',count(*) from allele union all select 'Protein',count(*) from protein union all select 'Publication',count(*) from publication union all select 'DiseaseAnnotation',count(*) from diseaseannotation union all select 'Homologue',count(*) from homologue union all select 'Interaction',count(*) from interaction union all select 'Organism',count(*) from organism union all select 'Chromosome',count(*) from chromosome"
    [ "$fails" -eq 0 ] || die "$fails hard check(s) failed on $DB"
    echo "verify ok on $DB"
}

run_step() {
    local step=$1; shift
    local log
    log="$runs/${step}-rc${RC}-$(ts).log"
    echo "== $step (log $log)"
    "step_$step" "$@" 2>&1 | tee "$log"
}

case "${1:-}" in
    preflight|update|image|fetch|check|build|resume|verify) run_step "$@" ;;
    all)
        for s in preflight update image fetch check build verify; do run_step "$s"; done ;;
    *) /usr/bin/sed -n '2,19p' "$0"; exit 2 ;;
esac

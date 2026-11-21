#!/usr/bin/env bash
# Extract AllianceMine inputs from an Alliance curation dump (pg_dump custom format, PostgreSQL 17).
#
#   tools/curation_dump/extract.sh <dump> <out-dir> [extract ...]      (default extract: genes)
#
# Each extract is tools/curation_dump/<name>.sql; without an extract_<name> function below, its
# output goes to <out-dir>/<name>.tsv. The SQL's first line lists the tables it needs
# ("-- tables: a b c"). The script restores only those tables, without indexes or foreign keys,
# into a throwaway postgres:17 container with no published port and no host data volume, runs
# the SQL, writes <out-dir>/<output>, and stops the container on exit, which deletes the restored
# data. The dump is mounted read-only.
#
# Outputs of the genes extract:
#   Gene.tsv                 14-column layout read by AllianceGenesConverter
#   gene-ids/<MOD>.txt       one gene CURIE per line, the per-gene fetchers' seed list
#   counts.txt               genes, genes with a location and the location assembly, per MOD
#
# Environment: PG_IMAGE (default postgres:17), RESTORE_JOBS (default 4).
set -euo pipefail

here=$(cd "$(dirname "$0")" && pwd)
PG_IMAGE=${PG_IMAGE:-postgres:17}
RESTORE_JOBS=${RESTORE_JOBS:-4}
container=agr-curation-extract-$$

die() { echo "FAIL: $*" >&2; exit 1; }
say() { echo "[$(date -u +%FT%TZ)] $*"; }

[ $# -ge 2 ] || die "usage: $0 <dump> <out-dir> [extract ...]"
dump=$(cd "$(dirname "$1")" && pwd)/$(basename "$1")
out=$2
shift 2
extracts=("${@:-genes}")
[ -f "$dump" ] || die "$dump not found"
for e in "${extracts[@]}"; do [ -f "$here/$e.sql" ] || die "no extract $here/$e.sql"; done
mkdir -p "$out"
out=$(cd "$out" && pwd)

tables=$(for e in "${extracts[@]}"; do /usr/bin/sed -n '1s/^-- tables: //p' "$here/$e.sql"; done | tr ' ' '\n' | sort -u | tr '\n' ' ')
[ -n "${tables// /}" ] || die "no '-- tables:' line in the extract SQL"
table_args=()
for t in $tables; do table_args+=(-t "$t"); done

cleanup() { docker stop "$container" >/dev/null 2>&1 || true; }
trap cleanup EXIT

say "container $container ($PG_IMAGE), dump $dump"
docker run -d --rm --name "$container" -e POSTGRES_HOST_AUTH_METHOD=trust -e POSTGRES_DB=curation \
    --shm-size=2g -v "$(dirname "$dump"):/dump:ro" "$PG_IMAGE" >/dev/null
for _ in $(seq 1 60); do docker exec "$container" pg_isready -U postgres -q 2>/dev/null && break; sleep 2; done
docker exec "$container" pg_isready -U postgres -q || die "postgres did not start"

in_dump=/dump/$(basename "$dump")
say "restore $tables"
docker exec "$container" pg_restore -U postgres -d curation --section=pre-data --no-owner --no-acl \
    "${table_args[@]}" "$in_dump"
docker exec "$container" pg_restore -U postgres -d curation --data-only --no-owner --no-acl \
    -j "$RESTORE_JOBS" "${table_args[@]}" "$in_dump"

psql_run() { docker exec -i "$container" psql -U postgres -d curation -v ON_ERROR_STOP=1 -q; }

extract_genes() {
    psql_run < "$here/genes.sql" > "$out/Gene.tsv.tmp"
    local dups
    dups=$(tail -n +2 "$out/Gene.tsv.tmp" | cut -f1 | sort | uniq -d | head -3)
    [ -z "$dups" ] || die "Gene.tsv has repeated Ids (more than one location?): $dups"
    mv "$out/Gene.tsv.tmp" "$out/Gene.tsv"
    mkdir -p "$out/gene-ids"
    rm -f "$out"/gene-ids/*.txt
    awk -F'\t' -v dir="$out/gene-ids" '
        BEGIN { split("NCBITaxon:559292 SGD NCBITaxon:10090 MGI NCBITaxon:10116 RGD NCBITaxon:7955 ZFIN NCBITaxon:7227 FB NCBITaxon:6239 WB NCBITaxon:8355 XBXL NCBITaxon:8364 XBXT NCBITaxon:9606 HUMAN", a, " ")
                for (i = 1; i < 18; i += 2) mod[a[i]] = a[i + 1] }
        NR > 1 { print $1 > (dir "/" mod[$9] ".txt") }' "$out/Gene.tsv"
    for f in "$out"/gene-ids/*.txt; do sort -o "$f" "$f"; done
    psql_run <<'SQL' > "$out/counts.txt"
\copy (SELECT g.mod, count(*) AS genes, count(l.id) AS with_location, string_agg(DISTINCT ga.primaryexternalid, ',') AS assembly FROM g LEFT JOIN genegenomiclocationassociation l ON l.geneassociationsubject_id = g.id AND NOT coalesce(l.obsolete, false) LEFT JOIN assemblycomponent ac ON ac.id = l.genegenomiclocationassociationobject_id LEFT JOIN biologicalentity ga ON ga.id = ac.genomeassembly_id GROUP BY g.mod ORDER BY g.mod) TO STDOUT WITH (FORMAT csv, DELIMITER E'\t', HEADER true)
SQL
    say "Gene.tsv: $(($(wc -l < "$out/Gene.tsv") - 1)) genes"
    column -t "$out/counts.txt"
}

for e in "${extracts[@]}"; do
    say "extract $e"
    if declare -F "extract_$e" >/dev/null; then
        "extract_$e"
    else
        psql_run < "$here/$e.sql" > "$out/$e.tsv"
        say "$e.tsv: $(($(wc -l < "$out/$e.tsv") - 1)) rows"
    fi
done
say "done; stopping $container (deletes the restored tables)"

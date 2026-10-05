#!/bin/bash
# extract_gene_dbxrefs.sh - gene cross-references for the flybase-gene-crossreferences source,
# pulled from the local chado-pg (run on the build host, from flymine-deploy/).
#
# Same 7 gene-specific DBs as the Sep 2026 reload. No Reactome/KEGG: pathway accessions are shared
# across genes and belong in Gene.pathways, not crossReferences.
# New for FB2026_03: restricted to current (non-obsolete) gene features of the 12 species FlyMine's
# chado sources load. The converter creates a Gene for every FBgn it sees, so the unfiltered Sep
# extract (239K FBgns) made ~145K identifier-only stub genes that had to be deleted after loading.
set -euo pipefail
cd /home/ec2-user/flymine-deploy
OUT=data/flybase/crossreferences/current/gene_dbxrefs.tsv
sudo mkdir -p "$(dirname "$OUT")"

docker exec -i chado-pg psql -U chado -d chado -v ON_ERROR_STOP=1 -At -F $'\t' <<'SQL' | sudo tee "$OUT.new" >/dev/null
SELECT DISTINCT f.uniquename, db.name, dx.accession
FROM feature f
JOIN cvterm t          ON t.cvterm_id = f.type_id AND t.name = 'gene'
JOIN organism o        ON o.organism_id = f.organism_id
JOIN feature_dbxref fd ON fd.feature_id = f.feature_id
JOIN dbxref dx         ON dx.dbxref_id = fd.dbxref_id
JOIN db                ON db.db_id = dx.db_id
WHERE f.uniquename ~ '^FBgn[0-9]+$' AND NOT f.is_obsolete
  AND o.genus = 'Drosophila'
  AND o.species IN ('melanogaster','pseudoobscura','ananassae','erecta','grimshawi','mojavensis',
                    'persimilis','sechellia','simulans','virilis','willistoni','yakuba')
  AND db.name IN ('GB_protein','FlyBase Annotation IDs','EntrezGene','UniProt/TrEMBL','GB',
                  'FLYCYC_GENE','UniProt/Swiss-Prot');
SQL

sudo mv "$OUT.new" "$OUT"
echo "rows: $(sudo wc -l < "$OUT")  genes: $(sudo cut -f1 "$OUT" | sort -u | wc -l)"
sudo cut -f2 "$OUT" | sort | uniq -c | sort -rn

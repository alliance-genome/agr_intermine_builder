# Gene.tsv: how it's produced in the new builder

## Background

The `alliance-genes` source in `project.xml` reads
`/root/data/genes/Gene.tsv` and feeds it to
`AllianceGenesConverter.java`, which expects a 14-column tab-delimited file
with this exact header:

```
Id  SecondaryId  Synonyms  CrossRefs  Name  Symbol  MOD Description  \
Auto Description  Species  Chromosome  Start  End  Strand  SoTerm
```

Each row becomes one Gene Item linked to the "Alliance Gene data set"
dataset. This source is the **primary** carrier of gene metadata for every
non-yeast MOD; without it, gene records for mouse, rat, zebrafish, fly, worm,
human, X.laevis, and X.tropicalis are reduced to placeholder rows that other
sources (GO annotation, orthologs, alleles) create as side effects.

## How 8.3.0 produced Gene.tsv

8.3.0 used Alliance's Java tool `agr_intermine_data_extractor`, run out of
ECR image `100225593120.dkr.ecr.us-east-1.amazonaws.com/agr_java_software:stage`
with extractor classes `GeneExtractor` + `FMSExtractor`. The tool queried
the Alliance Neo4j stage host (`stage.alliancegenome.org`) and wrote
`/data/genes/Gene.tsv` into a host-mounted volume. That file (193 MB,
~470K rows across 9 MODs + SARS-CoV-2) was reused for every 8.3.0 build.

That tool is no longer wired into the new container build path, and the
Alliance Neo4j stage may not be reliably available going forward. We
replaced it with a local synthesis step.

## How 9.0.0+ produces Gene.tsv

`docker/alliancemine/scripts/bgi_to_genes_tsv.py` reads the per-MOD
`BGI_*.json` files that `extract_data.py` downloads from FMS into
`/root/data/genes/`, and emits `Gene.tsv` in the same directory.

Field mapping from BGI 1.0.2.x JSON to the 14-column schema:

| Col | Output field | BGI source |
|---|---|---|
| 1 | Id | `basicGeneticEntity.primaryId` |
| 2 | SecondaryId | first of `basicGeneticEntity.secondaryIds[]` |
| 3 | Synonyms | `[a, b, c]` from `basicGeneticEntity.synonyms[]` |
| 4 | CrossRefs | `[a, b, c]` from `basicGeneticEntity.crossReferences[].id` |
| 5 | Name | top-level `name` |
| 6 | Symbol | top-level `symbol` |
| 7 | MOD Description | top-level `geneSynopsis` |
| 8 | Auto Description | empty (BGI does not carry this; the old Neo4j extractor pulled it from a separate slot) |
| 9 | Species | `basicGeneticEntity.taxonId` |
| 10 | Chromosome | `genomeLocations[0].chromosome` |
| 11 | Start | `genomeLocations[0].startPosition` |
| 12 | End | `genomeLocations[0].endPosition` |
| 13 | Strand | `genomeLocations[0].strand` |
| 14 | SoTerm | **SO term name** (e.g. `protein_coding_gene`) — translated from `soTermId` via `/root/data/fms/ONTOLOGY_SO.obo` |

**Critical**: column 14 must contain the SO term **name**, not the ID.
`AllianceGenesConverter.java` switches on `feature_type.equalsIgnoreCase("protein_coding_gene")` etc., so an SO ID like `SO:0001217` matches nothing and the row is silently dropped (`item == null` → `continue`). See `docs/RC20_BUILD_INCIDENT_2026_05_07.md` §"Root cause #2" for the full debugging story.

The "Auto Description" gap is acceptable: the converter handles an empty
column, and the gene Synopsis (col 7) is populated from `geneSynopsis`. If
we later need automated descriptions for those rows we can join them in
from the Alliance API `/api/gene/{id}` endpoint via a separate fetcher.

## Wiring

```
extract_data.py FMSExtractor.download_all()
  -> after FMS file download loop:
  -> build_genes_tsv()
       -> python3 docker/alliancemine/scripts/bgi_to_genes_tsv.py
              --data-dir /root/data/genes
              --out Gene.tsv
```

`project.xml` was updated to scope the alliance-genes source to
`Gene.tsv` only (`src.data.dir.includes`), so `AllianceGenesConverter`
no longer tries to parse the BGI JSON files in the same directory.

## Rebuilding the file ad-hoc

If `Gene.tsv` is stale or missing on the dev host, rerun the build step
without re-downloading FMS:

```bash
docker compose run --rm alliancemine-builder \
    python3 /root/scripts/bgi_to_genes_tsv.py \
    --data-dir /root/data/genes \
    --out Gene.tsv
```

Expected output: ~330-470K rows depending on FMS release content. Compare
to per-MOD BGI counts:

```bash
for f in /root/data/genes/BGI_*.json; do
    echo "$f $(python3 -c "import json,sys;print(len(json.load(open(sys.argv[1]))['data']))" "$f")"
done
```

## Verification after build

After integration, expect the "Alliance Gene data set" to be the
single largest gene-dataset attribution per MOD. Sample query:

```sql
SELECT d.name, count(*)
FROM gene g
JOIN bioentitiesdatasets bd ON bd.bioentities = g.id
JOIN dataset d ON d.id = bd.datasets
JOIN organism o ON g.organismid = o.id
WHERE o.shortname = 'M. musculus'
GROUP BY d.name
ORDER BY 2 DESC;
```

Healthy result for mouse: `Alliance Gene data set` ≈ 80-95K rows.

## Future work

When the Alliance API fetcher (`alliancemine-bio-sources/scripts/fetch_genes.py`
on the `wire-api-sources` branch) lands on master, we can deprecate this
local synthesis step. The API path is preferred long-term:
- automated descriptions are populated
- `dateProduced`, `dataProvider`, `modCrossRefCompleteUrl` slots are filled
- single canonical source per Alliance release

## Related files

- `docker/alliancemine/scripts/bgi_to_genes_tsv.py` — the synthesiser
- `docker/alliancemine/scripts/extract_data.py` — `build_genes_tsv()` invocation
- `docker/alliancemine/project.xml` — `alliance-genes` source includes
- `legacy/old_bash_scripts/run_data_extractor` — historical Neo4j-based extractor command

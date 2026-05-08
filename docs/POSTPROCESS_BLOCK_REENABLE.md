# project.xml postprocess block — re-enable for future builds

Date: 2026-05-08
Status: pending decision (rc20 backup first), but next build MUST include these steps

## Context

Current `/root/alliancemine/project.xml` (and upstream `alliance-genome/alliancemine`) has five `<post-process>` entries commented out:

```xml
<post-processing>
    <post-process name="create-references"/>
    <post-process name="do-sources"/>
    <!--<post-process name="create-intergenic-region-features"/>
    <post-process name="create-location-overlap-index"/>
    <post-process name="create-overlap-view"/>
    <post-process name="create-gene-flanking-features"/>
    <post-process name="populate-child-features"/>-->
    <post-process name="transfer-sequences"/>
    <post-process name="create-attribute-indexes"/>
    <post-process name="summarise-objectstore"/>
    <post-process name="create-autocomplete-index"/>
    <post-process name="create-search-index"/>
</post-processing>
```

These five were likely disabled during 9.0.0 build-time tuning (each adds 5-15 min to postprocess). Never re-enabled.

## Direct consequences (verified in rc20 audit, 2026-05-08)

| Empty table | Affected user templates |
|---|---|
| `intergenicregion` (0 rows) | Retrieve → All intergenic regions; Chromosome → All intergenic regions; Gene → Upstream intergenic region |
| `geneflankingregion` (0 rows) | Gene → Flanking features within a specific distance |
| `intron` (0 rows) | Retrieve → All genes that have introns |

Plus side effects on overlap queries (location-overlap-index, overlap-view) and any template that traverses `Gene.upstreamIntergenicRegion`, `Gene.flankingRegions`, `Gene.introns`, or any `*.overlappingFeatures.*` path.

## What each step does

| Step | Function | Time on rc20-sized DB |
|---|---|---|
| `create-intergenic-region-features` | Walks chromosomes, computes adjacent-gene gaps, emits `IntergenicRegion` Items + `adjacentGenes` collection | 5-10 min |
| `create-location-overlap-index` | Builds B-tree indexes on `Location.start/end` to make overlap joins viable | 1-2 min |
| `create-overlap-view` | Materialized view of feature-pairs that overlap, used by `*.overlappingFeatures.*` template paths | 2-5 min |
| `create-gene-flanking-features` | For every gene, emits `GeneFlankingRegion` Items at +/- N kb upstream/downstream | 5-15 min |
| `populate-child-features` | Walks parent→child feature hierarchy (e.g. MRNA → exon, intron) and propagates references | 5-10 min |

Total ~30-50 min added to postprocess phase.

## Fix

In **upstream `alliance-genome/alliancemine` repo** `project.xml`: uncomment the block. PR upstream so it ships in the next AllianceMine release.

In **the in-repo `docker/alliancemine/project.xml`** patched copy (if any): apply same fix.

In **rc20 currently running container**: edit `/root/alliancemine/project.xml` in builder, then run each step manually against rc20 DB:

```bash
ssh AllianceMineDev
docker exec -it alliancemine-alliancemine-builder-run-c06d6908f14f bash
cd /root/alliancemine

# edit project.xml — uncomment the block (sed or vi)

for p in create-intergenic-region-features \
         create-location-overlap-index \
         create-overlap-view \
         create-gene-flanking-features \
         populate-child-features; do
  ./gradlew --stacktrace --no-daemon \
      -Dorg.gradle.project.release=9.0.0-rc20 \
      postprocess -Pprocess=$p \
      2>&1 | tee /root/alliancemine/postproc-$p-$(date +%Y%m%d-%H%M).log
done

# refresh search + autocomplete since data changed
./gradlew postprocess -Pprocess=create-search-index \
    -Dorg.gradle.project.release=9.0.0-rc20
./gradlew postprocess -Pprocess=create-autocomplete-index \
    -Dorg.gradle.project.release=9.0.0-rc20

# WAR rebuild not required - data changes only
```

## Pre-flight: backup rc20 first

Before running postprocess steps that mutate the rc20 DB, dump to S3:

```bash
docker exec alliancemine-alliancemine-builder-run-c06d6908f14f bash -c \
  'PGPASSWORD=$RDS_PASSWORD pg_dump -h $RDS_HOST -U $RDS_USER -F c \
   -f /tmp/alliancemine_9_0_0_rc20_pre_postproc.dump alliancemine_9_0_0_rc20'

# copy out, push to S3
docker cp alliancemine-alliancemine-builder-run-c06d6908f14f:/tmp/alliancemine_9_0_0_rc20_pre_postproc.dump /tmp/

aws s3 cp /tmp/alliancemine_9_0_0_rc20_pre_postproc.dump \
  s3://agr-db-backups/db-backups/alliancemine/alliancemine_9_0_0_rc20_pre_postproc_$(date -u +%Y%m%d).dump
```

If postprocess steps misbehave (rare but possible — `create-overlap-view` has been known to OOM on huge gene sets) we restore from this dump.

## Verification after postprocess rerun

```sql
SELECT 'intergenic', count(*) FROM intergenicregion
UNION ALL SELECT 'flanking',  count(*) FROM geneflankingregion
UNION ALL SELECT 'intron',    count(*) FROM intron
UNION ALL SELECT 'overlap_idx_size_mb', pg_relation_size('location__start_end_loc') / 1024 / 1024;
```

Expected:
- `intergenic` ~5000-6000 (yeast-only feature)
- `flanking` ~50000+ (every gene × 2 directions)
- `intron` 200+ if `populate-child-features` derives them from MRNA exon gaps; could be 0 if no exon-pairs in source data
- overlap index 50-200 MB

Then re-test affected templates:

```bash
BASE='http://172.31.59.87:8086/alliancemine/service/template/results'
curl -s "$BASE?name=Organism_IntergenicRegions&format=tsv&size=5" | head
curl -s "$BASE?name=gene_overlapping_flanking_regions&constraint2=GeneFlankingRegion.gene&op2=LOOKUP&value2=his3&constraint4=GeneFlankingRegion.direction&op4=eq&value4=upstream&constraint5=GeneFlankingRegion.overlappingFeatures.featureType&op5=eq&value5=ORF&constraint1=GeneFlankingRegion.length&op1=eq&value1=2000&format=tsv" | head
curl -s "$BASE?name=Gene_Introns&format=tsv&size=5" | head
```

## Why this matters going forward

Every new RC build inherits the commented block. Without re-enable, every yeast user that tries to find introns, intergenic regions, or flanking features hits 0 results. This is a multi-year regression masked by the fact that yeast curators don't typically use those templates daily. Comments from users in 2026-05 audit suggest at least three external researchers noticed.

Permanent fix path:
1. PR `alliance-genome/alliancemine` upstream to uncomment the block.
2. Add a postprocess smoke test to the build pipeline: after `create-search-index` finishes, query `count(*)` on intergenicregion / geneflankingregion / intron and fail the build if all three are zero (currently 0 silently passes).
3. Add the smoke test to `build_full.py` in this repo.

## Related files

- `/root/alliancemine/project.xml` (in builder, currently commented)
- Upstream `alliance-genome/alliancemine/project.xml`
- `docker/alliancemine/scripts/build_full.py` — pipeline runner; add smoke check here
- `docs/RC20_TEMPLATE_TRIAGE.md` — broader rc20 template audit

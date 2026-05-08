# AllianceMine TODO — rc20 follow-up

Last updated: 2026-05-08

Snapshot of open work after the rc20 build + initial template triage. Every line should resolve via either an XML edit + redeploy, a postprocess rerun, a source-loader patch, or a groupwide design call. References point at the doc with the full diagnosis.

## DONE this session (for context)

- rc20 build completed (genes 460k, alleles 431k, expression 1.77M)
- pg_dump rc20 → 7.9 GB at builder `/tmp/alliancemine_9_0_0_rc20_pre_postproc_20260508_1436.dump` (not yet pushed to S3)
- Webapp deployed to multitenant:8086, properties baked-in correct
- Complex bag-upgrade fix (class_keys.properties Complex key + taxonif→taxonid typo)
- Complex fieldconfig reorder in webconfig-model.xml so list view defaults show data
- osbag_int populated for "Curated Macromolecular Complexes" — list now shows 634 items live
- Dockerfile patches committed locally (`agr_intermine_builder` 581d7cb)
- Source fixes committed in sibling `alliancemine` repo wire-api-sources branch (af455b1)

## Template fixes — pure XML edits, no rebuild

| TaskID | Template | Fix |
|---|---|---|
| #27 | Gene→Alleles | Decide multi-MOD strategy (see Design Discussion below) before editing |
| #28 | Allele→Identifiers + Gene→Variants | Same — depends on multi-MOD decision |
| #30 | Literature→Functional Complementation | Trim view cols that always render blank for HGNC complements |
| #32 | Gene→Expression / Expression→Gene | Convert INNER joins to OUTER on `location/anatomy`; replace ZFIN-default LOOKUP with empty/yeast |
| #33 | Gene→GenomicDNA + Gene→Identifiers | Add Gene.secondaryIdentifier and Gene.crossReferences.source.name to view; fix bad ZFIN defaults |
| #34 | Gene→UTRs | Rewrite path `Gene.transcripts.UTRs.*` → `Gene.UTRs.*`; drop stale `dataSets.name='SGD data set'` constraint (see `docs/TEMPLATE_FIX_GENE_UTRS.md`) |
| #35 | ChromosomeRegion + Chromosome_Gene_FeatureType | Delete 5 duplicate AGR-style templates from default-template-queries.xml; or fix bad defaults (`S. cerevisiae S288C` → `S. cerevisiae`, fly → yeast) |

After all of these: rebuild WAR (`./gradlew :webapp:assemble`), redeploy to 8086.

## Postprocess gaps — uncomment + rerun, no rebuild

| TaskID | What |
|---|---|
| #29 | intron=0 (Gene_Introns template) |
| #31 | intergenicregion=0 + view cols (Organism_IntergenicRegions) |
| #36 | geneflankingregion=0 (gene_overlapping_flanking_regions) |

Single fix: uncomment 5 postprocess steps in `/root/alliancemine/project.xml`:
- create-intergenic-region-features
- create-location-overlap-index
- create-overlap-view
- create-gene-flanking-features
- populate-child-features

Then run each via `./gradlew postprocess -Pprocess=<step>` against rc20 DB. ~30-60 min total. Rerun create-search-index + create-autocomplete-index after. Full plan in `docs/POSTPROCESS_BLOCK_REENABLE.md`. Pre-flight: push the existing pg_dump to S3 first.

## SGD allele investigation

| TaskID | What |
|---|---|
| #37 | Audit SGD allele loader code (sgd-allele converter): is it emitting all expected fields (description, alleleClass, aliasName, allelesgdid, name, publications)? Compare emit calls to rc20 allele table content. |
| #38 | Audit FMS allele payload + model coverage: pull fresh ALLELE_SGD JSON, list keys, compare to converter reads. Audit `genomic_additions.xml` Allele class — fields curators expect (description, alleleClass, aliasName, secondaryIds, publications, phenotypes) all declared? |

Driver: TFC3 / CDC28 show 4 / 47 alleles in template, of which 2 / 17 render blank. Blanks are AGR-source allele records (alleleId/alleleSymbol set, SGD fields NULL). User believes SGD loader was supposed to populate description etc — verify before assuming AGR/SGD schema split is the only cause.

## Yeast organism dedup (data quality)

`organism` table has 2 rows with `shortName='S. cerevisiae'`:
- id 25000004, taxon 559292 (S288C reference) — 7964 genes
- id 32000001, taxon 4932 (legacy generic) — 4 ghost genes

Plus 2 empty-shortName orgs at taxonids 339724 + 237631.

Fix: source-loader normalization (`alliance-genes` fetcher: collapse 4932→559292). Or one-shot SQL remap on rc20 if loader fix is too big a lift this cycle.

## Design discussion items

`docs/TEMPLATE_DESIGN_MULTIMOD_DISCUSSION.md` — needs groupwide call:
- AllianceMine = YeastMine + Alliance multi-MOD. Alleles, expression, variants, identifiers all have parallel SGD-shape vs AGR-shape data on the same InterMine classes.
- Pick: Position 1 (yeast-canonical, hide AGR), Position 2 (AGR-canonical, deprecate SGD shape), Position 3 (multiplex view with both), Position 4 (per-organism template variants).
- Decision blocks #27 / #28 final fix.

## Source-loader / model fixes (rebuild required, NOT tonight)

- sgd-gff-utr converter — wire UTR↔transcript edge so `Gene.transcripts.UTRs.*` path works (workaround applied for #34)
- alliance-alleles converter — dedupe AGR allele records against existing SGD-source alleles by primary identifier so TFC3/CDC28 don't get double-loaded
- Yeast organism normalization in fetchers (collapse 4932 → 559292)

## Upstream PRs to alliance-genome/alliancemine

Already committed locally on `wire-api-sources` (alliancemine repo, af455b1):
- `dbmodel/resources/class_keys.properties` — Complex key + taxonif→taxonid
- `webapp/src/main/webapp/WEB-INF/webconfig-model.xml` — Complex fieldconfig reorder

Pending:
- Cherry-pick or fast-forward to master, open PR
- project.xml postprocess block uncomment (after rerun verifies it doesn't break the build)

## Operational

- IAM RDS perms for `pnuin` (admin to apply): single inline policy command in `docs/IAM_POLICIES_PNUIN_RDS.md`. Unblocks shared_buffers/effective_cache_size param activation that's been pending since 2026-05-05.
- Push pre-postproc dump to S3:
  ```bash
  aws s3 cp .../alliancemine_9_0_0_rc20_pre_postproc_20260508_1436.dump \
    s3://agr-db-backups/db-backups/alliancemine/
  ```
- Push commits to remotes (currently both local-only):
  - `agr_intermine_builder` development @ 398122a + 581d7cb
  - `alliancemine` wire-api-sources @ af455b1

## Build pipeline hardening

Add to `docker/alliancemine/scripts/build_full.py` after postprocess phase:
- Smoke test: query count(*) on intergenicregion / geneflankingregion / intron / gene / allele / expressionannotation. Fail build if any are zero (currently 0 silently passes — caused this whole rc20 audit cycle).
- Verify class_keys.properties has Complex (and any new bag-relevant classes) before WAR build.

## Reference docs

- `docs/RC20_BUILD_INCIDENT_2026_05_07.md` — rc20 build incident timeline + recovery
- `docs/RC20_TEMPLATE_TRIAGE.md` — full template-bug audit
- `docs/USER_TEMPLATE_REPORT_2026_05_07.md` — original 15-issue user report
- `docs/TEMPLATE_DESIGN_MULTIMOD_DISCUSSION.md` — multi-MOD schema split design call
- `docs/TEMPLATE_FIX_GENE_UTRS.md` — Gene_UTRs path-rewrite fix
- `docs/POSTPROCESS_BLOCK_REENABLE.md` — Bucket B uncomment + rerun procedure
- `docs/IAM_POLICIES_PNUIN_RDS.md` — IAM grant for RDS reboot/scale
- `docs/RUNBOOK_ALLIANCEMINE_RESTART.md` — Webapp restart with bag-upgrade kick
- `docs/MULTITENANT_BACKUP_RESTORE.md` — Snapshot/restore mines on multitenant host

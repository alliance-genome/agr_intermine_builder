# rc20 template fix status — 2026-05-12

Session-end summary of which user-reported template issues are fixed live on 8086 (`alliancemine-9.0.0-rc20`, pointed at `alliancemine_9_0_0_rc20` DB on intermine-postgres RDS) versus what still needs a rebuild.

All "fixed" entries are live in `alliancemine_userprofile.savedtemplatequery` and verified via REST `/service/template/results?...&format=count`. Saved-template overrides survive webapp restart. Source XML in builder NOT yet patched for the post-25 saved templates — needs a separate commit before the next WAR rebuild.

## ✅ Fixed live on 8086 (16 templates + infrastructure)

| User-reported issue | Template / change | Verified |
|---|---|---|
| #1 Gene → Alleles (CDC28: 47 rows, 17 blank) | `Gene_Alleles` — added Gene.alleles.alleleId/alleleSymbol/alleleType to view; all 47 rows now populated (AGR fields fill where SGD fields null) | 47 ✓ |
| #2a Allele → Identifiers no yeast | `Allele_Identifiers` — multiplex SGD+AGR view (12 cols), `Gene.alleles LOOKUP cdc28-4` via expanded Allele class key | 1,520 ✓ |
| #4 Literature → Functional Complementation blank cols | `Literature_Complements` — dropped 3 always-blank cols (complement.symbol, crossReferences.identifier, source.name); added `complement.secondaryIdentifier` which carries the HGNC string | 2,866 ✓ |
| #5 Deleted Merged Features needs status / MOD description | `Deleted_Merged_Features_Tab` — added Gene.status + Gene.modDescription cols; dropped Gene.briefDescription; OUTER joins on chromosome/chromosomeLocation | 98 ✓ |
| #6 Retrieve → All intergenic regions returns 0 | `Organism_IntergenicRegions` — re-ran `create-intergenic-region-features` postprocess; populated 6,386 rows | 6,386 ✓ |
| #7 Gene → Expression returns 0 | `Gene_Expression` — changed ZFIN default LOOKUP `fgf8b` to `CDC28` | 6 ✓ |
| #8 Expression → Gene returns 0 | `Expression_Gene` — `location` constraint switched to `CONTAINS cytoplasm` (most common yeast value); OUTER joins on cellular component / anatomy / etc. | 5,919 ✓ |
| #9 Gene → Genomic DNA missing systematic / standard names | `Gene_GenomicDNA` — replaced bare AGR body with SGD-style 10-col view (sgdAlias, secondaryIdentifier, symbol, description, qualifier) | 1 ✓ |
| #10 Gene → Identifiers not intuitive, missing cols | `Gene_Identifiers` — added Gene.secondaryIdentifier + Gene.crossReferences.source.name to view; replaced ZFIN defaults with `S. cerevisiae` / wildcard / `SGD*` | 5,587 ✓ |
| #11 Gene → UTRs no yeast results | `Gene_UTRs` — rewrote path `Gene.transcripts.UTRs.*` → `Gene.UTRs.*` direct; dropped stale `dataSets.name='SGD data set'` constraint; dropped `Gene.UTRs.sequence.residues` from view (sequence not loaded for yeast UTRs by sgd-gff-utr converter — separate gap) | 4 ✓ |
| #12 Chromosomal Region → All genes (S. cerevisiae S288C default) | `ChromosomeRegion_AllGenes` — default org changed to `S. cerevisiae` with `CONTAINS` op | 12 ✓ |
| #13 Chromosome → Genes by Feature Type (fly defaults) | `Chromosome_Gene_FeatureType` — yeast chrI/ORF defaults | 117 ✓ |
| #14 Gene → Flanking features returns 0 | `gene_overlapping_flanking_regions` — re-ran `create-gene-flanking-features` postprocess; populated 145,160 rows | 4 (his3 upstream ORF 2000bp) ✓ |
| Curated Macromolecular Complexes list 0 items | `class_keys.properties` — added `Complex = identifier, accession, name`; fixed `taxonif` → `taxonid` typo; manually populated `osbag_int` with 634 rows | 634 ✓ |
| Complex list view hides results | `webconfig-model.xml` — moved `systematicName` fieldconfig above `properties` in Complex class block | live |
| Complex template impossible AND'd defaults | `Complex_Details_Participant` — name constraint switchable=OFF, accession-only by default | 45 ✓ |
| GoSlim template impossible AND'd annotType | `GoSlimTerm_Gene` — dropped annotType constraints (field is NULL for all 252,607 rows in rc20; loader gap) | 43,534 ✓ |
| GO Terms tab empty ONE OF list | `GO_Terms_Tab` — default `namespace = biological_process` | 24,435 ✓ |
| Organism → All genes (S. cerevisiae S288C default) | `Organism_Genes` — yeast default | 7,260 ✓ |
| Gene → Variants ZFIN-only | `Gene_Variants` — kept template as-is; updated longDescription to note yeast variants not loaded; suggested Gene → Alleles for yeast users | 5 ✓ |

### Infrastructure changes

| What | Detail |
|---|---|
| RDS instance class | Scaled `db.t3.xlarge` → **`db.r6i.xlarge`** (16 GB → 32 GB RAM, memory-optimized) |
| `shared_buffers` | 8 GB (25% of new RAM; was auto-clamped to 25 GB after scale, manually tuned) |
| `effective_cache_size` | 16 GB (50% of RAM) |
| `work_mem` | 32 MB (unchanged) |
| Solr cores `-rc20` | Populated with 14.5M search docs + 53K autocomplete via filesystem cp from `-9.0.0` core (the 5/8 indexing run had pointed at the wrong core name) |

## ⏳ NOT fixed (require rebuild or further work)

| User-reported issue | Why not fixed live | Action needed |
|---|---|---|
| #3 Retrieve → All genes with introns | `intron` table empty (0 rows) — sgd-gff source doesn't emit Intron objects; populate-child-features postprocess only propagates existing items, doesn't derive. See `docs/INTRON_LOADING_GAP.md`. | Audit which 8.3.0 source loaded 348 yeast introns; add same source to rc21 project.xml OR write a custom postprocess to derive introns from MRNA exon gaps. Rebuild required. |
| #2b Gene → Alleles and Variants (yeast variants) | `variant` table holds 82K rows but ALL are ZFIN/RGD-shape. No yeast variant data loaded. | Add a yeast-variants source if SGD distributes one, OR extend alliance-variants converter to fill yeast. Rebuild required. Currently template is documented as ZFIN-only. |
| TFC3 / CDC28 allele dedup | `alliance-alleles` source loads AGR-shape duplicates of yeast alleles (e.g. CDC28 47 rows = 30 SGD + 17 AGR-duplicate-of-SGD). XML-only fix shows AGR cols populated but duplicates remain. | Fix in `alliance-alleles` converter: dedupe AGR records against existing SGD-source alleles by primary identifier. Rebuild required. |
| SGD allele field completeness (description, alleleClass, etc.) | Pending audit — SGD curator believes loader should populate richer fields. Tasks #37 + #38. | Audit `sgd-allele` converter code + FMS payload + Allele class in `genomic_additions.xml`. May require model addition + rebuild. |
| Lost SGD curator templates | 25 templates exist in old `user-intermine-db.userprofile_alliancemine_local` (90 saved) but NOT in current `alliancemine_userprofile` (65 saved). Pre-8.3.0 hand-edits never propagated. | Extract from local dumps (`dumps/old_userprofile/`); INSERT missing 25 into current `alliancemine_userprofile.savedtemplatequery`. Task #39. |
| Yeast organism duplicate (4 ghost genes on taxon 4932) | Two `S. cerevisiae` rows in `organism` table (559292 + 4932). 4 genes orphan on the legacy 4932 row. | Source-loader normalization in fetcher (collapse 4932 → 559292), or one-shot SQL remap. Rebuild ideal; SQL band-aid optional. |
| `GOEvidenceCode.annotType` NULL for all rows | go-annotation source doesn't populate this attribute. GoSlim template workaround applied (drop the filter) but underlying data still missing. | Fix in `go-annotation` converter to populate annotType from evidence code lookup. Rebuild required. |
| Yeast UTR sequence text | `sgd-gff-utr` converter doesn't link UTR → sequence Item; `Gene.UTRs.sequence.residues` is unreachable. Workaround: dropped from template view. | Fix in sgd-gff-utr converter to populate UTR.sequence. Rebuild required. |
| Source XML (`default-template-queries.xml`) in builder | All 16 live fixes are in `savedtemplatequery` rows only. Next build's WAR will inherit the old WAR-baked XML unless source is patched. | Apply each of the 16 changes to `/root/alliancemine/webapp/src/main/resources/default-template-queries.xml` (builder) and corresponding upstream `alliance-genome/alliancemine` PR. Then next build's WAR ships them as defaults even if userprofile DB is reset. |

## Permanent restore considerations

When a future build deploys against a fresh `alliancemine_userprofile` DB:
- Saved templates in current userprofile DB are PERSISTENT (no DB rebuild) — fixes carry forward as long as userprofile DB is reused.
- If userprofile DB gets reset / migrated, saved fixes are lost. Re-apply via `/service/template/upload` script (have token + endpoint pattern from this session).
- Permanent solution = patch source XML (`default-template-queries.xml`) in upstream `alliance-genome/alliancemine` so future WAR builds include the fixes as baked-in defaults.

## Open task IDs (taskmaster)

- #28 Allele→Variants — partial (Allele_Identifiers done, Gene_Variants needs yeast variants data → rebuild)
- #29 Gene→Introns — needs source-loader work
- #37 SGD allele loader audit — pending
- #38 FMS SGD allele payload + model coverage audit — pending
- #39 Restore lost SGD templates from old userprofile RDS — pending

## Cross-references

- `docs/SESSION_LOG_2026_05_11.md` — previous session's record
- `docs/INTRON_LOADING_GAP.md` — intron template root cause + fix options
- `docs/TEMPLATE_DESIGN_MULTIMOD_DISCUSSION.md` — multi-MOD schema split design call
- `docs/RC20_TEMPLATE_TRIAGE.md` — original triage doc (some assumptions corrected this session, e.g. "populate-child-features will fix introns" — it won't)
- `docs/POSTPROCESS_BLOCK_REENABLE.md` — postprocess rerun procedure
- `docs/RUNBOOK_ALLIANCEMINE_RESTART.md` — restart procedure incl bag-upgrade kick
- `TODO.md` — running task index

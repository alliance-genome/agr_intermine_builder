# rc20 template triage — static analysis

Date: 2026-05-08
Source DB: `alliancemine_9_0_0_rc20` on RDS
Templates dumped from: `/root/alliancemine/webapp/src/main/resources/default-template-queries.xml` (1918 lines, 94 templates, 5 with duplicate names)

This document categorizes the 14 user-reported template bugs into **three failure classes**: configuration omissions in `project.xml`, template XML defects (wrong path / bad defaults / duplicate names), and source-loader gaps (data not produced by an integration source).

## Class A — postprocess steps commented out (project.xml)

Five postprocess steps are commented out in `/root/alliancemine/project.xml`:

```xml
<!--<post-process name="create-intergenic-region-features"/>
<post-process name="create-location-overlap-index"/>
<post-process name="create-overlap-view"/>
<post-process name="create-gene-flanking-features"/>
<post-process name="populate-child-features"/>-->
```

Direct consequences in rc20:

| Empty table | Templates affected |
|---|---|
| `intergenicregion` (0 rows) | Retrieve→All intergenic regions (#5,#6); Chromosome→All intergenic regions; Gene→Upstream intergenic region |
| `geneflankingregion` (0 rows) | Gene→Flanking features within a specific distance |
| `intron` (0 rows; via `populate-child-features`) | Retrieve→All genes that have introns |

**Fix**: uncomment the block, rerun the relevant postprocess steps. They are cheap relative to the build (`create-gene-flanking-features` ~5 min, `create-intergenic-region-features` ~5 min, `populate-child-features` ~10 min on rc20-sized DB). No need to re-integrate.

```bash
# inside builder container
cd /root/alliancemine
./gradlew --stacktrace --no-daemon \
  -Dorg.gradle.project.release=9.0.0-rc20 \
  postprocess -Pprocess=create-intergenic-region-features
# repeat with create-gene-flanking-features, populate-child-features
# then rerun create-search-index + create-autocomplete-index
```

## Class B — duplicate template names (XML defect)

`grep -c '<template name=' default-template-queries.xml` returns 94 distinct template entries, but five names appear twice:

| Name | First occurrence (AGR-style) | Second occurrence (SGD-style) |
|---|---|---|
| `ChromosomeRegion_AllGenes` | line 15 — filter `S. cerevisiae S288C` (no match) | line 219 — filter via featureType, `S. cerevisiae` |
| `Chromosome_Gene_FeatureType` | line 23 — default `D. melanogaster`/`2R`/`protein_coding_gene` | line 253 — default yeast/`chrI`/`ORF` |
| `Gene_GenomicDNA` | line 105 — 5 cols, missing systematicName/symbol | line 451 — full SGD with `sgdAlias`, org filter |
| `Literature_GO` | line 129 | line 610 |
| `Organism_Genes` | line 134 — bare AGR | line 645 — SGD `Retrieve → All chromosomal locations` |

InterMine's `loadTemplates()` parses XML sequentially into a `Map<String,TemplateQuery>`; later wins. **However the webapp UI lists templates by parse order and renders all entries at the title-level** — so users see two templates with the same title. Whichever they click first is XML-order-first (AGR-broken).

**Fix**: in this AllianceMine build, the SGD versions are correct for users. Delete the AGR-style duplicates at lines 15-19, 23-29, 105-109, 129-133, 134-138. Keep the AGR templates that have unique names (e.g. Gene_Allele, Gene_Variants, Allele_Identifiers, Gene_Expression, Expression_Gene — these have no SGD counterpart).

## Class C — single-template XML defects

| # | Template | Problem | Fix |
|---|---|---|---|
| 1 | Gene→Alleles (`Gene_Allele` line 73) | View selects `alleles.alleleId / alleleSymbol / alleleType` — AGR-only fields. Yeast SGD alleles populate `alleleSgdid / name / alleleClass`. CDC28 has 47 alleles total: 17 AGR-shape + 30 SGD-shape, the SGD 30 render as blank rows. | Use SGD-aware `Gene_Alleles` template at line 345 (already correct) — drop the AGR `Gene_Allele` for yeast users, or merge fields. |
| 2 | Allele→Identifiers (`Allele_Identifiers` line 9) | Default org=`D. rerio`, default alleleSymbol=`sa45217` (case-sensitive `=` not LOOKUP). Yeast SGD alleles use `name` not `alleleSymbol`. | Add yeast variant template; convert `=` to LOOKUP; default to no values. |
| 3 | Gene→Alleles and its Variants (`Gene_Variants` line 124) | Traverses `Gene.alleles.variants.*`. SGD alleles have no `variants` collection. | Add yeast variant or hide for non-AGR-MOD orgs. |
| 4 | Gene→Expression / Expression→Gene (lines 50, 90) | yeast has 13373 gene-expression links but most have null location/source/anatomy. Template has INNER constraint on `location` for Expression_Gene. | All sub-paths to OUTER joins; replace defaults with empty; per-org template variants. |
| 5 | Gene→Genomic DNA (line 105 AGR) | Missing systematicName/symbol cols, only primaryIdentifier. | Delete duplicate (Class B). The line 451 SGD version is correct. |
| 6 | Gene→Identifiers (line 110) | Default constraints set `D. rerio` + `fgf8a` + `*ZDB*` — three filters all editable but bad defaults for yeast. View misses `secondaryIdentifier`, `crossReferences.source.name`. | Add `Gene.secondaryIdentifier` and `Gene.crossReferences.source.name` to view. Replace defaults with `Saccharomyces cerevisiae` empty/wildcard. |
| 7 | Gene→UTRs (line 548) | Path `Gene.transcripts.UTRs.*` — yeast UTRs are linked via `utr.geneid` direct (35624 rows) but **not** linked through transcripts (sgd-gff-utr does not wire `transcript.UTRs`). | Rewrite path to `Gene.UTRs.*` direct, OR fix sgd-gff-utr converter to also attach UTR to MRNA. |
| 8 | Literature → Functional Complementation (line 592) | View shows `complements.complement.primaryIdentifier`, `.symbol`, `.crossReferences.identifier` — user reports cells blank but tooltip shows `HGNC:3208`. Probably `complement.primaryIdentifier` IS the HGNC string and `complement.symbol` is null for non-yeast complement targets. | Simplify columns: drop `.symbol` (null for HGNC), keep crossReferences with source.name suffix. |
| 9 | Retrieve→All intergenic regions (line 655) | Returns 0 — see Class A. Plus user requests adding `gene.status` and `gene.modDescription` to view, removing `briefDescription`. | After Class A fix, edit view: replace `briefDescription` with `description` and `status`. |
| 10 | Chromosomal Region→All genes (line 15) | Class B duplicate; AGR version filters `S. cerevisiae S288C` (no rows). | Delete duplicate. |
| 11 | Chromosome→Genes of a selected Feature Type (line 23) | Class B duplicate; defaults to fly. | Delete duplicate. |
| 12 | Gene→Flanking features within a specific distance (line 723) | `geneflankingregion` empty — see Class A. | After Class A fix, no template change needed. |

## Class D — yeast organism duplicate (data quality)

`organism` table has two rows with `shortName='S. cerevisiae'`:

| id | taxonid | gene count |
|---|---|---|
| 25000004 | 559292 (S288C reference strain) | 7964 |
| 32000001 | 4932 (legacy species-level NCBI taxon) | 4 |

Most templates use `Gene.organism.shortName='S. cerevisiae'` which matches both — not the failure mode for them. But some sources still tag yeast objects to taxon 4932 instead of 559292, causing **partial split** of yeast records. The four genes attached to 4932 are ghosts.

**Fix**: in fetchers / loaders, normalize taxon `4932` → `559292` (or vice-versa). Or: add a post-load cleanup query to remap `organismid` from 32000001 → 25000004 and delete the 32000001 row.

## Recommended execution order

1. **Now (no rebuild needed)**: edit `default-template-queries.xml` to delete the 5 duplicate AGR-style templates (Class B). Re-deploy WAR. This unlocks #10, #11 and unduplicates #5.
2. **Postprocess rerun (~30 min)**: uncomment 5 postprocess steps in `project.xml`, rerun `postprocess -Pprocess=...` for each, then `create-search-index` + `create-autocomplete-index`. Unlocks #5, #6 (intergenic), #9 (templates show data), #12 (flanking), #1 (introns IF populate-child-features actually generates them — needs verification).
3. **Template path edits (no rebuild)**: fix Class C #1 (Gene→Alleles → swap to SGD version), #6 (Gene→Identifiers cols), #7 (Gene→UTRs path), #8 (Literature complements), #9 (intergenic cols). Re-deploy WAR.
4. **Source loader work (rebuild required)**: #2-#4 (allele/variant yeast support), #7 (UTR-transcript link via converter fix), Class D (organism normalization). These are not for tonight.

## Verification queries

Before shipping any fix, confirm against rc20 DB:

```sql
-- After postprocess rerun
SELECT 'intergenic',count(*) FROM intergenicregion
UNION ALL SELECT 'flanking',count(*) FROM geneflankingregion
UNION ALL SELECT 'intron',count(*) FROM intron;
-- Expect: intergenic 5000+ (yeast only ~5800), flanking ~30000+, intron ~250 (yeast)

-- Yeast template smoke
SELECT count(*) FROM gene g JOIN organism o ON o.id=g.organismid WHERE o.taxonid='559292';
-- Expect ~7964 (matches existing)
```

## Files to edit

- `/root/alliancemine/project.xml` — Class A postprocess uncomment
- `/root/alliancemine/webapp/src/main/resources/default-template-queries.xml` — Classes B, C
- For source-loader fixes: upstream `alliance-genome/alliancemine` repo

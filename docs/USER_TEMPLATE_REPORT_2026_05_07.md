# User-reported template issues — 2026-05-07

Report received from a yeast curator testing AllianceMine 9.0.0 (live on
prod, rc18 backing DB). Used to diagnose and triage which issues are
fixed by the rc20 rebuild vs which need separate work.

## Triage table

| # | Template | Symptom | Cause class | rc20 fix? |
|---|---|---|---|---|
| 1 | Gene → Alleles | CDC28: 47 rows, 30 expected + 17 blank-value rows. Same for SAC1 | Placeholder Gene rows (alliance-genes load broken) cause Allele → Gene reference to point at stub Genes with no attributes. Hover shows real ID via reverse reference resolution; column path returns blank. | likely YES |
| 2 | Allele → Identifiers (yeast) | Returns no results | Multi-hop join through Allele.gene.organism — combination of placeholder Genes + planner bug | partial |
| 3 | Gene → Alleles and Variants (yeast) | Returns no results | Same multi-hop pattern as #2 | partial |
| 4 | Retrieve → All genes that have introns | "No results" — used to work | Gene → transcripts → introns (collection multi-hop). Sources `sgd-gff` / `sgd-gff-utr` populate yeast transcripts. Likely planner bug + possible postprocess gap. | needs verification post-rc20 |
| 5 | Literature → Complementation | Complement primary DBID, standard name, cross-refs all blank; HGNC visible only in hover | Complement source's link to Gene goes via reference; Gene records are placeholders → attributes blank in column path. | likely YES |
| 6 | Retrieve → All intergenic regions: missing 'status' / 'MOD description' columns; blank 'brief description' | webconfig-model.xml view config | view-config (separate from data) | NO — webconfig fix |
| 7 | Retrieve → All intergenic regions | Returns no results — used to work | Multi-hop traversal Gene ↔ IntergenicRegion + planner bug + maybe postprocess gap | likely YES |
| 8 | Gene → Expression | Returns no results | expressionannotation = 0 in DB (alliance-expression checkpoint dropped) | YES — fixed by re-run |
| 9 | Expression → Gene | Returns no results | Same as #8 | YES |
| 10 | Gene → Genomic DNA | Missing Systematic Name + Standard Name columns in result table | webconfig-model.xml view config | NO — webconfig fix |
| 11 | Gene → Identifiers | UX: have to set organism + Contains + leave text blank + change to SGD; result lacks Systematic Name + cross-ref type | template constraints + webconfig-model.xml view | NO — template + webconfig fix |
| 12 | Gene → UTRs (yeast) | Returns no rows for any input | Gene → transcripts → UTRs multi-hop. SGD UTRs come from sgd-db-utr / sgd-gff-utr; check those sources loaded. + planner bug | partial — need verify UTR sources after rc20 |
| 13 | Chromosomal Region → All genes (yeast) | Returns nothing with "S. cerevisiae S288C" but works with "S. cerevisiae" | Template constraint default uses long-form name; organism table shortname is "S. cerevisiae" | NO — template constraint fix |
| 14 | Chromosome → Genes of a selected Feature Type | Doesn't work for yeast | Feature Type dropdown matches against `Gene.featureType`. Yeast genes via SGD source may use SO ID format differing from BGI-derived genes (other MODs use SoTerm name like "protein_coding_gene"). | mostly YES — once Gene records are populated correctly |
| 15 | Gene → Flanking features within a specific distance | Doesn't appear to work for any inputs | Postprocess `do-sources` / `transfer-sequences` gap or `gene-flanking-region` postprocessor not run / failed | needs verification post-rc20 |

## Summary

| Category | Count |
|---|---|
| Fixed by rc20 rebuild (data restore) | ~6 issues |
| Needs webconfig-model.xml view edits (separate) | 3 issues |
| Needs template constraint edits (separate) | 2 issues |
| Needs upstream InterMine planner fix or workaround | 2-3 issues |
| Needs postprocess investigation | 2 issues |

## Plan after rc20 build completes

1. Re-run user-template smoke test against rc20 (script
   `template-smoke.sh` from earlier audit). Categorize by which still
   return empty.
2. For empty-but-data-loaded templates: inspect the SQL the planner
   generates (compare to direct SQL in psql) — multi-hop bug or filter
   issue.
3. For UI/display gaps: edit `webconfig-model.xml` in the alliancemine
   webapp source, rebuild WAR, redeploy.
4. For template constraint defaults: edit the relevant template XML
   under `webapp/src/main/webapp/template/`.

## Memory note

This same report should be re-run against rc20 to measure how many
issues data restoration alone fixed. Save the rc20 numbers for
side-by-side comparison.

# AllianceMine template design — multi-MOD data shape mismatch

Date: 2026-05-08
Status: needs groupwide discussion before any template fix lands

## Background

AllianceMine = YeastMine codebase + Alliance multi-MOD integration. Templates inherited from YeastMine were designed for SGD-shape data only. Alliance sources (alliance-genes, alliance-alleles, alliance-expression, alliance-disease, alliance-orthologs, alliance-phenotypes) introduce parallel-but-different field populations on the **same InterMine classes**.

Result: a single class like `Allele` carries two distinct schemas in production:

| Field | SGD source populates | AGR alliance-alleles populates |
|---|---|---|
| `primaryIdentifier` | yes | yes |
| `name` | yes (e.g. `cdc28-4`) | no |
| `allelesgdid` | yes | no |
| `alleleClass` | yes (e.g. `missense variant`) | no |
| `aliasName` | yes (e.g. `cdc28-6`) | no |
| `description` | yes | yes |
| `alleleId` | no | yes |
| `alleleSymbol` | no | yes |
| `alleleType` | no | yes |

Existing templates `view=` clauses select either SGD-side fields OR AGR-side fields. Either choice produces blank rows for the other source's records.

## Concrete example — CDC28

47 alleles in `alliancemine_9_0_0_rc20`:
- 30 SGD-source rows: `allelesgdid` set, `alleleId` NULL
- 17 AGR-source rows: `alleleId` set (homolog/orthology references), `allelesgdid` NULL

`Gene_Alleles` template selects only SGD cols → 17 AGR rows render with blank cols 5-10. User report describes exactly this: "30 expected + 17 blank".

## Same shape mismatch elsewhere

- **Expression**: `expressionAnnotation.location/source/sourceURL/stageTerm` populated by ZFIN/MGI/etc. Yeast SGD expression rows have most of those NULL but populate via `Gene.expressionannotationsgene` join with anatomy/cellularcomponent paths.
- **Variants**: `Gene.alleles.variants.*` collection only populated by alliance-variants for ZFIN. Yeast has no `variants` collection traversal at all.
- **Identifiers**: `Allele_Identifiers` selects `alleles.alleleSymbol` — fails on SGD where field is on `alleles.name`.
- **Chromosomal Region templates**: AGR-style version filters `S. cerevisiae S288C` (no DB row matches). SGD-style filters `S. cerevisiae`. These behave as **different defaults**, not duplicate templates. Both legitimate.

## The decision

This is a **design** question, not a bug. Three positions:

### Position 1 — yeast-canonical templates, hide AGR fields
Templates render only SGD-shape fields; alliance-alleles records hidden via `dataSets.name='SGD'` constraint or `allelesgdid IS NOT NULL`. AGR data still in DB for API/list export, just not in default UI templates.

Pro: clean tables, no blank rows, matches existing YeastMine UX.
Con: defeats the point of integrating Alliance data; users can't browse cross-MOD homolog alleles or non-yeast variants in the UI.

### Position 2 — AGR-canonical templates, expose Alliance-wide fields
Templates render only AGR-shape fields. SGD-shape becomes legacy. SgdConverter eventually maps `name→alleleSymbol`, `allelesgdid→alleleId`, etc.

Pro: single canonical schema across MODs.
Con: huge converter rewrite, breaks every saved query/list referencing SGD field names, breaks BlueGenes integrations.

### Position 3 — multiplex templates: render BOTH field sets
Templates have view-cols for both SGD and AGR triplets. Each row populates one set. Empty cells in unused-source columns are visible but unambiguous (col headers tell the user which schema produced the row).

Pro: no data loss, no converter rewrite, single template per concept.
Con: wider tables (~13 cols instead of 7), users see empty cells, cognitive load.

### Position 4 — per-organism template variants
Two templates per concept: `Gene_Alleles_SGD` (yeast-only, SGD shape) and `Gene_Alleles_AGR` (other MODs, AGR shape). Show both in UI with org filter visible in title.

Pro: each template is internally consistent. Power users self-select.
Con: doubles template count, splits the canonical "Gene → Alleles" link in the gene report page into two separate cards.

## Templates affected (rc20 audit, 2026-05-08)

Confirmed via REST against rc20 webapp:

1. `Gene_Allele` (line 73) / `Gene_Alleles` (line 345) — schema split: 47 alleles → 17 blank
2. `Allele_Identifiers` (line 9) — AGR-only fields, yeast users get nothing
3. `Gene_Variants` (line 124) — `variants` collection only from alliance-variants source
4. `Gene_Expression` / `Expression_Gene` (lines 50, 90) — assumes ZFIN-shape expressionAnnotation
5. `ChromosomeRegion_AllGenes` (lines 15, 219) — duplicate names with different defaults; AGR uses `S. cerevisiae S288C` (no match)
6. `Chromosome_Gene_FeatureType` (lines 23, 253) — duplicate; AGR defaults fly
7. `Gene_GenomicDNA` (lines 105, 451) — duplicate; AGR missing systematic/standard names
8. `Literature_GO` (lines 129, 610) / `Organism_Genes` (lines 134, 645) — duplicates; richness mismatch

## Out of scope for this discussion (still bugs, fix separately)

- intron/intergenicregion/geneflankingregion empty: postprocess steps commented out in `project.xml`. Pure config issue. Uncomment + rerun. Not multi-MOD.
- Yeast organism dup (`taxon 4932` 4 ghost genes alongside `taxon 559292` 7964 genes): data normalization, source-loader fix.
- `Gene_UTRs` path `Gene.transcripts.UTRs.*` returns 0 because sgd-gff-utr converter doesn't link UTR→transcript. SGD-internal converter bug, not multi-MOD design.
- `Literature_Complements` blank cols: probably field mapping in complement converter, not multi-MOD.

## Discussion items for the team

1. Pick Position 1 / 2 / 3 / 4 as default approach. Or hybrid (per-template choice).
2. If Position 4: agree on naming convention (`_SGD` suffix? `_Yeast` suffix? `_Alliance` suffix?).
3. If Position 3: agree on column ordering convention (SGD first, AGR after? interleaved by concept?).
4. Decide whether to keep duplicate template names (Position 4 → rename to disambiguate) or delete duplicates (Position 1/3 → keep one, drop the other).
5. Variants collection: ZFIN-only forever, or extend to other MODs as alliance-variants source coverage grows? Affects whether `Gene_Variants` template stays in default set.
6. BlueGenes/web embeds: do any external consumers query these templates by exact name? Renaming templates breaks them.

## Next steps

- Schedule discussion with SGD curators + Alliance bio-sources team.
- After decision: rewrite affected templates per chosen position, single PR to upstream `alliance-genome/alliancemine`.
- Until then: rc20 ships with current templates. Document the known schema-split behavior in the public release notes so users aren't surprised.

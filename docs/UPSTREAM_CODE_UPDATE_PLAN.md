# Upstream code-update plan — rc20 fixes → source repos

Pickup doc for a future Claude Code session to land the rc20 live fixes (currently in `alliancemine_userprofile.savedtemplatequery` rows + filesystem patches on live containers) into the source repositories so that future WAR builds inherit them as defaults.

**Status today:** 16 templates fixed live via saved-template REST upload + infra patches. Source XML files in `alliance-genome/alliancemine` master branch still hold the BROKEN versions. Without backporting, any reset of `alliancemine_userprofile` or any fresh build wipes the fixes.

**Goal of this plan:** produce 4-6 PRs to upstream that, once merged, replace all the per-session hand-patches with permanent source code.

## Repositories involved

```
alliance-genome/alliancemine                  # mine config + webapp + dbmodel
  branch: master (or wire-api-sources where commits already started)
  local checkout: /Users/nuin/Projects/alliance/alliancemine

alliance-genome/alliancemine-bio-sources      # source-loader converters
  branch: master
  local checkout: /Users/nuin/Projects/alliance/alliancemine-bio-sources
  (NOTE: may need to clone; verify before starting)

agr_intermine_builder (this repo)             # Dockerfile patches + project.xml override
  branch: development
  local checkout: /Users/nuin/Projects/alliance/agr_intermine_builder
```

## Reference data sources

- Live saved templates: query `alliancemine_userprofile.savedtemplatequery` on `intermine-postgres.cmnnhlso7wdi.us-east-1.rds.amazonaws.com`. Each row has `id`, `templatequery` (full XML), `userprofileid` (1000001 = superuser).
- WAR-baked defaults: `/root/alliancemine/webapp/src/main/resources/default-template-queries.xml` inside the running builder container `alliancemine-alliancemine-builder-run-c06d6908f14f` on AllianceMineDev. Compare each saved template against its WAR counterpart to derive the diff.
- Existing partial commit: sibling repo `/Users/nuin/Projects/alliance/alliancemine` already has commit `af455b1` on branch `wire-api-sources` covering Complex class_key + webconfig fieldconfig + taxonif typo. Extend, don't redo.

## PR 1 — class_keys.properties extension

**Repo:** `alliance-genome/alliancemine`
**File:** `dbmodel/resources/class_keys.properties`
**Already partly done in commit `af455b1` (Complex key + taxonid fix). Add Allele key extension on top.**

Current state in source (after `af455b1`):
```properties
Allele = alleleId, alleleSymbol
...
Organism = name, shortName, taxonid          # was taxonif (typo, fixed)
...
Complex = identifier, accession, name        # added
```

Apply this additional edit:
```diff
-Allele = alleleId, alleleSymbol
+Allele = alleleId, alleleSymbol, name, allelesgdid
```

Rationale: LOOKUP on `Gene.alleles` from the Allele_Identifiers template can't resolve yeast SGD allele names (`cdc28-4`) because they live in the `name` field, not `alleleSymbol`. Extending the class key lets LOOKUP work across both data shapes.

Verify after build:
```bash
PGPASSWORD=$RDS_PASSWORD psql -h $RDS_HOST -U postgres -d alliancemine_<release> \
  -c "SELECT count(*) FROM allele WHERE name LIKE 'cdc28%';"
# expect >0; LOOKUP with value 'cdc28-4' should now find rows
```

## PR 2 — webconfig-model.xml Complex fieldconfig reorder

Already in `af455b1` (sibling alliancemine repo). Submit as part of PR 1 or separately.

```diff
 <class className="org.intermine.model.bio.Complex" label="Molecular Complex">
     <fields>
         <fieldconfig fieldExpr="identifier" label="EBI Complex ID" />
         <fieldconfig fieldExpr="name" label="Complex Name" />
         <fieldconfig fieldExpr="function" label="Complex Function" />
-        <fieldconfig fieldExpr="properties" label="Complex Properties" />
+
         <fieldconfig fieldExpr="systematicName" label="Complex Systematic Name" />
+        <fieldconfig fieldExpr="properties" label="Complex Properties" />
         <fieldconfig fieldExpr="goAnnotation" label="Complex GO Annotation" />
         <fieldconfig fieldExpr="publications" label="Complex Publications" />
     </fields>
 </class>
```

Rationale: default Complex list view picks first attribute fieldconfigs as visible columns; with `properties` (long-text) ahead of `systematicName`, useful columns get hidden. Move `systematicName` up.

## PR 3 — default-template-queries.xml batch (16 templates)

**Repo:** `alliance-genome/alliancemine`
**File:** `webapp/src/main/resources/default-template-queries.xml`

For each template below, pull the live body from `savedtemplatequery` and replace the WAR XML block. Procedure:

```bash
ssh AllianceMineDev
docker exec alliancemine-alliancemine-builder-run-c06d6908f14f bash -lc \
  "PGPASSWORD=\$RDS_PASSWORD psql -h \$RDS_HOST -U \$RDS_USER -d alliancemine_userprofile -A -t \
   -c \"SELECT templatequery FROM savedtemplatequery WHERE templatequery LIKE \
        '<template name=\\\"<NAME>\\\"%';\""
```

Then in the local `alliance-genome/alliancemine` clone, find the matching `<template name="<NAME>">...</template>` block in `default-template-queries.xml` and replace.

Templates to backport (each has a saved row in `alliancemine_userprofile`):

| Template | Saved row contains | Verify with |
|---|---|---|
| `Gene_Alleles` | View extended with `alleles.alleleId/alleleSymbol/alleleType` (14 cols, 14 dataTypes) | Count CDC28 → 47 rows, no blank trios |
| `Allele_Identifiers` | 12-col multiplex view + `Gene.alleles LOOKUP cdc28-4` + S. cerevisiae default | Count yeast `cdc28-4` → ~1500 |
| `Literature_Complements` | 9-col view, dropped `complement.symbol` + `complement.crossReferences.*`; added `complement.secondaryIdentifier` | Count default PMID → ~2866 with HGNC visible col 5 |
| `Deleted_Merged_Features_Tab` | 11-col view with `Gene.status` + `Gene.modDescription`; dropped `Gene.briefDescription`; OUTER joins on chromosome / location | Count → 98 |
| `Gene_Expression` | Default LOOKUP `CDC28` instead of `fgf8b` | LOOKUP CDC28 → 6 |
| `Expression_Gene` | Default `Gene.expressionAnnotations.location CONTAINS cytoplasm` | Count → 5919 |
| `Gene_GenomicDNA` | SGD-style 10-col body (sgdAlias, secondaryIdentifier, symbol); delete the duplicate AGR template at line 105 | LOOKUP CDC28 → 1 |
| `Gene_Identifiers` | View + `Gene.secondaryIdentifier` + `Gene.crossReferences.source.name`; defaults `S. cerevisiae` / `*` / `SGD` | yeast SGD → 5587 |
| `Gene_UTRs` | Path rewrite `Gene.transcripts.UTRs.*` → `Gene.UTRs.*`; dropped `Gene.UTRs.sequence.residues`; OUTER join on `Gene.UTRs.chromosomeLocation` | LOOKUP CDC28 → 4 |
| `ChromosomeRegion_AllGenes` | Default org `S. cerevisiae` with `CONTAINS` (was `=` value `S. cerevisiae S288C`). **Also delete the AGR-style duplicate at line 15** so the SGD version at line 219 wins (or just keep one) | yeast chrXIV 1-20000 → 12 |
| `Chromosome_Gene_FeatureType` | Defaults yeast/chrI/ORF. **Delete AGR duplicate at line 23**. | yeast chrI ORF → 117 |
| `Organism_Genes` | Default org `S. cerevisiae` with `CONTAINS`. **Delete AGR duplicate at line 134**. | yeast → 7260 |
| `Complex_Details_Participant` | Accession constraint switchable=ON; name constraint switchable=OFF (so AND'd defaults don't return empty intersection) | CPX-599 → 45 |
| `GoSlimTerm_Gene` | Dropped annotType filter (data is NULL for all 252,607 GOEvidenceCode rows — see PR 5) | DNA binding → 43534 |
| `GO_Terms_Tab` | Default `namespace = biological_process` (was empty ONE OF list) | biological_process → 24435 |
| `Gene_Variants` | longDescription updated to note yeast variants not loaded; otherwise unchanged | ZFIN default → 5 |

For each block, replace in the source XML. Use the saved body as the canonical text — already verified working.

## PR 4 — project.xml uncomment postprocess block

**Repo:** `alliance-genome/alliancemine`
**File:** `project.xml`

```diff
   <post-processing>
     <post-process name="create-references"/>
     <post-process name="do-sources"/>
-    <!--<post-process name="create-intergenic-region-features"/>
-    <post-process name="create-location-overlap-index"/>
-    <post-process name="create-overlap-view"/>
-    <post-process name="create-gene-flanking-features"/>
-    <post-process name="populate-child-features"/>-->
+    <post-process name="create-intergenic-region-features"/>
+    <post-process name="create-location-overlap-index"/>
+    <post-process name="create-overlap-view"/>
+    <post-process name="create-gene-flanking-features"/>
+    <post-process name="populate-child-features"/>
     <post-process name="transfer-sequences"/>
     <post-process name="create-attribute-indexes"/>
     <post-process name="summarise-objectstore"/>
     <post-process name="create-autocomplete-index"/>
     <post-process name="create-search-index"/>
   </post-processing>
```

Rationale: without these 5 steps the `intergenicregion` and `geneflankingregion` tables stay empty, breaking Retrieve→All intergenic regions / Gene→Flanking features templates.

Same edit also needed in `agr_intermine_builder/docker/alliancemine/project.xml` (already done locally — uncommit not yet pushed; verify via `git status` in that repo).

Verify after build:
```sql
SELECT 'intergenic',count(*) FROM intergenicregion
UNION ALL SELECT 'flanking',count(*) FROM geneflankingregion;
-- expect intergenic ~6000, flanking ~145000 for yeast-heavy build
```

## PR 5 — converter / source-loader fixes (separate repo)

**Repo:** `alliance-genome/alliancemine-bio-sources`
**Files / changes:**

### 5a. `sgd-gff-utr` converter — wire UTR sequence

UTR Items currently have `gene` reference set but `sequence` reference is null. `Gene.UTRs.sequence.residues` path returns 0 rows because the sequence link is missing. Fix:

```
sgd-gff-utr/src/main/java/org/intermine/bio/dataconversion/SgdGffUtrConverter.java
```
In the per-feature loop, when constructing each UTR Item, also create or look up a Sequence Item from the GFF sequence field and `setReference("sequence", seqItem)`.

Verify: after rerun of sgd-gff-utr source + integrate, query `SELECT count(*) FROM utr WHERE sequenceid IS NOT NULL` — expect >0.

Then revert the Gene_UTRs template to include `Gene.UTRs.sequence.residues` in the view.

### 5b. `alliance-alleles` converter — dedupe vs SGD source

Currently loads AGR-shape allele records (`alleleId/alleleSymbol/alleleType`) including duplicates of yeast SGD alleles (e.g. CDC28 gets 17 AGR-shape duplicates of its 30 SGD-shape alleles). Fix:

```
alliance-alleles/src/main/java/org/intermine/bio/dataconversion/AllianceAllelesConverter.java
```
Before emitting an Allele Item, check if an existing Allele in the integration store already has matching `primaryIdentifier`. If yes, skip emit (let SGD-source data win). Alternative: emit but `setAttribute("dataSet", ...)` so downstream queries can filter.

Verify after rebuild:
```sql
SELECT count(*) FROM allele a JOIN gene g ON a.geneid=g.id WHERE g.symbol='CDC28';
-- before fix: 47; after fix: 30 (SGD-only)
```

### 5c. `go-annotation` converter — populate annotType

`GOEvidenceCode.annotType` is NULL for all 252,607 rows in rc20. Should be `manually curated` or `high-throughput` based on the evidence code. Fix:

```
go-annotation/src/main/java/org/intermine/bio/dataconversion/GoAnnotationConverter.java
```
Build a static map of GO evidence codes → annotType category (IDA/IPI/IGI/IMP/EXP = "manually curated"; HDA/HEP/HMP/HGI = "high-throughput"; ISS/IBA/etc = "computational analysis"). Set when emitting GOEvidenceCode Items.

Verify:
```sql
SELECT annottype, count(*) FROM goevidencecode GROUP BY annottype;
-- expect non-NULL values
```

Then re-add the annotType filter to GoSlimTerm_Gene template constraintLogic.

### 5d. Intron source — TBD

Yeast intron data was loaded in 8.3.0 (348 rows) but not in 9.0.0. Identify source via 8.3.0 audit:
```sql
\c alliancemine_8_3_0
SELECT i.primaryidentifier, d.name AS dataset
FROM intron i
JOIN bioentitiesdatasets bd ON bd.bioentities = i.id
JOIN dataset d ON d.id = bd.datasets
LIMIT 5;
```

Add the identified source to `alliance-genome/alliancemine/project.xml`. See `docs/INTRON_LOADING_GAP.md` for full options.

### 5e. Organism normalization

Two yeast `organism` rows: taxon 559292 (correct) + 4932 (legacy). 4 yeast genes orphaned on 4932. Fix in fetcher (whichever source loads them — likely `alliance-genes` extractor): map taxonid `4932 → 559292` during emission.

```
scripts/fetch_genes.py (or wherever)
```
Add normalization function:
```python
def normalize_taxonid(t):
    if t in ("4932", "NCBITaxon:4932"):
        return "NCBITaxon:559292"
    return t
```

Verify:
```sql
SELECT taxonid, count(*) FROM organism WHERE taxonid IN ('559292','4932') GROUP BY taxonid;
-- expect single row for 559292 with all 7964+4 genes
```

## PR 6 — agr_intermine_builder Dockerfile extension

**Repo:** `agr_intermine_builder` (this repo)
**File:** `docker/alliancemine/Dockerfile`

Already has Complex class_keys + webconfig + taxonif patches (commit `581d7cb`). Extend the existing class_keys RUN block to add Allele extension:

```diff
 RUN sed -i 's/taxonif/taxonid/' /root/alliancemine/dbmodel/resources/class_keys.properties && \
+    sed -i 's/^Allele = alleleId, alleleSymbol$/Allele = alleleId, alleleSymbol, name, allelesgdid/' \
+        /root/alliancemine/dbmodel/resources/class_keys.properties && \
     grep -q '^Complex' /root/alliancemine/dbmodel/resources/class_keys.properties || \
     printf '\nComplex = identifier, accession, name\n' >> /root/alliancemine/dbmodel/resources/class_keys.properties
```

This way the Allele class key extension is baked into every fresh image until PR 1 lands upstream.

## Execution order recommendation

1. **PR 4** (project.xml postprocess uncomment) — smallest, no schema risk. Land first.
2. **PR 1 + PR 2** (class_keys + webconfig) — already partly in `af455b1`. Land together.
3. **PR 3** (template XML batch) — large but mechanical. Could split per-template into smaller PRs if reviewers prefer.
4. **PR 6** (Dockerfile patch extension) — local repo only, no external review.
5. **PR 5** (converters in alliancemine-bio-sources) — most invasive. Land 5a-5e separately, each with its own audit + test.

After PR 1-4 + 6 merge: a fresh build will inherit all template fixes as WAR defaults. Saved-template DB rows become redundant (but harmless).

After PR 5 lands and rebuild: live RDS allele/intron/UTR/annotType data populates correctly, removing the workarounds that were needed in PR 3.

## Verification full-cycle

After all PRs and a rebuild + redeploy:

```bash
# Templates default-on-render
for t in Gene_Alleles Allele_Identifiers Literature_Complements Deleted_Merged_Features_Tab \
         Gene_Expression Expression_Gene Gene_GenomicDNA Gene_Identifiers Gene_UTRs \
         ChromosomeRegion_AllGenes Chromosome_Gene_FeatureType Organism_Genes \
         Complex_Details_Participant GoSlimTerm_Gene GO_Terms_Tab Gene_Variants; do
  echo -n "$t: "
  curl -s "http://<new-host>:<port>/alliancemine/service/template/results?name=$t&format=count" 2>&1
done
```

Expected counts (with default constraints, see status doc for specific param values):
- All 16 should return non-zero except Gene_Variants which returns 5 only for ZFIN-shape data.

Plus DB sanity:
```sql
SELECT 'genes',count(*) FROM gene
UNION ALL SELECT 'alleles',count(*) FROM allele
UNION ALL SELECT 'introns',count(*) FROM intron
UNION ALL SELECT 'intergenic',count(*) FROM intergenicregion
UNION ALL SELECT 'flanking',count(*) FROM geneflankingregion;
-- expect: genes ~460000, alleles depends on 5b, introns >0 if 5d, intergenic ~6000, flanking ~145000
```

## State at session handover

- Live 8086 webapp serves all 16 fixed templates correctly via saved-template rows in `alliancemine_userprofile.savedtemplatequery`. Verified working as of this doc's date.
- Source XML in builder + source XML in `alliance-genome/alliancemine` remain unpatched for the 16 templates.
- Builder source `class_keys.properties` patched in-container for Complex + taxonif + Allele yeast fields. Dockerfile RUN block has Complex + taxonif (commit 581d7cb); needs Allele extension (PR 6 above).
- Builder source `webconfig-model.xml` patched in-container for Complex fieldconfig. Dockerfile RUN block has it (commit 581d7cb).
- Builder source `project.xml` patched in-container (postprocess uncommented). In-repo file patched, uncommitted.
- 5 postprocess steps re-run successfully against rc20 DB → populated 6386 intergenic + 145160 flanking rows.
- Solr cores `-rc20` populated via cp from `-9.0.0` core (manual recovery; not relevant to source PRs).
- RDS scaled t3.xlarge → r6i.xlarge with shared_buffers 8 GB. Operational state only; not in any code PR.

## Reference

- Verification counts and per-template diffs: `docs/RC20_TEMPLATE_FIX_STATUS_2026_05_12.md`
- Session play-by-play: `docs/SESSION_LOG_2026_05_11.md`
- Intron data gap: `docs/INTRON_LOADING_GAP.md`
- Multi-MOD design discussion (informs PR 3 Gene_Alleles + Allele_Identifiers shape decisions): `docs/TEMPLATE_DESIGN_MULTIMOD_DISCUSSION.md`
- Existing partial commit in alliancemine repo: `af455b1` on `wire-api-sources`
- Existing Dockerfile commits in this repo: `398122a`, `581d7cb`, `6750da8`, `b92ff4e`, `abbbfc5`, `785d154` on `development`

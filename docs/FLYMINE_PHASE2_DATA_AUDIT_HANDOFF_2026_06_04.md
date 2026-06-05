# Phase 2 data audit — gaps vs agr_stock Phase 2 aims

**Date:** 2026-06-04
**From:** agr_intermine_builder session
**To:** new_flymine session
**Re:** Data-side coverage of `agr_stock/docs/plans/2026-05-22-bdsc-phase2-specific-aims.md`. Phase 2 round 2 build still firing (`flybase-allele-stubs` integrate pending) — this audit looks at what's missing from the FlyMine schema regardless of round 2's outcome.

---

## 1. TL;DR — three new bio-sources needed

To hit Aims 1–3 the FlyMine schema needs three entity classes we don't currently load:

| Source request | chado FlyBase count | Aim impact | Data already on disk? |
|---|---|---|---|
| **`flybase-insertions`** (FBti) | **420,755** | Aim 2 cross-class queries, Aim 3 ID converter | ✅ `precomputed_files/insertions/insertion_mapping_fb_2026_01.tsv` (28 MB) |
| **`flybase-transgenic-constructs`** (FBtp) | **173,232** | Aim 2 (transgenes — core promise), Aim 4 BDSC stock pages | ✅ `precomputed_files/transposons/transgenic_construct_descriptions_fb_2026_01.tsv` (6 MB) |
| **`flybase-breakpoints`** (FBbs) — optional | 12,657 | Aim 1 (`cytologicalBreakpoints` schema exists but unpopulated) | partial — `precomputed_files/map_conversion/cyto-genetic-seq.tsv` |

Plus one chado-side restoration: **phenstatement + library_* tables** (dropped during the 2026-06-02 disk-fill crisis on AllianceMineDev) — needed for Aim 1's `complementationResults` once the chado-team cvterm work lands.

---

## 2. Phase 2 aim coverage as it stands

### Aim 1 — FBab/FBba pages

| Need | Have | Gap |
|---|---|---|
| FBab/FBba ingest as Allele subclasses | ✅ 23,870 + 644 | — |
| `deletedGenes` / `duplicatedGenes` collections | ✅ 41,295 / 3,629 | — |
| `composedOfAberrations` collection | ✅ schema, 0 rows | sibling's `fbba_to_fbab.tsv` seed has empty rows on purpose |
| `carriedAlleles` collection | ✅ schema, 0 rows | chado `derived_tp_assoc_alleles` rel has 168,252 rows ready; need converter SQL + cvterm confirmation |
| `complementationResults` collection | ✅ schema, 0 rows | chado `phenstatement` table needed — **dropped from chado-pg this session, restoration needed** |
| `cytologicalBreakpoints` collection | ✅ schema, 0 rows | chado FBbs feature has 12,657 rows; need converter SQL |

### Aim 2 — Stock-focused mine + cross-class queries

| Need | Have | Gap |
|---|---|---|
| Stocks (FBst) | ✅ 122,066 | — |
| Genes (FBgn) | ✅ 148,066 | — |
| Alleles (FBal) | ✅ 234,211 → ~300K (after round 2's `flybase-allele-stubs`) | covered |
| **Insertions (FBti)** | ❌ ~0 | **`flybase-insertions` source needed — 420,755 rows in chado** |
| **Transgenes / constructs (FBtp)** | ❌ ~0 | **`flybase-transgenic-constructs` source needed — 173,232 rows** |
| Aberrations (FBab) | ✅ 23,870 | — |
| Balancers (FBba) | ✅ 644 | — |
| `Stock.genotype` text field | unknown | **verify after round 2 build finishes** — needed for Aim 4 named queries |
| Synonyms (gene/allele aliases) | likely ✅ via chado FlyBaseProcessor | **verify count after round 2 build** |
| CG-number resolution | likely via `Gene.secondaryIdentifier` or `Synonym` | **verify after round 2 build** |

The "stocks × transgenes × genes × insertion sites" core promise of Aim 2 is not deliverable until both **`flybase-insertions`** and **`flybase-transgenic-constructs`** sources land.

### Aim 3 — Batch download + ID converter

ID converter input spec (from agr_stock Phase 2 §Aim 3):

| Input prefix | Have in FlyMine | Need |
|---|---|---|
| FBgn | ✅ | — |
| FBal | ✅ (after round 2 — 300K) | — |
| **FBti** | ❌ | `flybase-insertions` source |
| FBab | ✅ | — |
| FBba | ✅ | — |
| symbol / synonym | likely ✅ via chado | **verify Synonym count** |
| CG-number | likely ✅ via secondary identifier | **verify after round 2** |

Without `flybase-insertions`, the ID converter rejects FBti inputs.

### Aim 4 — BDSC integration

Named queries Aim 4 lists (Phase 2 §Aim 4 bullet 1):

- **stock additions** — needs `Stock` + `Stock.genotype` parsing → verify Stock.genotype loads
- **synonym audits** — needs `Synonym` → verify
- **balancer composition** — needs `Balancer.composedOfAberrations` → we have schema, 0 rows until curated table populated
- **FBab/FBba resolution** — needs Aim 1 pages live (i.e. Tomcat deployment) + the entities (we have them)

---

## 3. Source spec 1 — `flybase-insertions`

### Why

FlyBase ships 420K FBti insertion records. They're how transgenic stocks are anchored to genomic locations. Without them:
- Aim 2 cross-class "stocks × insertion sites" queries return empty.
- Aim 3 ID converter has no FBti resolution.
- Stock genotype parsing (BDSC's Phase 1 output) can't link insertion IDs back to genomic context.

### Input file

`/root/data/flybase/insertions/current/insertion_mapping_fb_2026_01.tsv` (already on disk, ~28 MB).

```
##fbti_id	symbol	genomic_location	range	orientation	estimated_cytogenetic_location	observed_cytogenetic_location
FBti0000001	P{lacW}gukh[k08210]	2L:7,238,500..7,238,500	2L:7238500-7238500	+	24A2-24A2	24A2-24A2
...
```

### Source wiring

```xml
<source name="flybase-insertions" type="flybase-insertions" version="4.2.0">
  <property name="src.data.dir" location="/root/data/flybase/insertions/current"/>
  <property name="src.data.dir.includes" value="insertion_mapping_*.tsv"/>
</source>
```

### Schema additions

InterMine genomic model already has `TransposableElementInsertionSite` (extends `Insertion` extends `SequenceFeature`). No additions needed; just verify the class is in the loaded model after this source compiles.

If the class isn't there, add:
```xml
<class name="TransposableElementInsertionSite" extends="Insertion" is-interface="true">
  <attribute name="cytogeneticLocation" type="java.lang.String"/>
</class>
```

### Converter scope

Per row:
- col 1 (FBti) → `TransposableElementInsertionSite.primaryIdentifier`
- col 2 (symbol like `P{lacW}gukh[k08210]`) → `.symbol`
- col 3 (genomic_location like `2L:7238500..7238500`) → parse into `chromosomeLocation` reference (a `Location` item with `Chromosome` ref + `start`/`end`)
- col 4 (range) → `range` attribute
- col 5 (orientation `+`/`-`) → `Location.strand`
- col 6 (estimated cytological) → `cytogeneticLocation`
- col 7 (observed cytological) → ignored or added as second attr
- Organism = Dmel/7227 for all rows
- Header rows starting with `##` skipped

### keys.properties

```properties
DataSet.key                          = name
DataSource.key                       = name
Organism.key                         = taxonId
TransposableElementInsertionSite.key = primaryIdentifier
Chromosome.key                       = primaryIdentifier
```

### Expected counts

420,755 new `TransposableElementInsertionSite` rows + ~5-10 MB DB delta. No new Gene rows (FBti's gene linkage comes via chado feature_relationship, separate Phase 3 work).

### Tests

1. `testInsertionsCreated` — fixture with 4 valid rows → 4 inserts + 4 Location items
2. `testHeaderRowsSkipped`
3. `testChromosomeLocationParsed` — assert `chromosomeLocation.start = 7238500`
4. `testOrientationStrand` — assert `Location.strand = "1"` for `+`, `"-1"` for `-`

---

## 4. Source spec 2 — `flybase-transgenic-constructs`

### Why

FlyBase ships 173K FBtp transgenic constructs (the "{lacW}", "{UAS-X}", "{Gal4-Y}" et al. — the actual molecular tools used to make transgenic stocks). Without them Aim 2's "transgenes" entity is empty; every stock that uses a transgene becomes orphan-referenced.

### Input file

`/root/data/flybase/transposons/current/transgenic_construct_descriptions_fb_2026_01.tsv` (already on disk, ~6 MB).

```
## FlyBase Transgenic Construct Data Report
## Generated: ...
#construct_FBtp_id	construct_symbol	encoded_features	encoded_features_ids	related_FBti	related_FBti_ids
FBtp0000001	P{lacW}	lacZ; w[+mC]; ...	FBgn0014447; FBgn0003996	P{lacW}gukh[k08210]; ...	FBti0000001; ...
...
```

### Source wiring

```xml
<source name="flybase-transgenic-constructs" type="flybase-transgenic-constructs" version="4.2.0">
  <property name="src.data.dir" location="/root/data/flybase/transposons/current"/>
  <property name="src.data.dir.includes" value="transgenic_construct_descriptions_*.tsv"/>
</source>
```

### Schema additions

InterMine genomic model has `TransgenicConstruct` (or similar — verify). If not, add:

```xml
<class name="TransgenicConstruct" extends="BioEntity" is-interface="true">
  <attribute name="symbol" type="java.lang.String"/>
  <attribute name="description" type="java.lang.String"/>
  <collection name="encodedGenes" referenced-type="Gene"/>
  <collection name="relatedInsertions" referenced-type="TransposableElementInsertionSite"/>
</class>

<!-- reverse refs on Gene and TransposableElementInsertionSite -->
<class name="Gene" is-interface="true">
  <collection name="encodedByConstructs" referenced-type="TransgenicConstruct"
              reverse-reference="encodedGenes"/>
</class>
```

### Converter scope

Per row:
- col 1 (FBtp) → `TransgenicConstruct.primaryIdentifier`
- col 2 (symbol like `P{lacW}`) → `.symbol`
- col 3 (encoded features list, semicolon-separated) → `.description` (free-text) AND
- col 4 (encoded FBgn list, semicolon-separated) → `encodedGenes` collection via FBgn merge
- col 5 (related FBti list) → `relatedInsertions` collection via FBti merge
- col 6 (related FBti IDs) — alternative for col 5 parsing
- Organism = Dmel/7227

### keys.properties

```properties
DataSet.key              = name
DataSource.key           = name
Organism.key             = taxonId
Gene.key                 = primaryIdentifier
TransgenicConstruct.key  = primaryIdentifier
TransposableElementInsertionSite.key = primaryIdentifier
```

### Expected counts

173,232 new `TransgenicConstruct` rows + ~5 MB DB delta. Gene merges into chado's 17,884 Dmel genes; insertion merges depend on `flybase-insertions` running first.

### Tests

1. `testConstructsCreated`
2. `testEncodedGenesParsed` — pipe-split FBgn list, merge into existing Gene
3. `testRelatedInsertionsParsed` — pipe-split FBti list
4. `testHeaderRowsSkipped`

**Source ordering note**: `flybase-transgenic-constructs` must run AFTER `flybase-insertions` so the FBti references resolve. Place after `flybase-insertions` in project.xml.

---

## 5. Optional source 3 — `flybase-breakpoints`

Lower-priority for Aim 1 since the converter SQL approach is preferred (read directly from chado). But if chado-team cvterm confirmation drags, a TSV-based fallback would deliver `Aberration.cytologicalBreakpoints` from `precomputed_files/map_conversion/cyto-genetic-seq.tsv` (already on disk).

12,657 FBbs records in chado. Skip for now; revisit if Aim 1 SQL stalls past wk 9.

---

## 6. chado-side restoration — phenstatement + library_*

During 2026-06-02 disk-fill crisis on AllianceMineDev I dropped these chado tables to recover space:

```
phenstatement, phenotype, phenotype_cvterm, phenotype_comparison*, library_*
```

For Aim 1's `complementationResults` converter (your spec waiting on cvterm confirmation), the `phenstatement` table is the source of truth. Restoration paths:

1. **Re-download chado dump + selective restore** — re-fetch `FB2026_01.sql.gz` (16 GB compressed), use `pg_restore -L` to extract only the dropped tables. ETA 30 min download + 1-2 hr restore.
2. **Targeted pg_dump from a FlyBase mirror** — if AGR has access to FlyBase's chado pg directly (Cambridge, Harvard mirrors), pg_dump just the dropped tables.
3. **Skip phenstatement entirely** — express complementation via the chado-allele-descriptions seed table approach you used for `fbba_to_fbab.tsv`. Manual curation. Higher cost long-term.

Suggest option 1 once disk pressure allows; we currently have 46 GB free on AllianceMineDev and the chado-pg volume is 109 GB; restoration would push ~+30 GB.

Optional: I can encode the selective-restore command in `extract_data.py` so future cold builds re-fetch and restore the dropped tables automatically.

---

## 7. Aim 2/3/4 verification queries (run after round 2 build wraps)

```sql
-- Stock.genotype field populated?
SELECT count(*), count(genotype) FROM stock;

-- Synonym entities loaded? (Aim 3 ID converter)
SELECT count(*) FROM synonym;
SELECT count(*) FROM synonym WHERE value LIKE 'CG%';  -- CG-number resolution

-- Gene.secondaryIdentifier populated with CG numbers?
SELECT count(*) FROM gene WHERE secondaryidentifier LIKE 'CG%';

-- Allele.symbol pattern check (Aim 3 ID converter symbol input)
SELECT count(DISTINCT symbol) FROM allele;
```

If `Synonym` is empty or low, chado FlyBaseProcessor may not be loading them and we need a `flybase-synonyms` source too. If `Stock.genotype` is null, chado StockProcessor doesn't capture genotype text — bigger problem for Aim 4 named queries.

---

## 8. Updated active source projection

| Round | Active sources | New entities | DB size projection |
|---|---|---|---|
| Phase 2 round 1 | 24 | — | 19 GB |
| **Phase 2 round 2 (in flight)** | **25** | +66K `Allele` stubs, +2-4K non-Dmel Drosophila alleles | **~20 GB** |
| **+ `flybase-insertions`** | 26 | +420K `TransposableElementInsertionSite` | ~25 GB |
| **+ `flybase-transgenic-constructs`** | 27 | +173K `TransgenicConstruct` | ~27 GB |
| + chado phenstatement restored + Aim 1 SQL | 27 | (populates existing schema collections, no new entities) | ~28 GB |

Phase 2 full data target: **~28 GB** (still far below the 80-100 GB "complete" target since protein2ipr / flybase-alleles legacy / fly-anatomy-ontology remain disabled).

---

## 9. Cross-references

- agr_stock Phase 2 aims: `agr_stock/docs/plans/2026-05-22-bdsc-phase2-specific-aims.md`
- Your Aim 1 scoping: `new_flymine/docs/HANDOFF_BUILDER_PHASE2_AIM1_2026-06-02.md`
- Your round-2 reply: `new_flymine/docs/HANDOFF_TO_BUILDER_PHASE2_ROUND2_2026-06-04.md`
- Builder Phase 2 findings (round 1): `agr_intermine_builder/docs/FLYMINE_PHASE2_FINDINGS_HANDOFF_2026_06_04.md`
- Active build state: project_build round 2 firing, watcher `bu9q8izkv`

Ready for round 3 when you are. Suggest tackling `flybase-insertions` first since FBti unblocks both Aim 2 cross-class queries and Aim 3 ID converter.

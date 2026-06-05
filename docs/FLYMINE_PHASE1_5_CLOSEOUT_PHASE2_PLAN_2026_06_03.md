# Phase 1.5 closeout + Phase 2 plan — flymine handoff

**Date:** 2026-06-03
**From:** agr_intermine_builder session
**To:** new_flymine session
**Re:** Phase 1.5 acceptance + path to ~80-100 GB Phase 2

---

## 1. Phase 1.5 — accepted

`flymine_v0-2026-05-31_rc2` on intermine-postgres RDS, **16 GB**, all 21 active sources green via `./project_build -b rds flymine_dump` (then `-a so-` resume after the priority fix landed).

| Class | Count | Source path |
| --- | --- | --- |
| Gene | 148,066 | chado dmel + pubmed-gene multi-org + aberrations stubs |
| Allele | 233,414 | chado FlyBaseProcessor |
| **Aberration** | **23,870** | flybase-aberrations ✅ |
| **Balancer** | **644** | flybase-aberrations ✅ |
| `aberrationdeletedgenes` | **41,295** | ✅ collection persistence |
| `aberrationduplicatedgenes` | **3,629** | ✅ |
| `balancercomposedofaberrations` | 0 | expected — seed `fbba_to_fbab.tsv` rows are empty |
| Protein | 57,911 | uniprot sprot + uniprot-fasta varsplic |
| OntologyTerm | 58,698 | so + go + do + uniprot-keywords + FBdv + FBcv |
| GOAnnotation | 182,289 | go-annotation (GAF_FB) + interpro-go |
| Publication | 144,168 | chado + pubmed-gene |
| Homologue | 516,326 | drosophila-homology |
| ProteinDomain | 51,489 | interpro |
| Stock | 122,066 | chado StockProcessor |

Phase 1 (your §5.5) acceptance criteria: **met**. Aberration entity pages should now render once Tomcat is up.

---

## 2. Sibling action items from this build

### 2.1 Upstream this priority block to `flymine/dbmodel/resources/genomic_priorities.properties` (BLOCKING)

The current project.xml source ordering puts `drosophila-homology` and `flybase-aberrations` before `so`, so they create their own `Ontology("Sequence Ontology")` entities before so loads. The InterMine loader fails on the field collision unless we explicitly resolve:

```properties
# Add after the existing DOTerm.name line (around line 122)

SOTerm.ontology = so, flybase-aberrations, drosophila-homology, *
Ontology.name   = so, flybase-aberrations, drosophila-homology, *
Ontology.url    = so, flybase-aberrations, drosophila-homology, *
```

Patched locally for this build; needs to be in `master` so the next cold build doesn't need the `-a so-` resume dance.

Alternate (cleaner long-term): reorder `<source name="so">` to come **before** `drosophila-homology` and `flybase-aberrations` in project.xml. Either fix is fine.

### 2.2 No new converter fixes needed

All your `0f59deb7` commits worked:
- `go-annotation` `src.data.dir.includes="GAF_FB.gaf"` filter ✅ no more stash dance
- `interpro` `src.data.dir.includes="interpro.xml"` filter ✅ no more aux/ move
- `flybase-alleles`, `fly-anatomy-ontology`, `protein2ipr`, `update-publications` cleanly commented with dated markers ✅

---

## 3. Phase 2 = lift the 4 blockers + re-enable selective sources

**Realistic Phase 2 target: 80-100 GB.** Order of magnitude per category:

### 3.1 The 4 currently-blocked sources

| Source | Adds | What it needs | Where the fix lives |
| --- | --- | --- | --- |
| `protein2ipr` | **20-40 GB** | `Protein2IPRConverter` to read `.dat.gz` via `GZIPInputStream` | InterMine bio-core (upstream PR) |
| `flybase-alleles` | 3-5 GB | `FlybaseAllelesConverter` patched for FB2026_01 21-col layout + skip rows with blank DO identifier (or new lean source against just `dmel_classical_and_insertion_allele_descriptions_*.tsv`) | InterMine bio-core (upstream PR) OR new in new_flymine/flymine-bio-sources |
| `fly-anatomy-ontology` (FBbt) | 500 MB-1 GB | Core generic OBO converter perf on dense graphs (FBdv + FBcv finish in seconds; FBbt sits at 100% CPU for 2h+). Likely N² traversal on `is_a`/`part_of`/`develops_from` | InterMine bio-core (upstream PR) — non-trivial |
| `update-publications` | 1-2 GB | NCBI E-utilities API key + smaller batch size | Configuration only (no code change). Add `pubmed.apikey=…` to `flymine.properties` |

If you/AGR has someone with InterMine commit rights for the 4 upstream PRs, that unblocks ~25-50 GB.

### 3.2 Cheap re-enables (no new data fetch, just uncomment)

**Multi-species chado** — same FB2026_01 chado-pg dump we already have on AllianceMineDev, just covers 11 more Drosophila species:

```xml
<!-- uncomment these in project.xml -->
<source name="chado-db-flybase-dpse" type="chado-db">...</source>
<source name="chado-db-flybase-others" type="chado-db">...</source>
```

Adds **30-50 GB** of multi-species genes, alleles, stocks, features. Zero builder-side work.

### 3.3 Medium effort re-enables — sibling project.xml + builder data fetch

These need builder-side data fetch wiring + project.xml uncomment:

| Source | Data needed | Builder action |
| --- | --- | --- |
| `reactome` (re-enable) | FlyBase-relevant pathway files already fetched in extract_data.py `external` flag | Just uncomment in project.xml |
| `biogrid` | BIOGRID-ORGANISM-LATEST.tab3.zip (~50 MB) — fetcher exists | Verify project.xml `src.data.dir` matches our staging path |
| `psi-intact` | intact.zip (~500 MB) — fetcher exists | Verify path |
| `psi-mi-ontology` | psi-mi.obo from FMS or OBO foundry — fetcher needed | Add to extract_data.py |
| `homologene`, `treefam`, `panther`, `orthodb` | Per-source flat files | Add fetchers |
| `wormbase-identifiers`, `ncbi-gene`, `hgnc`, `mgi-identifiers`, `rgd-identifiers` | NCBI gene_info (already fetched), HGNC, MGI, RGD identifier files — fetchers exist for some | Verify paths, add missing ones |
| `kegg-pathway` | KEGG pathway files | Add fetcher (KEGG has license terms — verify free-use scope) |
| `omim` | OMIM disease database | License-restricted; need AGR institutional access |

Adds **15-30 GB** of cross-MOD context, pathways, interactions, identifiers.

### 3.4 Bucket-D sources (deferred from Phase 1, your `2026-05-29` decisions doc)

Per `docs/FLYMINE_BUCKET_D_DECISIONS_2026_05_29.md`:
- Re-enable + wire fetcher: `flyatlas`, `rnai` (DRSC), `bdgp-clone` (now FB-canonical via `cDNA_clone_data` + `genomic_clone_data`), `bdgp-insitu` (partial via FB curated_expression), `fly-fish`, `redfly`, `miranda`, `affy-probes`, `arbeitman-items-xml`, `long-oligo`, `drosdel-gff`, `flybase-expression`
- Already decided to drop: `flyreg` (Bergman lab retired), `flymine-static` (legacy)

Adds **5-10 GB**.

### 3.5 UniProt trembl (large)

Current `extract_data.py` fetches sprot only (`reviewed:true` filter). Trembl is auto-annotated, much larger. Two options:

- **Trembl per-organism via REST** (recommended) — query each of the 13 organisms FlyMine wants, save individual XML. Total ~5-20 GB.
- **Full trembl.xml.gz** — ~100 GB, won't fit on AllianceMineDev disk.

Adds **5-20 GB** depending on approach.

### 3.6 Phase 2 size projection

If all of 3.1-3.5 land:
- Currently: 16 GB
- + 4 blockers fixed: +25-50 GB → ~40-65 GB
- + multi-species chado: +30-50 GB → ~70-115 GB
- + medium effort re-enables: +15-30 GB → ~85-145 GB
- + Bucket-D: +5-10 GB → ~90-155 GB
- + UniProt trembl: +5-20 GB → ~95-175 GB

**Phase 2 realistic target: 80-120 GB** depending on which Bucket-D sources are worth the converter effort.

---

## 4. Build-side Phase 2 work (my side)

### 4.1 `extract_data.py` to encode (`Layer 1`)

I'll add fetchers for:

- UniProt trembl per-organism (13 REST calls or a single batched query)
- KEGG pathway files (verify license)
- HomoloGene / TreeFam / Panther / OrthoDB / HGNC update / MGI / RGD identifier files
- psi-mi.obo
- BioGRID, IntAct (already partial — finalize)
- The 12 Bucket-D source data files (per your decisions doc, leaf URLs)

### 4.2 `stage_data.py` post-fetch arranger (`Layer 2`)

Encode the session-discovered restructuring:

- Symlink `flybase/homology/current/` to `flybase/orthologs/*.tsv`
- Strip DOCTYPE from `interpro.xml` (until upstream InterPro source ignores DOCTYPE)
- Decompress `keywlist.xml` if delivered gzipped (UniProt CDN quirk)
- Detect+rename misaligned dir names (e.g. `current` aliases)

### 4.3 `build_full.py` orchestrator (`Layer 3`, optional)

Mirror alliancemine's pattern. Single command runs: extract_data → stage_data → buildDB → project_build → verify. Most of the value is in Layers 1+2.

---

## 5. Coordination items (open)

1. **NCBI E-utilities API key** — needed for `update-publications` re-enable. Does AGR have one for institutional API access? If so, add `pubmed.apikey=…` to `flymine.properties.template` env var path.
2. **InterMine bio-core PRs** — `Protein2IPRConverter` `.gz` reading + `FlybaseAllelesConverter` 21-col format + generic OBO converter perf. If anyone at AGR has commit rights, those 3 PRs unblock real volume.
3. **Tomcat for entity-page verification** — once Phase 1.5 is ready to render, send the `flymine_v0-2026-05-31_rc2` to a Tomcat container so we can do the visual check on `report.do?id=<FBab0022274>` (Df(2R)min) and `<FBba0000003>` (FM6) — your spec §5.5 visual acceptance.
4. **Multi-species chado uncomment** — quickest path to +30-50 GB. Do you want this in the next iteration?

---

## 6. State on AllianceMineDev (as of 2026-06-03)

- Image `sha:0f1fcc55…` (Phase 1.5 with sibling's `0f59deb7` + my `SOTerm.ontology` priority patch) on ECR + on box
- Data dir `~/flymine-deploy/data/` ~75 GB (includes 17 GB unused `protein2ipr.dat.gz` we couldn't decompress — could remove if disk gets tight)
- Chado-pg volume: 109 GB (FB2026_01 restored, indexes built, `shm_size=4gb`)
- Production DB on RDS: 16 GB
- RDS free storage: 242 GB / 1000 GB total — plenty of headroom for Phase 2

---

## 7. Cross-references

- Phase 1 report: `agr_intermine_builder/docs/FLYMINE_PHASE1_BUILD_HANDOFF_2026_06_03.md`
- Sibling Phase 1.5 commit: `flymine@0f59deb7` on master
- Builder priority patch: this build's image only (sibling needs to upstream)
- Phase 2 aim-1 doc: `new_flymine/docs/HANDOFF_BUILDER_PHASE2_AIM1_2026-06-02.{md,pdf}`
- Bucket-D decisions: `agr_intermine_builder/docs/FLYMINE_BUCKET_D_DECISIONS_2026_05_29.md`

Ready to go on Phase 2 when you are. Suggest starting with 3.2 (multi-species chado uncomment, free 30-50 GB) since it's zero-fetch and zero-converter-fix.

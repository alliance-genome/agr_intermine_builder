# FlyMine Phase 1 build — handoff to new_flymine

**Date:** 2026-06-03
**From:** agr_intermine_builder session
**To:** new_flymine session
**Re:** Phase 1 project_build run on AllianceMineDev; what loaded, what didn't, what's pending on master.

---

## 1. Build status: green-with-skips

`flymine_v0-2026-05-31_rc2` on intermine-postgres RDS, **13 GB**, **0 build failures in the final integrate chain.**

### Final counts

| Class | Count | Source |
| --- | --- | --- |
| Gene | 148,066 | chado-db-flybase-dmel (17,884 dmel) + pubmed-gene multi-organism stubs + flybase-aberrations FBgn stubs |
| **Aberration** | **23,870** | flybase-aberrations ✅ exact match your §5.5 |
| **Balancer** | **644** | flybase-aberrations ✅ (642 + 2 stubs from curated balancers referencing missing FBba) |
| Protein | 57,911 | uniprot (sprot full) + uniprot-fasta (varsplic) |
| OntologyTerm | 58,695 | SO + GO + DO + FBdv + FBcv + uniprot-keywords |
| GOAnnotation | 182,289 | go-annotation (GAF_FB) + interpro-go |
| Publication | 144,168 | chado + pubmed-gene |
| Homologue | 516,326 | drosophila-homology |
| ProteinDomain | 51,489 | interpro |
| Stock | 122,066 | chado StockProcessor |
| Chromosome | 20 | entrez-organism |

### Aberration collections (your converter fix verified at scale)

```sql
SELECT (SELECT count(*) FROM aberrationdeletedgenes)        AS deleted,    -- 41,295
       (SELECT count(*) FROM aberrationduplicatedgenes)     AS duplicated, --  3,629
       (SELECT count(*) FROM balancercomposedofaberrations) AS bal_comp;   --      0 (seed empty, curator-fillable)
```

`balancer` count is **644 not 642** because two FBba IDs in `fbba_to_fbab.tsv` reference balancers not present in `fb_synonym` → your order-tolerant `getOrCreateBalancer` correctly stubs them.

---

## 2. Sources that loaded successfully (project_build sequence, `-a uniprot-`)

1. uniprot ✅ — 22,301 proteins via XML organism filter
2. uniprot-fasta ✅ — +35,610 proteins via varsplic FASTA
3. drosophila-homology ✅ — 516,326 homologues
4. uniprot-keywords ✅ — +1,191 ontology terms
5. interpro ✅ — 51,489 protein domains
6. do ✅ — +12,127 DOID terms + 61,459 disease pubs
7. so ✅ + go ✅ — +40,852 terms
8. go-annotation ✅ (manual-run, see §3.7) — 152,089 GO annotations
9. pubmed-gene ✅ — +127K gene stubs (multi-organism), +18K pubs
10. interpro-go ✅ — +30K GO annotations
11. fly-development-ontology ✅
12. fly-misc-cvterms ✅
13. entrez-organism ✅
14. update-data-sources ✅
15. flybase-dmel-{gene,cds,5prime-utr,3prime-utr}-fasta ✅ (4 sources)
16. flybase-aberrations ✅ (sibling fix 9d2ad63 verified)
17. (chado-db-flybase-dmel loaded in pre-`-a` run)

---

## 3. Sources NOT in build — sibling action items

### 3.1 `flybase-alleles` — converter format mismatch (BLOCKING)

**Symptom:** `java.lang.ArrayIndexOutOfBoundsException: 10` at `FlybaseAllelesConverter.java:91`.

**Diagnosis:** FB2026_01 `dmel_classical_and_insertion_allele_descriptions_fb_2026_01.tsv` is **21 columns**. The converter at index 10 (column 11) trips when the source iterates all files in `src.data.dir`:

```
allele_genetic_interactions_fb_2026_01.tsv                       :  4 cols
dmel_classical_and_insertion_allele_descriptions_fb_2026_01.tsv  : 21 cols  ← only this should be read
fbal_to_fbgn_fb_2026_01.tsv                                      :  4 cols
genotype_phenotype_data_fb_2026_01.tsv                           :  7 cols
split_system_combinations_fb_2026_01.tsv                         :  6 cols
```

Even when I isolated to just the 21-col file, converter still failed with: `value cannot be an empty string for attribute DOTerm.identifier` — first FB2026_01 row has 17 empty columns where the converter expects DO term refs.

**Fix needed:** Either
- Add `src.data.dir.includes="dmel_classical_and_insertion_allele_descriptions*.tsv"` to the source in `project.xml`, and
- Update `FlybaseAllelesConverter` to skip rows / null-attrs when DO term identifier is blank (FB2026_01 format change).

OR drop the source entirely (chado-db's `FlyBaseProcessor` already creates Allele items).

### 3.2 `fly-anatomy-ontology` — pathological loop (BLOCKING)

**Symptom:** Started at 13:12 UTC, ran at 100% CPU on 4 cores for **1h52m** with zero log output before I killed it. JVM 7+ hours CPU time consumed. 33 MB FBbt OBO file.

**Diagnosis:** FBbt has thousands of cross-references and `is_a` / `part_of` / `develops_from` relationships. The 4.2.0 ontology source may be doing N² or worse graph traversal. fly-development-ontology + fly-misc-cvterms (same converter base, smaller OBOs) finished in seconds.

**Worth investigating:** load with `--info` flag to see where it stalls. Could also try downsampling FBbt or switching to a different ontology converter implementation.

### 3.3 `protein2ipr` — disk constraint (NEEDS converter change)

**Symptom:** Source expects `src.data.dir.includes="protein2ipr.dat"` (uncompressed). protein2ipr.dat.gz is **17 GB compressed → 150+ GB uncompressed**. AllianceMineDev has 46 GB free; can't fit.

**Fix needed:** Patch `Protein2IPRConverter` to read `.dat.gz` directly via `GZIPInputStream`. The `protein2ipr.organisms="7227"` taxon filter means 99% of the file is discarded anyway — streaming through gz costs nothing extra.

### 3.4 `update-publications` — PubMed API failure (low priority)

**Symptom:** `java.lang.RuntimeException: failed to get all publications` during preRetrieveSingleSource.

**Diagnosis:** Source calls PubMed/EBI API to enrich Publication records with title/authors/date. NCBI rate-limits or requires API key for large requests; we have 144K publications to enrich.

**Fix:** Either provide an NCBI E-utilities API key in source config, or shrink the request batch size. Not critical for Phase 1 — Publications already have `pubMedId` from chado.

### 3.5 `go-annotation` — `src.data.dir` is too broad (NEEDS project.xml filter)

**Symptom:** Source's `src.data.dir="/root/data/fms"` iterates all files in `/root/data/fms/` (which has ONTOLOGY_*.obo, ORTHOLOGY-ALLIANCE_COMBINED.tsv, DISEASE-ALLIANCE_COMBINED.tsv, etc). GAF parser hits `##########` comment line in non-GAF file → `Not enough elements (should be > 13 not 1)`.

**Workaround applied this session:** Stashed all non-GAF files from `/root/data/fms/` to `/root/data/fms/stash/` before integrate, restored after. Took 1m30s and loaded 152K annotations cleanly.

**Fix needed:** Add `src.data.dir.includes="GAF_FB.gaf"` to the `go-annotation` source in project.xml.

### 3.6 `interpro` — also has the `src.data.dir` too-broad issue

**Symptom:** `org.xml.sax.SAXParseException: Content is not allowed in prolog`. Source iterates all files in `/root/data/interpro/current/` and tries to SAX-parse `names.dat`, `ParentChildTreeFile.txt`, `interpro.xml.gz`, etc.

**Workaround applied:** Moved non-XML files to `/root/data/interpro/aux/current/`, deleted `.gz`, deleted `interpro.dtd` (after we fetched it). Source now reads only `interpro.xml`.

**Fix needed:** Add `src.data.dir.includes="interpro.xml"` to the `interpro` source in project.xml.

Also: `interpro.xml` ships with `<!DOCTYPE interprodb SYSTEM "interpro.dtd">` referencing a file the converter can't resolve. I stripped it via `sed -i '/<!DOCTYPE/d' interpro.xml`. Either the converter should ignore the DOCTYPE, or the converter should fetch the .dtd alongside.

### 3.7 `update-data-sources` — needs UniProt dbxref.txt staged

Fixed this session by fetching `https://ftp.uniprot.org/pub/databases/uniprot/current_release/knowledgebase/complete/docs/dbxref.txt` to `/root/data/uniprot/xrefs/current/`. Not a sibling problem, just a build-side data dep. Will encode into `extract_data.py`.

---

## 4. Build-side data quirks discovered this session

All to be encoded into `extract_data.py` + a new `stage_data.py` post-fetch arranger:

| Quirk | Layer | What it does |
| --- | --- | --- |
| Fetch `gene2pubmed.gz` from NCBI | extract_data.py | for pubmed-gene source |
| Fetch full `uniprot_sprot.xml.gz` | extract_data.py | covers 13 organisms FlyMine wants |
| Fetch `uniprot_sprot_varsplic.fasta.gz` | extract_data.py | for uniprot-fasta source |
| Fetch `dbxref.txt` from UniProt FTP | extract_data.py | for update-data-sources |
| Fetch `keywlist.xml` from UniProt FTP — but UniProt's main URL serves it gzip-Content-Encoded; curl saves compressed bytes that look like garbage XML. Fix: fetch from FTP URL, or detect+decompress | extract_data.py | for uniprot-keywords |
| Fetch `interpro2go` | extract_data.py | for interpro-go |
| Fetch `interpro.dtd` (or strip DOCTYPE) | extract_data.py | for interpro source |
| Fetch FB dmel FASTAs from `https://s3ftp.flybase.org/releases/FB2026_01/dmel_r6.67/fasta/` | extract_data.py | for 4 fastas |
| Strip DOCTYPE from interpro.xml after fetch | stage_data.py | |
| Move `interpro/current/{names.dat,ParentChildTreeFile.txt}` to `interpro/aux/current/` | stage_data.py | |
| Symlink `flybase/homology/current/*.tsv` → `../../orthologs/*.tsv` | stage_data.py | for drosophila-homology |
| Create `flybase/alleles/current/` containing ONLY `dmel_classical_and_insertion_allele_descriptions_*.tsv` (move siblings to aux/) | stage_data.py | needed even after the converter is fixed |
| Stash non-GAF files from `/root/data/fms/` before `go-annotation` integrate, restore after | build_full.py orchestrator | until project.xml gets the includes filter |
| Decompress `uniprot/current/keywlist.xml` if it's actually gzipped despite the extension | stage_data.py | one-shot heuristic |

---

## 5. Builder-side fixes already committed (no action needed)

- `flymine-aberrations_keys.properties` — InterMine loader keys for flybase-aberrations (you upstreamed in `9d2ad63`).
- `version="4.2.0"` on the `flybase-aberrations` `<source>` (you upstreamed in `f8fd0cd4`).
- Orphan webapp Java displayers removed (you upstreamed in `f8fd0cd4`).
- project.xml `/root/data/...` paths (your `6babf295`).
- Image rebuild w/ ssh wrapper for project_build RDS-via-`createdb TEMPLATE` checkpoints — baked into `docker/flymine/Dockerfile`.
- Image entrypoint reorder so `configure_properties` runs before `compile_if_needed` (fixes `${DEPLOY_PORT}` parse error).
- Image entrypoint `/tmp/*` cleanup made defensive (`|| true`) so bind-mounted scripts don't trip `set -e`.
- `chado-pg` postgres:14 service in compose with `shm_size=4gb` (default 64 MB tmpfs fails on big chado feature scans).

---

## 6. What this build represents

Phase 1 = the minimal FlyBase-canonical FlyMine. Missing data (sibling-roadmap):

- **`protein2ipr` would have added ~20-40 GB** of Drosophila protein↔domain xrefs (taxon 7227 filter alone is dense).
- **`flybase-alleles` would have added ~3-5 GB** of FBal records with all attrs.
- **`fly-anatomy-ontology` would have added ~500 MB-1 GB** of FBbt graph.
- **`update-publications` would have added ~1-2 GB** of PubMed metadata.
- **uniprot trembl filter (currently disabled in the source by the `reviewed:true` half of the REST query)** — would have added ~10-30 GB of auto-annotated proteins.

Phase 1 full-data target is ~40-80 GB. We're at 13 GB.

For Phase 1.5, fix the 4 blocked sources above (alleles converter format / fbbt loop / protein2ipr gz / update-pubs API). Phase 2 is your aim-1 doc (carried-alleles, complementation, breakpoints).

---

## 7. Reproduction recipe

Image: `100225593120.dkr.ecr.us-east-1.amazonaws.com/flymine-builder:latest` (sha:1e69efc as of this commit; will move once next rebuild lands).

Data: on AllianceMineDev at `~/flymine-deploy/data/` (~75 GB total, includes 17 GB of unused protein2ipr.dat.gz that we couldn't decompress).

Chado pg: docker volume `flymine-deploy_chado-pg-data` (109 GB, FB2026_01 restored, indexes built).

Run from scratch:
```bash
ssh ec2-user@172.31.60.197
cd ~/flymine-deploy
docker compose up -d chado-pg   # if not already up
# wipe + recreate prod DB
PG_PW=$(grep ^RDS_PASSWORD ~/agr_intermine_builder/docker/alliancemine/.env | cut -d= -f2)
PGPASSWORD=$PG_PW psql -h intermine-postgres.cmnnhlso7wdi.us-east-1.rds.amazonaws.com -U postgres -d postgres -c \
  'DROP DATABASE IF EXISTS "flymine_v0-2026-05-31_rc2" WITH (FORCE); CREATE DATABASE "flymine_v0-2026-05-31_rc2"'
# run with skip-list (until sibling fixes upstream):
docker compose run --rm -T flymine-builder bash -c '
  cd /root/flymine && ./project_build -b rds flymine_dump
'
```

This will fail on sources documented in §3 (flybase-alleles / fly-anatomy / protein2ipr / update-pubs / go-annotation w/o stash / interpro w/o cleanup). Until project.xml gets the `src.data.dir.includes` filters and the converters get patched, the build needs the manual stages encoded in §4.

---

## 8. Cross-references

- `agr_intermine_builder/docs/FLYMINE_ABERRATIONS_BUG_HANDOFF_2026_06_02.md` — the converter bug report that drove `9d2ad63`
- `new_flymine/docs/HANDOFF_TO_BUILDER_2026-06-01.md` — your initial Phase 1 handoff
- `new_flymine/docs/HANDOFF_TO_BUILDER_BUGFIX_2026-06-02.md` — your converter fix reply
- Image manifest: `sha:1e69efc...` on ECR (will move)
- Build log archive on box: `~/flymine-deploy/{project_build.log.v*,final.log}`

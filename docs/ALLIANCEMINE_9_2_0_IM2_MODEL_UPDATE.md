# AllianceMine 9.2.0.im2: model update (Alliance API migration, Phases 1–6)

Status: **planning; nothing built.** Started 2026-10-08. Release only after full testing.

**What it is:** AllianceMine on Alliance release 9.2.0 data, with the expanded InterMine model and data loading moved from FMS bulk files to
the Alliance API, plus FlyMine-style protein, domain, pathway and homology sources. Background: `API_MIGRATION_ROLLOUT.md`.

## Decisions (2026-10-08)

| Topic | Decision |
|---|---|
| Version | **9.2.0.im2** (Alliance data release 9.2.0, second InterMine model). DB `alliancemine_9_2_0_im2_rc<N>`. First named 9.1.0.im2; moved to 9.2.0 on 2026-10-08 (see below) |
| Data release | The Alliance API serves one release at a time and switches 9.1.0 → 9.2.0 on 2026-10-14. Fetching all 9 species takes 1.5–3 days, so the API prefetch runs **after** the switch and FMS is pinned to 9.2.0: every source comes from the same release |
| Scope | Phases 1–6, plus upstream FlyMine's cross-species sources |
| Retired upstream | Drop `treefam` (TreeFam is gone) and `homologene` (NCBI froze it in 2014) |
| Add | `ncbi-gene`, `hgnc`. Not `omim` (licensed files) or the `*-identifiers` resolvers (the Alliance API supplies IDs) |
| Species | General sources limited to the 9 AllianceMine taxa: 559292 9606 10090 10116 6239 7227 7955 8364 8355 |
| Orthologs | Keep PANTHER and OrthoDB as separate data sets. Ortholog templates get a data-set constraint so they keep returning Alliance (DIOPT) rows only |
| Interactions | Skip `biogrid` and `psi-intact`: they duplicate the Alliance molecular/genetic interactions |
| User profile | Test against a **copy** (`COPY_PROFILE_DB=true`); the live profile is untouched until cutover |
| Build | Overnight (US time). Shared RDS |
| Code | New branches + PRs in all three repos |
| Release | Only after full testing. **File downloading is verified before any build** |

## Where the code is

| Repo (GitHub) | Branch | Local worktree | What it holds |
|---|---|---|---|
| `alliance-genome/alliancemine` | `alliancemine-9.2.0.im2` (from `expand-model-api-dedup` 0d80490) | `~/Projects/alliance/new_alliancemine/wt-im2/alliancemine` | `project.xml` (78 active sources), webapp config, `default-template-queries.xml` |
| `alliance-genome/alliancemine-bio-sources` | `alliancemine-9.2.0.im2` (from `expand-model-api-dedup` e198477) | `…/wt-im2/alliancemine-bio-sources` | **The model** (`alliancemine-global_additions.xml`), one directory per bio-source (converter Java + keys + empty `_additions.xml`), and `scripts/`: the Python Alliance-API / FMS fetchers driven by `scripts/fetch_all.py` |
| `alliance-genome/agr_intermine_builder` | `alliancemine-9.2.0.im2` (from `development` + Phase-6 `ab9f605`) | `~/Projects/alliance/agr_intermine_builder-im2` | `docker/alliancemine/`: Dockerfile, **`project.xml` (the one actually built; see B1)**, `entrypoint.sh`, `scripts/extract_data.py` (all downloads), `scripts/build_full.py` |

## How data gets in (pipeline)

`extract_data.py` (builder) runs inside the build container and fills `/root/data`:
1. **S3 sync** of `s3://agr-db-backups/alliancemine/intermine/` → `/root/data/intermine/` (SGD extras, yeast homologs, psi-mi/goslim OBO).
2. **FMS snapshot**: `FILE_MAP` files from `https://fms.alliancegenome.org/api/snapshot/release/<rel>` → `/root/data/fms/` (genome FASTA, ontologies, GAFs, Alliance orthology).
3. **Alliance API / FMS-derived fetchers**: `fetch_all.py --out-dir /root/data/api` (each writes one TSV; SQLite cache in `/root/data/api-cache/`).
4. **Flat files** (Phase 6, `download_flatfiles()`): UniProt, InterPro, protein2ipr, KEGG, Reactome → `/root/data/<source>/current/`.
5. **Runtime NCBI** (no download): `entrez-organism`, `update-publications`.
6. **SGD Postgres** (`www-rds-primary.yeastgenome.org`): `sgd`, `sgd-complexes`, `sgd-complementation-db`.

## Sources (78 active in `alliancemine` project.xml)

Origin key: **FMS** = FMS snapshot file; **API** = Alliance REST API fetcher; **FMS→TSV** = fetcher that converts FMS
files to TSV; **FLAT** = flat-file URL; **S3**; **DB** = SGD database; **NCBI** = fetched at load time;
**MINE** = queried from another InterMine. "Pre" = already in 9.1.0.

| # | Source | Phase | Origin | Fetcher / download | Data | Status |
|---|---|---|---|---|---|---|
| 1–6 | alliance-{wb,fb,zfin,mgi,rgd,xtrops}-fasta | Pre | FMS FASTA | FILE_MAP | `/root/data/fms/FASTA_*.fa` | MGI/RGD/XT use older assemblies (GRCm38, Rnor6.0, XT9.1) |
| 7 | alliance-xlaevis-fasta | Pre | FMS FASTA (XL9.2/10.1 exist) | **none** | includes `""` | **Gap** |
| 8–15, 78 | do, go, eco, mmo, emapa, zfa, wbbt, fbbt, so | Pre | FMS ONTOLOGY | FILE_MAP | `/root/data/fms/ONTOLOGY_*.obo` | OK |
| 16–17 | psi-mi-ontology, go-slim | Pre | S3 | `download_s3_data()` | `/root/data/intermine/ontology/` | OK (go-slim is yeast-only) |
| 18, 27, 28 | sgd, sgd-complementation-db, sgd-complexes | Pre | DB | – | – | OK |
| 19–26, 29–30 | sgd-gff(+utr), sgd-db-utr, fungi/cgob/cglabrata/pombe homologs, homolog-genes, sgd-protein-properties/ntermini | Pre | S3 | `download_s3_data()` | `/root/data/intermine/…` | OK (`sgd-gff` uses taxon 4932) |
| 31 | alliance-genes | Pre → API | API `/gene/{id}` | `fetch_genes.py` | `/root/data/api/alliance-genes.tsv` | **Blocker: seeds yeast genes only** |
| 32 | go-annotation | Pre | FMS GAF (8 MODs) | FILE_MAP | `/root/data/fms/*.gaf` | OK |
| 33, 35, 36 | alliance-disease, -alleles, -expression | Pre → fetcher | FMS→TSV | `fetch_disease/alleles/expression.py` | project.xml points at a **Mac path** | **Path mismatch** |
| 34 | alliance-orthologs | Pre | FMS ORTHOLOGY-ALLIANCE | FILE_MAP | `/root/data/fms/` | OK |
| 37–38 | alliance-genetic/molecular-interactions | 1 | API `/gene/{id}/…-interactions` | `fetch_interactions.py` | `/root/data/api/` | **Yeast-only seed** |
| 39 | alliance-paralogs | 3a | API `/gene/{id}/paralogs` | `fetch_paralogs.py` | `/root/data/api/` | **Yeast-only seed** |
| 40 | alliance-phenotypes | 3b | API `/gene/{id}/phenotypes` | `fetch_phenotypes.py` | `/root/data/api/` | **Yeast-only seed** |
| 41 | alliance-disease-models | 5a | API `/gene/{id}/models` | `fetch_disease_models.py` | `/root/data/api/` | OK (no SGD by design) |
| 42 | alliance-allele-detail | 5b | API `/allele/{id}` | `fetch_allele_detail.py` | `/root/data/api/` | Seed list = FMS file frozen at 4.0.0 |
| 43 | alliance-ortholog-detail | 5c | API `/gene/{id}/orthologs` | `fetch_orthologs.py` | `/root/data/api/` | **Yeast-only seed** |
| 44 | alliance-disease-detail | 5d | API `/disease/{id}/genes` | `fetch_disease_annotations.py` | `/root/data/api/` | OK |
| 45–46 | alliance-mouse-strains, alliance-worm-rnai | 6d | MINE (MouseMine / WormMine query service) | `fetch_mousemine_strains.py`, `fetch_wormmine_rnai.py` | `/root/data/api/` | OK; depends on our own mines |
| 47–55 | transgenic-alleles, disease-alleles, experimental-disease, variants, gene-descriptions, agms, allele-phenotypes, gene-crossrefs, htp | extras | FMS→TSV | one `fetch_*.py` each | **Mac path** | **Path mismatch** |
| 56 | alliance-alphafold | extra | derived from gene-crossrefs | `fetch_alphafold.py` | **Mac path** | **Path mismatch; crashes `fetch_all` (wrong input path)** |
| 57 | alliance-string | extra | FLAT stringdb-downloads.org v12 | `fetch_string.py` | **Mac path** | Path mismatch; no *Xenopus* |
| 58–59 | alliance-crispr-screens, alliance-molecules | extras | FMS→TSV | `fetch_crispr_screens/molecules.py` | **Mac path** | Path mismatch; molecules = WB only |
| 60 | alliance-chembl | extra | FLAT EBI ChEMBL uniprot mapping | `fetch_chembl.py` | **Mac path** | Path mismatch; no species filter |
| 61 | uniprot | 6a | FLAT `uniprot_sprot.xml.gz` | `download_flatfiles()` | `/root/data/uniprot/current` | **Loader expects unzipped / per-taxon file** |
| 62 | uniprot-keywords | 6a | FLAT `keywlist.xml` | `download_flatfiles()` | same | OK |
| 63 | uniprot-fasta | 6a | FLAT `uniprot_sprot_varsplic.fasta.gz` | `download_flatfiles()` | same | **.gz vs plain name; loader class unset** |
| 64–65 | interpro, protein2ipr | 6a | FLAT EBI InterPro | `download_flatfiles()` | `/root/data/interpro/…` | **.gz not unzipped / name mismatch** |
| 66 | interpro-go | – | FLAT `interpro2go` | **none** | `/root/data/interpro/ontology/current` | **Gap** |
| 67 | pubmed-gene | – | FLAT NCBI `gene2pubmed` | **none** | `/root/data/pubmed/current` | **Gap** |
| 68–69 | orthodb, panther | – | FLAT | **none** | `/root/data/{orthodb,panther}/current` | **Gap** |
| 70–71 | treefam, homologene | – | retired | – | – | **Remove** (decision) |
| 72–73 | psi-intact, biogrid | – | FLAT | – | – | **Remove** (decision) |
| 74 | kegg-pathway | 6b | FLAT KEGG REST | `download_flatfiles()` | `/root/data/kegg/current` | **Format differs from what the loader expects; yeast taxon 4932 vs 559292** |
| 75 | reactome | 6b | FLAT reactome.org | `download_flatfiles()` | `/root/data/reactome/current` | **Wrong files** (needs `UniProt2Reactome_All_Levels.txt`, 6 columns) |
| 76–77 | update-publications, entrez-organism | Pre | NCBI | – | – | OK |

Full per-source detail (exact paths, URLs, converter classes) was produced by the 2026-10-08 inventory; this table is
the summary.

## Blockers found before any build

| # | Blocker | Fix |
|---|---|---|
| B1 | The **builder's own `docker/alliancemine/project.xml`** (old 39-source list) is copied over the alliancemine checkout, so none of the new sources would run | Replace it with the im2 project.xml (or stop copying it) |
| B2 | Dockerfile `ALLIANCEMINE_BRANCH` / `BIO_SOURCES_BRANCH` default to `master` | Set them to `alliancemine-9.2.0.im2` |
| B3 | `alliance-genes` and 5 other per-gene API fetchers **seed yeast genes only**. AllianceMine would lose every non-yeast gene | Seed from all MODs' gene lists (BGI / FMS) |
| B4 | 17 sources read from a **local Mac path** (`…/alliancemine-bio-sources/data`); fetchers write `/root/data/api` | Point them at `/root/data/api` |
| B5 | `fetch_alphafold.py` reads its input from the wrong path and exits 1, failing `fetch_all` and `extract_data` | Pass `--crossrefs /root/data/api/gene-crossrefs.tsv` |
| B6 | Release detection picks whatever is newest by date, independently in `extract_data` and in the fetchers | Pin one release (`ALLIANCE_RELEASE=9.2.0`) through `extract_data` and every fetcher |
| B7 | Phase-6 flat files: `.gz` not unzipped, KEGG format and taxon, wrong Reactome file | Fix `download_flatfiles()` per source |
| B8 | No downloads for interpro-go, pubmed-gene, orthodb, panther, ncbi-gene, hgnc, xlaevis FASTA | New download functions, filtered to the 9 taxa |
| B9 | AllianceMine still patches mail **after** deploy | Bake the mail fix into the WAR (as FlyMine/YeastMine) |

Also noted, not blocking:
- `extract_data` still downloads FMS files nothing reads now (combined disease/variant/expression, BGI, GFF), and still
  builds `Gene.tsv`. Trim these after the build works.
- Modules `diopt-orthologs`, `psi-complexes` and `sgd-complementation` exist in bio-sources but aren't in project.xml.

## Model changes (`alliancemine-bio-sources/alliancemine-global_additions.xml`, 166 → 185 classes)

**19 new classes:** CRISPRScreenResult, DiseaseModel, ECNumber, Molecule, Paralogue, PhenotypeAnnotation,
ProteinDomainRegion, Protocol, RNAi, STRINGInteraction, Sample, SampleCharacteristic, Strain, Tissue,
TransgenicAllele, Treatment, TreatmentParameter, UniProtFeature, VariantConsequence.

**Extended:**
- Allele, Disease, DiseaseAnnotation, DiseaseEvidence, ExpressionAnnotation
- Gene: descriptions, paralogues, phenotype annotations, disease models
- Homologue, Interaction, InteractionDetail, Interactor
- Pathway, Protein (UniProt fields, isoforms, features, domains, pathways), Variant

Nothing is removed, and no `extends` changes.

**Type changes that can break saved queries and templates:**
- `Homologue.algorithmsMatch` and `algorithmsAttempted`: String → Integer.
- `Homologue.isBestScore` and `isBestReverseScore`: String → Boolean.
- `VariantDetails.chrStartPosition` and `chrEndPosition`: String → Integer.
- `VariantDetails.hasDisease/PhenotypeAnnotations`: String → Boolean.

They affect templates **Gene_Orthologs, Organism_Orthologs, Gene_Homologs and Gene_Variants**, and any user query
that compares them with `'Yes'`/`'No'`.

**Risk:** Protein, UniProtFeature and ProteinDomainRegion are also defined by the upstream uniprot/interpro additions;
their reverse references may clash at `mergeModels`.

## Plan

1. **Code (branches above):** B1–B9; remove treefam/homologene/biogrid/psi-intact; add ncbi-gene, hgnc and the
   missing downloads; fix the 4 templates for the type changes. Keep each change small and documented here.
2. **API prefetch (from 2026-10-14, once the API serves 9.2.0):** all 9 species, parallel but WAF-safe, into the persistent cache on the build host. 1.5–3 days; reruns hit the cache.
3. **Download check (before any build):** on the build host, in a separate data folder, run `extract_data.py` only.
   Then a checker script confirms, for **every** source in project.xml:
   - its `src.data.dir` / file exists and is non-empty;
   - its include patterns match;
   - the format is what the loader expects (header/columns, unzipped);
   - row counts per taxon are plausible against 9.1.0.

   Iterate until clean.
4. **Model check:** `mergeModels` + `compileJava` for all sources (catches the Protein/UniProt clash) without loading data.
5. **Overnight test build** into `alliancemine_9_2_0_im2_rc1`, with a copy of the user profile. The build-DB guard
   checks the target name.
6. **Verification, Phases 1→6 in order:**
   - new classes populated per phase;
   - `compare_mines.py` against live 9.1.0 (expect release-to-release differences as well as model ones) for templates and class counts;
   - the type-changed templates;
   - search and autocomplete;
   - forgot-password mail.
7. **Release** after sign-off: AllianceMine cutover per `RUNBOOK_ALLIANCEMINE_RESTART.md` (bag-upgrade deadlock kick),
   with 9.1.0 kept as rollback.

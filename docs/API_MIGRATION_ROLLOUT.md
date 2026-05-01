# Alliance API Migration — Rollout & Verification Plan

**Status:** branches are landed across three repos. Phase 1-5 (Alliance-API
fetchers + model additions) is merged into `agr_intermine_builder/development`
already. Phase 6 (UniProt/InterPro/KEGG/Reactome flat-files + cross-mine
federation) is on feature branches awaiting merge. This document is the
operator playbook to integrate, build, verify, and roll back the full chain.

---

## Why this work exists

Two converging pressures drove the migration:

1. **FMS is being wound down.** AllianceMine's bio-source converters historically
   read TSV files distributed by the Alliance File Management Service. The
   service is sunsetting. Without intervention, the build would lose its data
   sources.

2. **The Alliance REST API exposes data FMS never did** — molecular and
   genetic interactions at full fidelity, paralogs, gene-level phenotypes,
   per-MOD disease models, richer disease annotations with ECO evidence
   chains, and per-algorithm orthology breakdowns. Plus sibling InterMine
   instances (MouseMine, WormMine) carry classes AllianceMine had no model
   for at all (Strain, RNAi).

The migration replaces FMS-only ingestion with a hybrid pipeline:

```
[Alliance API   ]  →  [scripts/fetch_*.py]  →  [data/*.tsv]  →  [Java BioFileConverter]  →  [InterMine]
[Sibling InterMines]      pagination, retry,    stable column     same pattern as            unchanged
                          sqlite cache          schema per feed   FMS-era converters
[UniProt/InterPro/  ]  →  [extract_data.py downloads]  →  [/root/data/{uniprot,interpro,kegg,reactome}/current/]
[KEGG/Reactome FTP  ]
```

Heavy plumbing (HTTP retry, pagination, caching, rate limiting) is in Python.
Java converters stay thin. No new external InterMine framework dependency.

---

## Cross-repo branch state

| Repo | Branch | Status | What it carries |
|---|---|---|---|
| `alliancemine-bio-sources` | `wire-api-sources` | not merged | 24 commits — Phase 1-6 model additions (14 new classes, 80+ attributes), eleven new bio-source modules, eleven Python fetchers under `scripts/` |
| `alliancemine` | `wire-api-sources` | not merged | 4 commits — `project.xml` declares all eleven new alliance-* sources + UniProt/InterPro/KEGG/Reactome InterMine-core sources |
| `agr_intermine_builder` | `development` | merged | `extract_data.py` invokes `fetch_all.py` (Phase 1-5 API fetchers); Dockerfile clones bio-sources via `BIO_SOURCES_BRANCH` build arg; `py3-tqdm` available for fetcher progress bars |
| `agr_intermine_builder` | `phase-6-flatfile-downloads` | not merged | 1 commit (off pre-tqdm `development`) — `extract_data.py` adds `download_flatfiles()` for UniProt/InterPro/KEGG/Reactome with `--skip-flatfiles` flag |

The `phase-6-flatfile-downloads` branch needs a rebase onto current
`development` before merge (because tqdm and the `db_admin` commits landed
after it forked).

---

## What's in the model now

### New classes (14)

| Class | Source | Phase |
|---|---|---|
| `Paralogue` | Alliance API `/gene/{id}/paralogs` | 3a |
| `PhenotypeAnnotation` | Alliance API `/gene/{id}/phenotypes` | 3b |
| `DiseaseModel` | Alliance API `/gene/{id}/models` (non-yeast MODs) | 5a |
| `UniProtFeature` | UniProt XML (Phase 6a flat-file) | 6a |
| `ProteinDomainRegion` | InterPro + protein2ipr | 6a |
| `Sample`, `SampleCharacteristic`, `Treatment`, `TreatmentParameter`, `Protocol`, `Tissue` | reserved for future high-throughput sources | 6c |
| `Strain` | MouseMine PathQuery | 6d |
| `RNAi` | WormMine PathQuery | 6d |

### Enriched existing classes

- **Allele**: `+alleleSynonyms`, `+alterationType`, `+apiCategory`, `+apiCrossReference` (FMS hygiene + Phase 5b)
- **Variant**: `+affectedGene` ref, `+variantsTypeId` (FMS hygiene)
- **Gene**: `+dateProduced`, `+dataProvider`, `+modCrossRefCompleteUrl`, `+diseaseModels` collection, `+paralogues` collection, `+phenotypeAnnotations` collection (Phase 2 + 3)
- **Homologue**: `+stringencyFilter`, `+predictionMethodsMatched/NotMatched/NotCalled` (Phase 5c) + Boolean upgrades on `isBestScore`/`isBestReverseScore` + Integer upgrades on `algorithmsMatch`/`algorithmsAttempted`
- **DiseaseAnnotation**: `+generatedRelationString`, `+diseaseQualifiers`, `+parentSlimIds`, `+viaOrthologyOrder`, `+uniqueId` (Phase 5d)
- **DiseaseEvidence**: `+evidenceCodes` collection of ECOTerm, `+dateAssigned` Date (Phase 5d)
- **VariantDetails**: `+hasDiseaseAnnotations`/`+hasPhenotypeAnnotations` Boolean upgrades, `+chrStartPosition`/`+chrEndPosition` Integer upgrades
- **ExpressionAnnotation**: `+cellularComponentQualifierIds/TermNames`, `+substructureQualifierIds/TermNames`, `+anatomyQualifierIds/TermNames` (FMS hygiene), `+sample`, `+tissue`, `+treatments` (Phase 6c)
- **Interaction / InteractionDetail / Interactor**: 10 new attributes/refs covering relation, aggregationDatabase, detection method, role names, participant types (Phase 1)
- **Pathway**: `+shortName`, `+description`, `+curated` Boolean, `+proteins` collection (Phase 6b)
- **Protein**: 8 new attributes (primaryAccession, uniprotAccession, uniprotName, isUniprotCanonical, isFragment, length, md5checksum, ecNumber), 6 new collections (features, proteinDomainRegions, keywords, isoforms, pathways, comments), 2 new refs (canonicalProtein, sequence) — Phase 6a

### Bio-source module catalogue

Eleven new alliance-* module directories:

| Module | Reads TSV | Class(es) populated | Source data |
|---|---|---|---|
| `alliance-genes` (enriched) | `alliance-genes.tsv` | Gene + new metadata | Alliance API per-gene |
| `alliance-genetic-interactions` (activated) | `genetic-interactions.tsv` | Interaction, InteractionDetail | Alliance API |
| `alliance-molecular-interactions` (activated) | `molecular-interactions.tsv` | Interaction, InteractionDetail | Alliance API |
| `alliance-paralogs` | `paralogs.tsv` | Paralogue | Alliance API |
| `alliance-phenotypes` | `phenotypes.tsv` | PhenotypeAnnotation | Alliance API |
| `alliance-disease-models` | `disease-models.tsv` | DiseaseModel | Alliance API |
| `alliance-allele-detail` | `allele-detail.tsv` | partial Allele (merged) | Alliance API |
| `alliance-ortholog-detail` | `orthologs.tsv` | partial Homologue (merged) | Alliance API |
| `alliance-disease-detail` | `disease-annotations-detail.tsv` | partial DiseaseAnnotation (merged) | Alliance API |
| `alliance-mouse-strains` | `mouse-strains.tsv` | Strain + Allele | MouseMine PathQuery |
| `alliance-worm-rnai` | `worm-rnai.tsv` | RNAi + Strain + Gene | WormMine PathQuery |

Plus four InterMine-core sources declared in project.xml (no local module
needed — InterMine resolves the type → loader from its core JARs):

- `uniprot`, `uniprot-keywords`, `uniprot-fasta` — populates Protein
- `interpro` + `protein2ipr` — populates ProteinDomain + ProteinDomainRegion
- `kegg-pathway` — populates Pathway via KEGG
- `reactome` — populates Pathway via Reactome

---

## Integration plan

### Merge order (top-down)

1. **`alliancemine-bio-sources/wire-api-sources` → `master`.**
   Has to land first because it defines the model. Anything downstream
   referencing class names (project.xml or webapp templates) is a
   dangling reference until this is in.
   - **Pre-merge gates**: passing `./gradlew clean compileJava` (already
     verified at 304 tasks). Code review on the new classes
     (Paralogue, PhenotypeAnnotation, DiseaseModel, Strain, RNAi,
     UniProtFeature, ProteinDomainRegion, Sample/Treatment family).
   - **Post-merge**: tag the commit so `BIO_SOURCES_BRANCH=master` in
     downstream Docker builds picks it up.

2. **`alliancemine/wire-api-sources` → `master`.**
   - **Pre-merge gates**: visual review of the project.xml stanzas (paths,
     globs, taxon lists). The Phase 6a/6b sources reference upstream
     data files that don't exist yet on the build host — that's fine
     because project.xml is a build-time spec, not a runtime dependency.
   - **Post-merge**: same — `ALLIANCEMINE_BRANCH=master` will pull it in.

3. **`agr_intermine_builder/phase-6-flatfile-downloads` → rebase onto
   `development` → merge to `development`.**
   - **Pre-merge action**: `git rebase development` — the branch is
     behind by `5068239`, `c9add56`, `67f3c62`. Resolve any conflicts
     in `extract_data.py` (the manifests should still apply cleanly).
   - **Pre-merge gates**: `python3 -c "import ast;
     ast.parse(open('docker/alliancemine/scripts/extract_data.py').read())"`
     plus `--help` smoke test.
   - **Verify URLs first** (see "Known issues" below) — a broken
     KEGG/Reactome URL is the most likely failure mode.

4. **`agr_intermine_builder/development` → `stage` → `production`.**
   The repo's existing promotion path. No change in mechanism.

### Image build

Once Steps 1-3 are done and merged, a fresh image build is a single command:

```bash
cd agr_intermine_builder/docker/alliancemine
docker compose build --no-cache alliancemine-builder
```

Until merge, use the explicit branch overrides:

```bash
docker compose build --no-cache \
  --build-arg ALLIANCEMINE_BRANCH=wire-api-sources \
  --build-arg BIO_SOURCES_BRANCH=wire-api-sources \
  alliancemine-builder
```

The Dockerfile clones both repos at image-build time
(`Dockerfile:69-74`); no host-side checkout step needed.

---

## Verification plan

### 1. Image-level checks (after `docker compose build`)

```bash
# Verify the image has both repos cloned
docker compose run --rm alliancemine-builder bash -c '
  ls -d /root/alliancemine /root/alliancemine-bio-sources
  ls /root/alliancemine-bio-sources/scripts/fetch_*.py | wc -l   # expect 11
  python3 -c "import tqdm; print(tqdm.__version__)"             # expect a version, not ImportError
  python3 /root/alliancemine-bio-sources/scripts/fetch_all.py --help
'
```

Success criteria: 11 fetch scripts present, tqdm imports, fetch_all
prints help with all 10 fetchers listed.

### 2. Extract-data dry run (no project_build yet)

```bash
docker compose run --rm alliancemine-builder extract --skip-fms --skip-flatfiles
```

This runs only the Alliance API fetchers (Phase 1-5). After ~20-30 min
cold-cache, ~2 min warm-cache:

- `/root/data/api/` should contain 9 TSVs:
  `alliance-genes.tsv, genetic-interactions.tsv, molecular-interactions.tsv,
  orthologs.tsv, paralogs.tsv, allele-detail.tsv,
  disease-annotations-detail.tsv, disease-models.tsv, phenotypes.tsv`
- `/root/data/api-cache/` should contain 8 `.sqlite` files
- Each TSV's row count should be non-zero — log lines `Wrote ... (N rows)`
  surface this. Empty TSVs are a real failure mode (e.g. seed-list
  enumeration broke); spot-check `wc -l` on each.

### 3. Cross-mine fetcher dry run

```bash
docker compose run --rm alliancemine-builder bash -c '
  cd /root/alliancemine-bio-sources
  python3 scripts/fetch_mousemine_strains.py --limit 100 --out-dir /tmp
  python3 scripts/fetch_wormmine_rnai.py --limit 100 --out-dir /tmp
  head -10 /tmp/mouse-strains.tsv /tmp/worm-rnai.tsv
'
```

Success criteria: both TSVs have a populated header row + ~100 data rows
with all columns present (no empty trailing columns indicating an
unmapped path in the PathQuery query).

### 4. Flat-file download dry run (Phase 6 branch only)

```bash
# After the phase-6 branch is merged into development:
docker compose run --rm alliancemine-builder extract --skip-fms --skip-api
```

Watches the four manifests run. After ~30-60 min on a fresh container
(UniProt sprot.xml.gz alone is ~1 GB), check:

- `/root/data/uniprot/current/` has 3 files: `uniprot_sprot.xml.gz`,
  `uniprot_sprot_varsplic.fasta.gz`, `keywlist.xml`
- `/root/data/interpro/current/interpro.xml.gz` exists
- `/root/data/interpro/match_complete/current/protein2ipr.dat.gz` exists
- `/root/data/kegg/current/` has `map_title.tab` plus 7 per-organism files
- `/root/data/reactome/current/` has 3 files

Each file size > 0 and the manifest summary log (`uniprot: N/N files
present`) reports full coverage.

### 5. Full pipeline build

After the dry runs are clean:

```bash
docker compose run --rm alliancemine-builder build
```

This is the multi-hour run (5-8 hours per the existing README). Watch
for failures by stage:

| Stage | Failure signal | Likely cause |
|---|---|---|
| `extract_data` | non-zero exit, summary shows failed downloads | Network blip; FMS or upstream FTP down; check `--skip-*` flags to isolate |
| `mergeModels` (per-source) | "Class X not in model" or "Reference Y has no reverse-reference" | Bio-source `_additions.xml` references a class not in `alliancemine-global_additions.xml`; usually means the bio-sources branch is stale |
| `compileJava` (per-source) | Java compile error | Converter expects a model attribute that didn't merge; same root cause |
| `project_build` | "src.data.dir does not exist" | extract_data didn't produce expected file; cross-check with `/root/data/` listing |
| `project_build` | converter-specific stack trace, e.g. NullPointerException | Schema mismatch between fetcher TSV and converter COL_* constants — usually a column-order drift |
| Solr index step | timeout, slow indexing | Database has more data than before — Solr config may need bigger heap; not a correctness issue |

### 6. Database spot-checks (post-build)

```sql
-- Confirm the new classes have rows
SELECT (SELECT count(*) FROM diseasemodel)         AS disease_models,
       (SELECT count(*) FROM paralogue)            AS paralogs,
       (SELECT count(*) FROM phenotypeannotation)  AS phenotype_annotations,
       (SELECT count(*) FROM strain)               AS strains,
       (SELECT count(*) FROM rnai)                 AS rnais,
       (SELECT count(*) FROM uniprotfeature)       AS uniprot_features,
       (SELECT count(*) FROM proteindomainregion)  AS interpro_regions;

-- Spot-check a known reference: mouse Trp53 (MGI:98834) should have ~1000 disease models
SELECT count(*) FROM diseasemodel dm
  JOIN gene g ON dm.gene = g.id
  WHERE g.primaryidentifier = 'MGI:98834';

-- Spot-check expression population fix: should be > 1.7M rows now
-- (vs ~0 in pre-migration builds where _COMBINED was empty)
SELECT count(*) FROM expressionannotation;

-- Confirm UniProt populated the previously-empty Protein class
SELECT count(*) FROM protein WHERE primaryaccession IS NOT NULL;
```

Success thresholds (rough — actual numbers depend on release):

- `expressionannotation` > 1,500,000
- `paralogue` > 50,000
- `phenotypeannotation` > 200,000
- `strain` > 100,000 (MouseMine has ~115k)
- `rnai` > 50,000 (WormMine)
- `protein` > 80,000 (UniProt for the 9 Alliance taxa)
- `proteindomainregion` > 200,000 (depends on InterPro coverage)
- `diseasemodel` > 500,000 (mouse + rat + zebrafish + xenopus)

If any of these are zero or off by an order of magnitude, the corresponding
fetcher or converter has a bug.

### 7. PathQuery smoke tests (webapp-level)

After deploy, exercise the new templates from BlueGenes or via REST:

```bash
# Should return interaction edges - was empty before this work
curl -s 'https://alliancemine.org/alliancemine/service/query/results?format=json' \
  --data-urlencode 'query=<query model="genomic" view="Gene.symbol Gene.molecularInteractions.partner.symbol"/>' \
  | head

# Should show paralogs of yeast HOG1
curl ... 'view="Gene.symbol Gene.paralogues.paralogue.symbol Gene.paralogues.identity"' \
  ... 'constraint><value>HOG1</value></constraint'

# Disease models for mouse Trp53
curl ... 'view="Gene.symbol Gene.diseaseModels.modelName Gene.diseaseModels.disease.name"'
```

---

## Known issues / TODOs

### TODO-verify markers in `extract_data.py`

The `phase-6-flatfile-downloads` branch added URL constants marked
`TODO-verify`:

- **KEGG REST endpoints** (`/list/pathway`, `/link/pathway/{org}`) return
  tab-separated text. The InterMine `kegg-pathway` loader was originally
  written against legacy FTP files; the format may have drifted. **Mitigation**:
  run a one-off `gradle :bio-source-kegg-pathway:build` against a small
  dataset before depending on it for production.
- **Reactome URLs** look stable but their `Ensembl2Reactome_All_Levels.txt`
  format changed in 2022. The InterMine reactome loader version we're on
  may not parse the current format.
- **UniProt trembl vs sprot**: the manifests pull SwissProt only. If the
  loader silently drops trembl entries, that's fine (they're predicted-only
  proteins). If it expects both files, add a fourth tuple.

These are all **non-blocking** for Phase 1-5 because the InterMine-core sources
they enable haven't been depended-on by any template yet — a missing
KEGG/Reactome ingest just means empty `Pathway` rows, not a build failure.

### Webapp / template work not in scope

The new classes are queryable via PathQuery as soon as the build completes,
but BlueGenes templates and webconfig-model.xml entries that surface them
nicely in the UI haven't been written. Sample candidates for follow-up:

- "Disease models for gene" — PathQuery on `Gene.diseaseModels`
- "Paralogs by identity threshold" — `Gene.paralogues.identity > 50`
- "Yeast genes inferred via mouse orthology to disease X" —
  `viaOrthologyOrder > 0` filter on DiseaseAnnotation
- "Mouse strains carrying allele X" — Strain → Allele traversal

### Branch divergence in agr_intermine_builder

`phase-6-flatfile-downloads` is behind by three `development` commits
(`67f3c62`, `5068239`, `c9add56`). Rebase before merge — none of those
three touch `extract_data.py` so the rebase should be a fast-forward.

---

## Rollback procedure

The migration is designed to be additive. Each layer can be backed out
independently:

### Roll back the alliancemine `wire-api-sources` merge

Revert the merge commit on master. project.xml will lose the new
`<source>` stanzas; `gradle clean compileJava` keeps working because
the model is unchanged. The downstream image build still has all 11
new bio-source modules but ingests no input — empty TSVs ⇒ empty
classes.

### Roll back the bio-sources `wire-api-sources` merge

Revert the merge on master. The model loses the 14 new classes and
80+ enrichments. project.xml in alliancemine still references the
class names, so:

- If alliancemine is also reverted: clean state
- If alliancemine is not reverted: `mergeModels` fails on every
  alliance-* module that touches a removed class

In other words: **alliancemine and alliancemine-bio-sources must roll
back together** if they roll back at all. Tag both at the merge point
to make this trivial.

### Roll back agr_intermine_builder Phase-6 merge

Revert the `phase-6-flatfile-downloads` merge on `development`. The
extract_data.py loses the `download_flatfiles()` method but the FMS
and API-fetcher paths keep working. Anyone running with `--skip-flatfiles`
on the post-merge build was already getting this state.

### Cache reset (force re-fetch)

If a fetcher is producing stale data after a fix:

```bash
rm -rf /root/data/api-cache/
docker compose run --rm alliancemine-builder extract --skip-fms --skip-flatfiles
```

The SQLite caches under `/root/data/api-cache/` short-circuit by
`(gene_id, endpoint)` keys — clearing them forces a fresh API hit.

---

## Where things live (glossary)

| Where | What |
|---|---|
| `alliancemine-bio-sources/scripts/common.py` | Shared HTTP+retry+sqlite-cache+TSV-writer helpers; `intermine_paginate()` for cross-mine PathQuery |
| `alliancemine-bio-sources/scripts/fetch_*.py` | Per-source Python fetchers |
| `alliancemine-bio-sources/scripts/fetch_all.py` | Orchestrator the Docker pipeline calls |
| `alliancemine-bio-sources/alliancemine-global_additions.xml` | The model — every class addition lives here |
| `alliancemine-bio-sources/alliance-*/...` | Each new bio-source module: Java converter + properties + integration keys |
| `alliancemine-bio-sources/CLAUDE.md` | Architecture note + cross-repo TODOs (the original |
| `alliancemine/project.xml` | Declares which sources the build runs and where their input lives (`/root/data/{fms,api,uniprot,interpro,kegg,reactome}/`) |
| `agr_intermine_builder/docker/alliancemine/Dockerfile` | Image build — clones both repos, installs python3 + tqdm |
| `agr_intermine_builder/docker/alliancemine/scripts/extract_data.py` | Pipeline pre-build step — FMS + S3 + API fetchers + (Phase 6 branch) flat-files |
| `agr_intermine_builder/docs/API_FETCHER_INTEGRATION.md` | Original Phase 1-5 spec doc |
| `agr_intermine_builder/docs/API_MIGRATION_ROLLOUT.md` | This document |

---

## Phase ledger (how we got here)

Reverse-chronological summary of the work, for anyone tracing history:

- **Phase 6d** — Cross-mine federation: MouseMine Strain, WormMine RNAi.
  PathQuery REST client in `common.py`. `Strain` + `RNAi` classes.
- **Phase 6c** — Sample/Experiment infrastructure: Sample, Treatment,
  Protocol family. Wired onto ExpressionAnnotation + PhenotypeAnnotation.
- **Phase 6b** — KEGG + Reactome pathway sources. Pathway class enriched.
- **Phase 6a** — UniProt + InterPro. Protein class fully populated for
  the first time. ProteinDomainRegion + UniProtFeature classes.
- **Phase 5** — Alliance API deepening: disease models, allele detail,
  ortholog per-algorithm breakdown, disease annotation richness.
  4 new `*-detail` enrichment modules using integration-key merge.
- **Phase 4** (docs) — Root CLAUDE.md architecture note for API-backed
  ingestion pattern.
- **Phase 3** — Paralogs + Phenotypes (new bio-source modules + classes).
- **Phase 2** — Gene metadata enrichment from `/gene/{id}`.
- **Phase 1** — Interaction converters wired against live API. Replaced
  the two empty stubs that had been there since day one.
- **FMS hygiene pass** — closed every column gap in the FMS-era
  converters: 9 attributes added, 1 schema bug fixed, type upgrades
  for 8 String → Boolean/Integer.
- **OBO term annotation pass** — 77 classes gained Sequence Ontology
  URIs (1/166 → 78/166 semantic coverage).
- **Sanitization pass** — 22 converters migrated to Log4j, raw
  collections parameterized, copyright headers, 1 InterRegion
  duplicate-name bug fixed.

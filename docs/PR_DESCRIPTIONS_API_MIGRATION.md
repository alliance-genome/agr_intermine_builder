# PR Descriptions for the Alliance API Migration

Three PRs in three repositories, intended to merge in the order below.
Copy the relevant section into the PR body when you open each one.

The full operator-facing playbook (verification thresholds, rollback,
glossary) lives in `agr_intermine_builder/docs/API_MIGRATION_ROLLOUT.md`
— link to it from the PR description rather than duplicating its contents.

---

## PR 1 — `alliance-genome/alliancemine-bio-sources` `wire-api-sources` → `master`

**URL:** https://github.com/alliance-genome/alliancemine-bio-sources/pull/new/wire-api-sources

### Title

`Post-FMS migration: API-backed sources, model expansion, cross-mine federation`

### Body

```markdown
This PR is the first of three coordinated PRs that migrate AllianceMine
off the sunsetting FMS file-distribution service onto the Alliance REST
API plus per-MOD InterMine federation. Companion PRs:

- alliance-genome/alliancemine#TODO (project.xml wiring) — must merge after this one
- alliance-genome/agr_intermine_builder#TODO (extract_data flat-file downloads)

Full rollout + verification + rollback playbook:
[`agr_intermine_builder/docs/API_MIGRATION_ROLLOUT.md`](https://github.com/alliance-genome/agr_intermine_builder/blob/development/docs/API_MIGRATION_ROLLOUT.md)

## What's in this PR (24 commits)

### Model expansion — `alliancemine-global_additions.xml`

**14 new classes:**
- `Paralogue`, `PhenotypeAnnotation`, `DiseaseModel` — new biological data
- `UniProtFeature`, `ProteinDomainRegion` — protein structure detail
- `Sample`, `SampleCharacteristic`, `Treatment`, `TreatmentParameter`,
  `Protocol`, `Tissue` — experimental-context infrastructure (lifted from FlyMine)
- `Strain`, `RNAi` — cross-mine federation classes (MouseMine, WormMine)

**80+ enrichments on existing classes:**
- `Allele` (+3 attrs from /allele/{id})
- `Variant` (+affectedGene ref, +variantsTypeId)
- `Gene` (+dateProduced, +dataProvider, +modCrossRefCompleteUrl, +5 collections)
- `Homologue` (+stringencyFilter, +per-algorithm method lists,
  Boolean upgrade on isBestScore/isBestReverseScore, Integer upgrade
  on algorithmsMatch/algorithmsAttempted)
- `DiseaseAnnotation` (+5 attrs including viaOrthologyOrder)
- `DiseaseEvidence` (+evidenceCodes ECOTerm collection, +dateAssigned Date)
- `VariantDetails` (Boolean + Integer type upgrades)
- `ExpressionAnnotation` (+6 qualifier attrs, +sample/tissue/treatments)
- `Interaction`/`InteractionDetail`/`Interactor` (10 new fields)
- `Pathway` (+shortName, +description, +curated, +proteins)
- `Protein` (+8 UniProt-derived attrs, +6 collections, +2 refs)

**Schema fixes:**
- InteractionRegion duplicate `<reference>`/`<collection>` named "locations"
  (would have failed model merge in any newer InterMine version)
- 77 OBO Sequence Ontology term URIs added (1/166 → 78/166 semantic coverage)
- 22 converters migrated from System.out to Log4j; raw collections
  parameterized; FlyMine-era copyright headers refreshed

### New Python fetcher pipeline — `scripts/`

Eleven new fetchers under `scripts/`:

| Script | Endpoint | Output |
|---|---|---|
| `fetch_genes.py` | `/gene/{id}` | `data/alliance-genes.tsv` |
| `fetch_interactions.py` | `/gene/{id}/{molecular,genetic}-interactions` | `genetic-` + `molecular-interactions.tsv` |
| `fetch_orthologs.py` | `/gene/{id}/orthologs` | `orthologs.tsv` |
| `fetch_paralogs.py` | `/gene/{id}/paralogs` | `paralogs.tsv` |
| `fetch_allele_detail.py` | `/allele/{id}` | `allele-detail.tsv` |
| `fetch_disease_annotations.py` | `/disease/{id}/genes` | `disease-annotations-detail.tsv` |
| `fetch_disease_models.py` | `/gene/{id}/models` | `disease-models.tsv` |
| `fetch_phenotypes.py` | `/gene/{id}/phenotypes` | `phenotypes.tsv` |
| `fetch_mousemine_strains.py` | MouseMine PathQuery | `mouse-strains.tsv` |
| `fetch_wormmine_rnai.py` | WormMine PathQuery | `worm-rnai.tsv` |
| `fetch_all.py` | orchestrator | — |

`scripts/common.py` carries the shared helpers: HTTP retry with
exponential backoff, SQLite cache (`/scripts/.cache/`), TSV writer,
gene-list enumeration from FMS BGI files, **and** an
`intermine_paginate()` PathQuery REST client used by the cross-mine
fetchers.

Stdlib only at runtime — `tqdm` is purely cosmetic.

### Eleven new bio-source modules

Each is a sibling Gradle subproject under `alliance-*/`:

`alliance-paralogs`, `alliance-phenotypes`, `alliance-disease-models`,
`alliance-allele-detail`, `alliance-ortholog-detail`,
`alliance-disease-detail`, `alliance-mouse-strains`, `alliance-worm-rnai`.

Plus two previously-stubbed modules made live:
`alliance-genetic-interactions`, `alliance-molecular-interactions`.

The `*-detail` modules don't own a class — they emit partial Items
keyed on a shared integration key (`Allele.key_alleleid`,
`Homologue.key_pair`, `DiseaseAnnotation.key_subject_term`) and rely
on InterMine's integration engine to merge them into the items emitted
by the primary source. New pattern in this codebase, documented in
the root `CLAUDE.md`.

## Verification

- `./gradlew clean compileJava` — passes at **304 tasks** (from 209
  before this work)
- Per-fetcher smoke test: `python3 scripts/<fetcher>.py --limit 5
  --out-dir /tmp/smoke` for any new fetcher; check the TSV header
  matches the converter's `COL_*` constants

Smoke results during development:
- HOG1 yeast: 729 genetic + 501 molecular interactions, 54 phenotype
  annotations, 46 orthologs
- Trp53 mouse: 1003 disease-model rows, 2 paralogs
- DOID:14330 Parkinson's: 3256 disease-gene annotations
- MouseMine Strain class: 114k+ strains queryable

## Out of scope (deferred to follow-up PRs)

- Webapp / BlueGenes templates surfacing the new classes
- KEGG/Reactome URL verification (TODO-verify markers in
  `agr_intermine_builder` PR)
- Push button to delete the four module dirs orphaned in
  settings.gradle (`diopt-orthologs`, `sgd-complementation`,
  `psi-complexes`, `psi-mi-ontology`) — those are pre-existing

## Rollback

This PR and the alliancemine wire-api-sources PR are **tightly coupled**:
both must roll back together. See "Rollback procedure" in the
rollout doc for details.
```

---

## PR 2 — `alliance-genome/alliancemine` `wire-api-sources` → `master`

**URL:** https://github.com/alliance-genome/alliancemine/pull/new/wire-api-sources

### Title

`Wire post-FMS API-backed sources into project.xml`

### Body

```markdown
Pairs with alliance-genome/alliancemine-bio-sources#TODO. Must merge
after that PR — references bio-source module names and class names
this repo doesn't define.

## What this PR does (4 commits)

`project.xml` gains declarations for:

**Phase 1-5: API-backed sources** (read TSVs at `/root/data/api/`,
produced by the bio-sources Python fetchers):

- `alliance-genetic-interactions` (was commented out, now live)
- `alliance-molecular-interactions` (was commented out, now live)
- `alliance-paralogs`
- `alliance-phenotypes`
- `alliance-disease-models`
- `alliance-allele-detail`
- `alliance-ortholog-detail`
- `alliance-disease-detail`

**Phase 6a: protein-level sources** (read flat files under
`/root/data/uniprot/current/` and `/root/data/interpro/...`):

- `uniprot`, `uniprot-keywords`, `uniprot-fasta`
- `interpro`, `protein2ipr`

**Phase 6b: pathway sources** (`/root/data/{kegg,reactome}/current/`):

- `kegg-pathway`, `reactome`

**Phase 6d: cross-mine federation:**

- `alliance-mouse-strains` (MouseMine PathQuery → mouse-strains.tsv)
- `alliance-worm-rnai` (WormMine PathQuery → worm-rnai.tsv)

**Source-input migration:**

- `alliance-genes` switched from the locally-built `/root/data/genes/`
  to the API-fetcher output `/root/data/api/alliance-genes.tsv`. The
  TSV preserves the legacy 14-column schema plus three new columns
  for dateProduced / dataProvider / modCrossRefCompleteUrl, so the
  Java converter is backward-compatible — a fallback to /root/data/genes
  still works if needed during the transition.

**Bug fix:**

- `alliance-expression`'s include glob changed from
  `EXPRESSION-ALLIANCE_COMBINED.tsv` (header-only in FMS 9.0.0,
  silently dropping 1.77M rows) to `EXPRESSION-ALLIANCE_*.tsv`
  picking up every per-MOD file.

## Verification

After this PR + the bio-sources PR are merged and the
`agr_intermine_builder` image is rebuilt, run:

```bash
docker compose run --rm alliancemine-builder build
```

Expected new database row counts (rough thresholds; see rollout doc
for the full SQL spot-check):

- `expressionannotation` > 1.5M (was ~0)
- `paralogue` > 50k
- `phenotypeannotation` > 200k
- `strain` > 100k
- `rnai` > 50k
- `protein` (with primaryaccession) > 80k
- `diseasemodel` > 500k

## Path conventions established

- `/root/data/fms/` — legacy FMS files (still used while FMS exists)
- `/root/data/api/` — Python fetcher output (Alliance REST API +
  cross-mine PathQuery)
- `/root/data/uniprot/current/` — UniProt release files
- `/root/data/interpro/current/`, `/root/data/interpro/match_complete/current/`
- `/root/data/kegg/current/`, `/root/data/reactome/current/`

These are realised by `agr_intermine_builder/docker/alliancemine/scripts/extract_data.py`.

## Rollback

Tightly coupled with the bio-sources wire-api-sources PR — they must
roll back together. See `API_MIGRATION_ROLLOUT.md` "Rollback procedure".
```

---

## PR 3 — `alliance-genome/agr_intermine_builder` `phase-6-flatfile-downloads` → `development`

**URL:** https://github.com/alliance-genome/agr_intermine_builder/pull/new/phase-6-flatfile-downloads

### Title

`extract_data: Phase-6 flat-file downloads (UniProt, InterPro, KEGG, Reactome)`

### Body

```markdown
Final piece of the Alliance API migration. Pairs with
alliance-genome/alliancemine#TODO (Phase 6a/6b project.xml stanzas)
and alliance-genome/alliancemine-bio-sources#TODO (Phase 6a/6b
model additions for Protein/Pathway expansion).

This PR is **safe to merge independently** of the other two — until
the bio-sources / project.xml changes land, the new download step is
unused (sources don't reference `/root/data/{uniprot,interpro,kegg,reactome}/`
yet). Until then, runs without `--skip-flatfiles` will create unused
files; harmless, just wasted bandwidth.

> **Pre-merge action**: rebase this branch onto current `development`.
> Behind by `5068239`, `c9add56`, `67f3c62`, `cad122b`. None touch
> `extract_data.py` so the rebase should be a fast-forward.

## What's in this PR (1 commit)

`docker/alliancemine/scripts/extract_data.py` gains:

- Four module-scope manifest constants — `UNIPROT_FILES`,
  `INTERPRO_FILES`, `KEGG_FILES`, `REACTOME_FILES`. Each is a list of
  `(url, target_dir_relative, target_filename)` tuples. Filenames are
  hard-coded because the InterMine bio-source loaders are picky
  (`uniprot_sprot_varsplic.fasta`, `keywlist.xml`, `protein2ipr.dat`).
- `AllianceDataExtractor._download_url()` — generic urlretrieve helper
  with one retry, mirroring the existing logging idiom.
- `AllianceDataExtractor.download_flatfiles()` — iterates the four
  manifests, skips files already present (size > 0) for resumability,
  reports per-source success ratio.
- `download_all()` accepts a third `skip_flatfiles` flag, runs
  flat-file pulls last so faster failures (FMS, API) surface first.
- `--skip-flatfiles` CLI flag for granular re-runs.

## TODO-verify markers

The URLs are based on canonical upstream conventions but two
upstreams have moved targets in recent years:

- **KEGG REST endpoints** (`/list/pathway`, `/link/pathway/{org}`)
  return tab-separated text. The InterMine `kegg-pathway` loader was
  written against legacy FTP files; format may have drifted. Mitigation:
  run `gradle :bio-source-kegg-pathway:build` against a small dataset
  before depending on this for production.
- **Reactome** (`Ensembl2Reactome_All_Levels.txt`,
  `ReactomePathways.txt`, `ReactomePathwaysRelation.txt`) — file
  format changed in 2022. Loader version may not parse current format.

These are **non-blocking** for the migration overall: a missing
KEGG/Reactome ingest just means empty `Pathway` rows, not a build
failure.

## Verification

```bash
# Dry-run flat-file downloads only (skip FMS + API)
docker compose run --rm alliancemine-builder extract --skip-fms --skip-api

# Verify expected files
docker compose run --rm alliancemine-builder bash -c '
  ls -la /root/data/uniprot/current/ /root/data/interpro/current/ \
         /root/data/kegg/current/ /root/data/reactome/current/
'
```

Expected layout per the manifests:

- `/root/data/uniprot/current/`: `uniprot_sprot.xml.gz`,
  `uniprot_sprot_varsplic.fasta.gz`, `keywlist.xml`
- `/root/data/interpro/current/interpro.xml.gz`
- `/root/data/interpro/match_complete/current/protein2ipr.dat.gz`
- `/root/data/kegg/current/`: `map_title.tab` + 7 per-organism files
- `/root/data/reactome/current/`: 3 TSVs

## Rollback

`git revert` the merge commit. The FMS and API-fetcher paths are
unaffected; only the new flat-file pass goes away. Anyone running with
`--skip-flatfiles` before this PR was already in this post-revert
state.
```

---

## Suggested ordering

1. **Open all three PRs first** so reviewers can see the cross-references.
2. Merge **PR 1 (bio-sources)** when reviewed.
3. Merge **PR 2 (alliancemine)** as soon as PR 1 is in `master` —
   nothing else gates it.
4. Rebase + merge **PR 3 (agr_intermine_builder)** independently.
   Build pipeline doesn't break either way.

After all three merge, the next agr_intermine_builder image build
pulls everything in via the `BIO_SOURCES_BRANCH=master` /
`ALLIANCEMINE_BRANCH=master` defaults.

## Replace the TODO references

When you open the PRs, GitHub assigns sequential numbers. Update the
`#TODO` placeholders in each PR's body with the actual PR numbers from
the other two so reviewers can navigate the cross-repo chain.

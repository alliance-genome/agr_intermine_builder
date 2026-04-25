# Alliance API Fetcher Integration

## Status

**Implemented.** The `extract_data` stage now runs the
`alliancemine-bio-sources/scripts/fetch_all.py` orchestrator after the
S3 sync and FMS download. Outputs land in `/root/data/api/` — the
location `alliancemine/project.xml` references for the nine API-backed
bio-source modules added on the `wire-api-sources` branches of the
`alliancemine` and `alliancemine-bio-sources` repos.

## Background

FMS is being wound down. Phase 1-5 of the Alliance API migration landed
nine API-backed bio-source modules in `alliancemine-bio-sources` that
read TSVs produced by Python fetchers calling the Alliance REST API
directly:

| Module | TSV | Source endpoint |
|---|---|---|
| `alliance-genes` (enriched) | `alliance-genes.tsv` | `/gene/{id}` |
| `alliance-genetic-interactions` | `genetic-interactions.tsv` | `/gene/{id}/genetic-interactions` |
| `alliance-molecular-interactions` | `molecular-interactions.tsv` | `/gene/{id}/molecular-interactions` |
| `alliance-paralogs` | `paralogs.tsv` | `/gene/{id}/paralogs` |
| `alliance-phenotypes` | `phenotypes.tsv` | `/gene/{id}/phenotypes` |
| `alliance-disease-models` | `disease-models.tsv` | `/gene/{id}/models` (non-yeast MODs) |
| `alliance-allele-detail` | `allele-detail.tsv` | `/allele/{id}` |
| `alliance-ortholog-detail` | `orthologs.tsv` | `/gene/{id}/orthologs` |
| `alliance-disease-detail` | `disease-annotations-detail.tsv` | `/disease/{id}/genes` |

## How it's wired

### 1. Image clones bio-sources at build time

The Dockerfile already clones `alliancemine-bio-sources` into
`/root/alliancemine-bio-sources/` via the `BIO_SOURCES_BRANCH` build
arg. The fetcher scripts (`scripts/fetch_*.py`, `scripts/fetch_all.py`,
`scripts/common.py`) ride along with that clone — no separate
checkout step needed.

To test fetcher changes from a feature branch before merge:

```bash
cd docker/alliancemine
echo 'BIO_SOURCES_BRANCH=wire-api-sources' >> .env
docker compose build --no-cache alliancemine-builder
```

Once the feature branch merges to upstream `master`, drop that line.

### 2. extract_data runs the orchestrator after FMS

`docker/alliancemine/scripts/extract_data.py` now does three passes
in `download_all`:

1. S3 sync of SGD/external data → `/root/data/intermine/`
2. FMS snapshot download of 49 MOD files → `/root/data/fms/` and `/root/data/genes/`
3. `python3 /root/alliancemine-bio-sources/scripts/fetch_all.py --out-dir /root/data/api/`

Order matters: FMS runs first because some fetchers reuse FMS artefacts
(BGI gene seeds, `EXPRESSION-ALLIANCE_*.tsv`, the
`VARIANT-ALLELE_COMBINED.tsv` allele seed, the
`DISEASE-ALLIANCE_COMBINED.tsv` disease seed).

### 3. SQLite cache lives under data/

`fetch_all.py` and the per-fetcher modules read a cache directory from
the `ALLIANCE_FETCH_CACHE` env var (defaulting to `scripts/.cache/`
inside the bio-sources repo). `extract_data.py` sets it to
`/root/data/api-cache/`, which is part of the existing
`./data:/root/data` bind-mount in `docker-compose.yml`. The cache
survives container recreation and is inspectable from the host.

Cold cache: ~20 min for a yeast-only build, longer for multi-MOD.
Warm reruns: ~2 min.

### 4. Granular re-runs

`extract_data.py` accepts `--skip-fms` and `--skip-api` so an operator
can re-run only one half during an incident:

```bash
# Just the API fetchers (e.g. after fetcher fix, FMS data still good)
docker compose run --rm alliancemine-builder extract --skip-fms

# Just FMS + S3 (e.g. legacy behaviour or if API is down)
docker compose run --rm alliancemine-builder extract --skip-api
```

Both flags together is rejected (nothing left to do).

The combined `extract_data` stage as a whole is also re-runnable via
`build_full.py --start-from extract_data` — this re-does both halves.

## Failure modes

| Failure | Behaviour |
|---|---|
| Single fetcher fails | `fetch_all.py` continues, exits non-zero in summary. `extract_data.py` marks API as `failed` and exits 1 unless `--stop-on-error` was passed (it isn't, by default). |
| All fetchers succeed but produce empty TSVs | Not detected here — surfaces during `project_build` when the bio-source modules read empty inputs. Fetchers themselves log `0 rows` clearly in their per-run summary. |
| `/root/alliancemine-bio-sources/scripts/fetch_all.py` missing | Image was built from a `BIO_SOURCES_BRANCH` that predates the Phase-5 work. `extract_data.py` logs the path and exits 1. Rebuild the image with a branch that includes `scripts/fetch_all.py`. |
| Network blip during a fetch | Per-fetcher retries with exponential backoff (`common.py`). Cache hits unaffected. Persistent failures bubble up to the orchestrator. |

## Verification checklist

After running `extract_data` on a fresh container:

- [ ] `/root/data/api/` contains nine TSVs:
      `alliance-genes.tsv`, `genetic-interactions.tsv`,
      `molecular-interactions.tsv`, `orthologs.tsv`, `paralogs.tsv`,
      `allele-detail.tsv`, `disease-annotations-detail.tsv`,
      `disease-models.tsv`, `phenotypes.tsv`
- [ ] `/root/data/api-cache/` contains one `.sqlite` file per fetcher
      (genes, interactions, orthologs, paralogs, allele_detail,
      disease_annotations, disease_models, phenotypes)
- [ ] `./gradlew :bio-source-alliance-paralogs:build` (and the other
      eight new modules) runs cleanly against the produced TSVs
- [ ] Full `project_build` completes; spot-check that `Paralogue`,
      `PhenotypeAnnotation`, and `DiseaseModel` objects are present
      in the resulting database

## References

- Per-fetcher details, schemas, and run options:
  `alliancemine-bio-sources/scripts/README.md`
- Architecture rationale (why Python-then-Java, why integration-key
  merge for the `*-detail` modules):
  `alliancemine-bio-sources/CLAUDE.md`, "API-backed sources" section
- Canonical fetcher run order is defined in
  `scripts/fetch_all.py::FETCHERS`: genes → interactions → orthologs →
  paralogs → allele_detail → disease_annotations → disease_models →
  phenotypes

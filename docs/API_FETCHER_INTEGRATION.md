# Wiring the alliancemine-bio-sources API fetchers into the Docker pipeline

## Status

**Pending implementation.** This doc captures what the Docker build pipeline
in `docker/alliancemine/` needs in order to consume the new API-backed
data feeds added to `alliancemine-bio-sources` over Phase 1-5
(commits `488b423` … `27eafa8` on the `wire-api-sources` branch of
that repo) and wired into `alliancemine/project.xml` (`18e4808` and
`4d87628` on this same branch in the `alliancemine` repo).

## Why

FMS is being wound down. The Phase 1-5 work landed nine API-backed
bio-source modules in `alliancemine-bio-sources`:

| Module | Reads | Source |
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

`alliancemine/project.xml` now points all nine sources at
`/root/data/api/`. That directory needs to exist with the listed
TSVs in it before `project_build` runs in the InterMine pipeline.

The TSVs are produced by Python fetchers under
`alliancemine-bio-sources/scripts/`, orchestrated by
`scripts/fetch_all.py`. The Docker pipeline needs to call that
orchestrator after `extract_data` (which still pulls FMS data the
fetchers reuse — BGI gene seeds, expression per-MOD files) and
before `project_build`.

## What to change in `docker/alliancemine/`

### 1. Mount or clone `alliancemine-bio-sources` into the build container

The fetchers live in that repo's `scripts/` directory and import a
shared `common.py`. The container needs the repo accessible at a
known path (e.g. `/root/alliancemine-bio-sources/`).

Two reasonable approaches:

- **Bind-mount** the host clone in `docker-compose.yml`:
  ```yaml
  services:
    alliancemine-builder:
      volumes:
        - ../../../alliancemine-bio-sources:/root/alliancemine-bio-sources:ro
  ```
- **`git clone`** at container start — add a step in `entrypoint.sh`
  before the new `fetch_api` stage:
  ```bash
  git clone --depth 1 --branch wire-api-sources \
      https://github.com/alliance-genome/alliancemine-bio-sources.git \
      /root/alliancemine-bio-sources
  ```

Pick one based on the deployment context (CI vs local dev). The
clone version is more portable; the bind mount is faster for local
iteration.

### 2. Add a new `fetch_api` pipeline stage

Insert between `extract_data` and `project_build` in
`entrypoint.sh`. Roughly:

```bash
fetch_api_stage() {
    log "=== Stage: fetch_api ==="
    mkdir -p /root/data/api
    python3 /root/alliancemine-bio-sources/scripts/fetch_all.py \
        --out-dir /root/data/api \
        --verbose
    # On any fetcher failure the orchestrator exits non-zero.
}
```

The orchestrator (`scripts/fetch_all.py`) already runs all eight
fetchers in dependency order and exits non-zero on any failure.
It supports `--only` / `--skip` / `--limit` for partial runs and
smoke tests. SQLite caches under `scripts/.cache/` so reruns are
fast — preserve that directory across container invocations if
possible (volume mount).

### 3. Update the `extract_data` stage's "complete" criteria

Some fetchers reuse FMS artefacts (BGI gene-list seed JSONs, the
per-MOD `EXPRESSION-ALLIANCE_*.tsv` files, the
`VARIANT-ALLELE_COMBINED.tsv` for allele seeds, the
`DISEASE-ALLIANCE_COMBINED.tsv` for disease seeds). The existing
extract_data step already pulls these as part of the 49-file FMS
snapshot, so no change is required there *yet*. Once FMS is fully
deprecated upstream, the fetchers will need a non-FMS seed source
(SGD-direct, or paginated `/gene` from the API itself).

### 4. Resource considerations

For a yeast-dominant build the fetchers add ~20 minutes to a cold
run (≈6k SGD genes × multiple endpoints, plus disease-side and
allele-detail expansions). With cache warm reruns are ~2 minutes.
For a multi-MOD build (mouse + rat + zebrafish + …) expect a few
hours on first pass; the SQLite cache dominates from the second
build onward.

The fetchers run sequentially today. If wall time becomes a
bottleneck, the orchestrator is a small file
(`scripts/fetch_all.py`) and could be parallelised with a thread
pool over fetcher subprocesses — none of them depend on each
other's output.

## Verification checklist before committing the Docker change

- [ ] Container has read access to a clone or bind-mount of
      `alliancemine-bio-sources` on the `wire-api-sources` branch (or
      whatever branch lands in upstream).
- [ ] `python3 /root/alliancemine-bio-sources/scripts/fetch_all.py
      --limit 10 --out-dir /tmp/api-smoke` runs to completion in
      under a minute and emits 8 TSV files.
- [ ] After `fetch_api_stage`, `/root/data/api/` contains:
      `alliance-genes.tsv`, `genetic-interactions.tsv`,
      `molecular-interactions.tsv`, `orthologs.tsv`, `paralogs.tsv`,
      `allele-detail.tsv`, `disease-annotations-detail.tsv`,
      `disease-models.tsv`, `phenotypes.tsv`.
- [ ] `gradlew :bio-source-alliance-paralogs:build` (and the other
      eight new modules) runs cleanly with the produced TSVs.
- [ ] Full `project_build` completes; spot-check that
      `Paralogue`, `PhenotypeAnnotation`, and `DiseaseModel`
      objects are present in the resulting database.

## Reference

- Per-fetcher details, schemas, and run options:
  `alliancemine-bio-sources/scripts/README.md`.
- Architecture rationale (why Python-then-Java, why
  integration-key merge for the `*-detail` modules):
  `alliancemine-bio-sources/CLAUDE.md`, "API-backed sources" section.
- The `scripts/fetch_all.py` orchestrator's `FETCHERS` list defines
  the canonical run order: genes → interactions → orthologs →
  paralogs → allele_detail → disease_annotations → disease_models →
  phenotypes.

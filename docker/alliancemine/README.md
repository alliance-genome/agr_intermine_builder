# AllianceMine Build Container

Docker container that runs the complete InterMine build pipeline for AllianceMine. Connects to an external RDS PostgreSQL instance and downloads data from the Alliance FMS API and S3.

## Usage

```bash
cp .env.example .env   # Fill in credentials
docker compose build
docker compose run --rm alliancemine-builder build
```

## Commands

| Command | Description |
|---------|-------------|
| `build` | Full 6-stage build pipeline |
| `build --start-from <stage>` | Start from a specific stage |
| `build --skip-stages <stage1> <stage2>` | Skip specific stages |
| `build --resume` | Resume project_build from last checkpoint |
| `extract` | Download data only (FMS, S3, API fetchers, flat files); no RDS access |
| `check-downloads` | Check `/root/data` against the cloned `project.xml` (exits 1 on any FAIL) |
| `promote` | Promote RC database to production |
| `deploy` | Deploy WAR to Tomcat |
| `bash` | Interactive shell |

## Build Stages

1. **buildDB** — Create PostgreSQL schema
2. **extract_data** — S3 (SGD data), FMS (latest upload per file type in the release), Alliance
   API fetchers, and the Phase-6 flat files (`scripts/flatfiles.py`), with gene IDs rewritten to
   Alliance CURIEs using the ID map built from the BGI files (`scripts/alliance_idmap.py`)
3. **project_build** — Data integration (4-7 hours, creates DB checkpoints)
4. **postprocess** — Indexes, summaries, Solr search/autocomplete
5. **war** — Build WAR file
6. **deploy** — Deploy to Tomcat via cargoRedeployRemote

## Download check

Before a build, download into a separate data folder and check it:

```bash
docker compose run --rm alliancemine-builder extract
docker compose run --rm alliancemine-builder check-downloads          # --deep scans whole files
```

`check_downloads.py` reports, per source in `project.xml`: missing or empty files, include
patterns that match nothing, gzip files the loader cannot read, format problems (FASTA/OBO/GAF/XML
sniffing, column counts), rows per taxon, and the share of rewritten gene IDs that are Alliance
CURIEs in the ID map. Unit tests: `python3 -m unittest discover -s docker/alliancemine/tests`.

## Environment Variables

See `.env.example` for all variables. Key ones:

- `RDS_HOST`, `RDS_PASSWORD` — RDS connection
- `ALLIANCE_RELEASE` — version to build (e.g., `9.0.0`)
- `BUILD_TYPE` — `test` (auto RC numbering) or `production`
- `SGD_DB_*` — SGD database connection (credentials in .env only)
- `SOLR_INDEX_URL`, `SOLR_AUTOCOMPLETE_URL` — Solr core URLs on multitenant

## Files

- `Dockerfile` — Alpine 3.20, Java 8, Perl, Python, aws-cli. Patches upstream bugs. The build uses
  the `project.xml` of the cloned `alliancemine` branch (`ALLIANCEMINE_BRANCH`), including its
  `dump="true"` checkpoints.
- `entrypoint.sh` — Resolves release, auto-increments RC, creates DBs, configures properties
- `scripts/` — Python build pipeline (build_full.py, extract_data.py, etc.)
- `properties/` — `envsubst` templates for InterMine properties

## See Also

- `docs/RELEASE_PROCESS.md` — Full release workflow
- `docs/BUILD_TROUBLESHOOTING.md` — Common errors and fixes

# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

AGR InterMine Builder is a build and deployment system for AllianceMine, a bioinformatics data warehouse that integrates genomic data from Model Organism Databases (MODs) for the Alliance of Genome Resources.

The system has two layers:
- **Docker build container** (`docker/alliancemine/`): Runs the InterMine build pipeline inside a container. This is the primary build system, proven with 9.0.0.
- **Host-side orchestration** (`src/`): Python CLI tools for RDS management, release versioning, and multi-mine orchestration via Docker SDK.

## Quick Start — Docker Build (Primary)

```bash
cd docker/alliancemine
cp .env.example .env           # Fill in RDS + SGD credentials
docker compose build            # Build image (~5 min)
docker compose run --rm alliancemine-builder build   # Full build (~5-8 hours)
```

Resume from checkpoint after failure:
```bash
docker compose run --rm -e RC_NUMBER=N alliancemine-builder build --start-from project_build --resume
```

## Host-Side CLI Tools

```bash
uv pip install -e .                                    # Install dependencies
python -m src.cli.rds_manager status                   # Check RDS
python -m src.cli.set_release show                     # Show Alliance releases
python -m src.cli.build_mines list                     # List available mines
```

### Testing and Linting
```bash
pytest                            # Run tests (4 test files in tests/)
pytest --cov=src --cov-report=html
black src/                        # Format (line-length: 100)
ruff check src/                   # Lint (line-length: 100, target: py39)
mypy src/                         # Type checking
```

## Architecture

### Two-Layer Design

```
Host (AllianceMineDev)                    Container (alliancemine-builder)
─────────────────────                     ─────────────────────────────────
src/cli/ (CLI tools)                      scripts/build_full.py (6-stage pipeline)
src/intermine_builder/ (orchestration)    scripts/extract_data.py (FMS + S3 data)
  └─ RDS provisioning                    scripts/promote_to_production.py
  └─ Docker SDK management               scripts/deploy_war.py
  └─ Multi-mine config                   entrypoint.sh (config, DB setup)
                                          project.xml (sources + dump checkpoints)
```

### Host-Side Modules (`src/`)

**MineBuilder** (`mine_builder.py`) — Top-level orchestrator. Creates Docker networks, builds images, manages containers.

**DockerManager** (`docker_manager.py`) — Docker container lifecycle via Python SDK.

**BuildExecutor** (`build_executor.py`) — Runs build stages inside containers.

**Config** (`config.py`) — Aggregates 6 nested dataclass configs from env vars.

**MineConfig** (`mine_config.py`) — `MineType` enum (4 mines), `BuildStage` enum, `MINE_CONFIGS` registry.

### Container-Side Scripts (`docker/alliancemine/scripts/`)

**build_full.py** — 6-stage pipeline: buildDB → extract_data → project_build → postprocess → war → deploy. Supports `--skip-stages`, `--start-from`, `--resume`.

**extract_data.py** — Downloads data from FMS snapshot API (49 files) and syncs SGD data from S3 (`s3://agr-db-backups/alliancemine/intermine/`).

**entrypoint.sh** — Resolves Alliance release from FMS API, auto-increments RC number, constructs versioned DB names, configures properties via `envsubst`, creates databases on RDS.

### Build Stages (Sequential, 6 stages)
1. **buildDB** — Create PostgreSQL schema (Gradle)
2. **extract_data** — Download data from FMS API + S3 (Python)
3. **project_build** — Data integration, 4-7 hours (intermine-scripts `project_build`)
4. **postprocess** — Indexing, summary tables, Solr search indexes (Gradle)
5. **war** — Build WAR file (Gradle)
6. **deploy** — Deploy WAR to Tomcat via cargoRedeployRemote (Gradle)

### Data Sources

**From FMS** (Alliance File Management System): BGI, GFF, GAF, FASTA, ontologies (OBO), disease, orthology, expression, alleles, variants — 49 files total.

**From S3** (`s3://agr-db-backups/alliancemine/intermine/`): SGD-specific data — protein properties, protein N-termini, yeast orthologs (fungidb, CGOB, C.glabrata, pombe), GFF-UTR, DB-UTR, ontologies (psi-mi.obo, goslim_yeast.obo), idresolver files.

**From SGD database** (external PostgreSQL at `www-rds-primary.yeastgenome.org`): SGD gene data, complexes, complementation data. Credentials in `.env` only, never committed.

### Database Structure (RDS)
- Main DB: `alliancemine_{version}_rc{N}` (test) or `alliancemine_{version}` (production)
- Profile DB: `alliancemine_userprofile` (persistent, shared across releases)
- Items DB: `alliancemine_items` (staging, rebuilt each integration)
- Checkpoint DBs: `alliancemine_{version}_rc{N}:{source-name}` (created by `project_build` via `CREATE DATABASE TEMPLATE`)

### Docker Configurations

- **`docker/alliancemine/`** — Active build container with RDS support (Alpine, Java 8, Python scripts)
- **`legacy/alliancemine-unified/`** — Previous all-in-one container (Tomcat+Solr+Build), archived
- **`legacy/wormmine-unified/`** — Previous WormMine container, archived
- **`legacy/`** — All deprecated configs, bash scripts, old Docker setups (reference only)

### Solr

Solr runs directly on the Multitenant host (172.31.59.87), port 8983. Cores:
- `alliancemine-search` / `alliancemine-autocomplete` — production
- `alliancemine-search-{version}` / `alliancemine-autocomplete-{version}` — per-release

InterMine does NOT auto-create Solr cores. They must be created by copying production core config before the postprocess step. The Solr URLs are hardcoded in two files in the alliancemine repo (`keyword_search.properties` and `objectstoresummary.config.properties`) and must be patched at runtime. The production WAR also references the old Docker hostname `agr.stage.alliancemine.solr.server` which must be mapped to `172.17.0.1` (Docker host gateway) via `/etc/hosts` or `--add-host`.

## Key Patterns

- Configuration via `.env` file + `envsubst` templates — never commit credentials
- `project_build` uses `-E UTF8` for RDS compatibility and server-side DB copies for checkpoints
- The Dockerfile patches `gradle.properties` (hardcoded `-Xmx48g`) and `SgdConverter.java` (dedup bug) — upstream PRs pending
- Container memory limit (56G) must exceed JVM heap (48g) by ~8G for native memory
- Profile DB is persistent across releases — not part of the build pipeline
- WAR has properties baked in at build time — post-deploy fixes needed for `webapp.baseurl`, `superuser.account`, and profile DB name

## Important Docs

- `docs/RELEASE_PROCESS.md` — End-to-end build and release workflow
- `docs/BUILD_TROUBLESHOOTING.md` — Common errors and fixes
- `docs/INFRASTRUCTURE_REFERENCE.md` — SSH hosts, RDS, machine specs (not committed, has credentials)

## Important Notes

- Build times: 5-8 hours total, `project_build` is ~70% (fbbt and xlaevis-fasta are bottlenecks)
- RDS: 500 GB gp3, checkpoint copies consume ~30-60 GB each — monitor storage during builds
- `legacy/` folder contains all deprecated approaches (reference only)
- Tests exist in `tests/` (4 files, 663 LOC) testing the `src/` orchestration layer
- Python target: >=3.9 (black targets py39-py311)
- Upstream fixes needed: alliancemine (`gradle.properties`, Solr URLs) and alliancemine-bio-sources (`SgdConverter` dedup)

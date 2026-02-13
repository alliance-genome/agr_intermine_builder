# Python Build System for InterMine

Python-based orchestration system for building InterMine instances in Docker containers with AWS RDS.

## Overview

This system replaces the legacy bash-based build scripts with a Python orchestration layer that provides:

- Automated Docker image building for each mine type
- Container lifecycle management (create, start, stop, cleanup)
- Build stage orchestration with progress tracking
- RDS database integration
- CLI interface for operation
- Build status monitoring

## Architecture

```
src/
├── intermine_builder/
│   ├── config.py           # Aggregated configuration (env vars, dataclasses)
│   ├── mine_config.py      # MineType/BuildStage enums, MINE_CONFIGS registry
│   ├── docker_manager.py   # Docker SDK container lifecycle
│   ├── build_executor.py   # Build stage execution inside containers
│   ├── mine_builder.py     # Top-level orchestrator
│   └── rds_provisioner.py  # RDS instance provisioning
├── cli/
│   ├── build_mines.py      # Build CLI (build, build-all, stage, status, cleanup)
│   ├── rds_manager.py      # RDS CLI (create, status, stop, start, delete)
│   └── set_release.py      # Release version CLI (current, next, show)
└── tests/
    ├── conftest.py          # Shared fixtures
    ├── test_config.py
    ├── test_mine_config.py
    ├── test_build_executor.py
    └── test_docker_manager.py
```

### Module Flow

```
CLI (build_mines.py) --> MineBuilder --> DockerManager --> BuildExecutor
                            |                                |
                       Config.from_env()           execute_command() in container
                            |
                      mine_config.py (MINE_CONFIGS registry)
```

- **MineBuilder** (`mine_builder.py`): Top-level orchestrator. Coordinates Docker networks, image builds, container creation, and delegates stage execution to BuildExecutor. Supports `with` statement for automatic cleanup.
- **DockerManager** (`docker_manager.py`): Manages Docker container lifecycle using the `docker` Python SDK. Containers tracked in-memory by `MineType`. Container naming: `{mine_type}-builder`.
- **BuildExecutor** (`build_executor.py`): Runs the 7 sequential build stages inside containers. Most stages use `./gradlew <task>` except `extract_data` (Python script) and `project_build` (Perl script from intermine-scripts). Workdir: `/root/{mine_type.value}`.
- **Config** (`config.py`): Aggregates nested dataclass configs (DatabaseConfig, RDSConfig, DockerConfig, InterMineConfig, AllianceConfig). Loads from env vars via `Config.from_env()` with dotenv support. Env var priority: `RDS_*` > `POSTGRES_*` > `DB_*`.
- **MineConfig** (`mine_config.py`): Defines `MineType` enum (4 mines), `BuildStage` enum (7 stages), and predefined `MineConfig` dataclasses in the `MINE_CONFIGS` dict.

## Installation

```bash
uv pip install -e .           # Runtime dependencies
uv pip install -e ".[dev]"    # With dev dependencies (pytest, ruff, mypy, black)
```

## Configuration

### Environment Variables

Create a `.env` file in the project root:

```bash
# RDS Connection (required)
RDS_HOST=your-rds-endpoint.rds.amazonaws.com
RDS_PORT=5432
RDS_USER=postgres
RDS_PASSWORD=your-password

# Alliance release version (default: 8.3.0)
ALLIANCE_RELEASE=8.3.0
```

### Mine Configurations

Each mine is pre-configured in `src/intermine_builder/mine_config.py`:

| Mine | Memory | CPUs | Heap | Release | Tomcat Port |
|------|--------|------|------|---------|-------------|
| AllianceMine | 32 GB | 8 | 16 GB | `ALLIANCE_RELEASE` env var | 8080 |
| WormMine | 24 GB | 6 | 12 GB | WS290 | 8081 |
| MouseMine | 28 GB | 7 | 14 GB | 1.10 | 8082 |
| FlyMine | 26 GB | 6 | 13 GB | 2.0 | 8083 |

## CLI Commands

### Build a Single Mine

```bash
python -m src.cli.build_mines build --mine alliancemine
python -m src.cli.build_mines build --mine alliancemine --rebuild      # Force image rebuild
python -m src.cli.build_mines build --mine alliancemine --skip-stages deploy
```

### Build All Mines

```bash
python -m src.cli.build_mines build-all
python -m src.cli.build_mines build-all --continue-on-error
python -m src.cli.build_mines build-all --rebuild
```

### Execute Single Stage

```bash
python -m src.cli.build_mines stage --mine alliancemine --stage buildDB
python -m src.cli.build_mines stage --mine wormmine --stage extract_data
```

### Status, Cleanup, List

```bash
python -m src.cli.build_mines status --mine alliancemine
python -m src.cli.build_mines cleanup --mine alliancemine
python -m src.cli.build_mines cleanup              # All mines
python -m src.cli.build_mines list
```

### Set Release Version

```bash
python -m src.cli.set_release current   # From Alliance FMS API
python -m src.cli.set_release next      # Next release from API
python -m src.cli.set_release 8.3.0     # Specific version
python -m src.cli.set_release show      # Show current + available
```

### RDS Management

```bash
python -m src.cli.rds_manager create    # Provision RDS instance (creates all mine DBs)
python -m src.cli.rds_manager status    # Check RDS status
python -m src.cli.rds_manager stop      # Stop RDS (cost saving)
python -m src.cli.rds_manager start     # Start stopped RDS
python -m src.cli.rds_manager delete    # Requires confirmation
```

### Python API

```python
from src.intermine_builder.mine_builder import MineBuilder
from src.intermine_builder.mine_config import MineType, BuildStage
from src.intermine_builder.config import Config

config = Config.from_env()

with MineBuilder(config) as builder:
    summary = builder.build_mine(MineType.ALLIANCEMINE)
    builder.execute_stage(MineType.ALLIANCEMINE, BuildStage.BUILD_DB)
    status = builder.get_mine_status(MineType.ALLIANCEMINE)
```

## Build Stages

Each mine goes through 7 sequential stages. Total time: 3-6 hours.

| # | Stage | Tool | Duration | Notes |
|---|-------|------|----------|-------|
| 1 | buildDB | `./gradlew buildDB` | 5-10 min | Creates PostgreSQL schema |
| 2 | extract_data | `python3 /root/scripts/extract_data.py` | 10-30 min | Downloads from Alliance FMS |
| 3 | project_build | `./project_build -b -T localhost` | 2-4 hours | Data integration (longest) |
| 4 | postprocess | `./gradlew postprocess` | 30-60 min | Indexing, summary tables |
| 5 | buildUserDB | `./gradlew buildUserDB` | 5-10 min | Skipped if profile DB exists |
| 6 | war | `./gradlew war` | 10-20 min | Builds WAR file |
| 7 | deploy | `./gradlew cargoRedeployRemote` | 5-10 min | Skipped if Tomcat not running |

## Docker Images

### AllianceMine (Primary)

The build-only container lives at `docker/alliancemine/`:

```
docker/alliancemine/
├── Dockerfile                     # Alpine 3.20, OpenJDK 8, build-only (no Tomcat/Solr)
├── docker-compose.yml             # 8 CPUs, 32 GB limits
├── .env.example                   # Environment template
├── entrypoint.sh                  # DB setup, envsubst, command dispatch
├── properties/
│   ├── alliancemine.properties.template   # Standard JDBC
│   └── hikaricp.properties.template       # HikariCP pooling (for testing)
└── scripts/
    ├── build_full.py              # 7-stage build pipeline
    ├── extract_data.py            # FMS data downloader
    ├── promote_db.py              # RC -> production DB rename
    └── deploy_war.py              # WAR deployment to EC2 Tomcat
```

```bash
cd docker/alliancemine
cp .env.example .env               # Fill in RDS credentials
docker compose build               # Build image (~15 min)
docker compose run --rm alliancemine-builder build    # Full build
docker compose run --rm alliancemine-builder bash      # Shell access
```

See [ALLIANCEMINE_BUILD_GUIDE.md](ALLIANCEMINE_BUILD_GUIDE.md) for the full operational guide including the release workflow (test RC builds, promotion, production deploy).

### Other Docker Setups

| Directory | Purpose | Status |
|-----------|---------|--------|
| `docker/alliancemine/` | Build-only container for AllianceMine | Active |
| `docker/alliancemine-unified/` | Self-contained AllianceMine (Tomcat + Solr + Build) | Active |
| `docker/wormmine-unified/` | Self-contained WormMine (port 8081) | Active |
| `legacy/multi_mine_rds/` | Multi-mine setup with shared base image | Deprecated |

## RDS Database Structure

Each mine uses two databases on the shared RDS instance:

| Mine | Main DB | Profile DB | Main Connections | Profile Connections |
|------|---------|------------|-----------------|-------------------|
| AllianceMine | `alliancemine_db` | `alliancemine_profiles_db` | 20 | 5 |
| WormMine | `wormmine_db` | `wormmine_profiles_db` | 15 | 5 |
| MouseMine | `mousemine_db` | `mousemine_profiles_db` | 18 | 5 |
| FlyMine | `flymine_db` | `flymine_profiles_db` | 16 | 5 |

Profile databases are persistent across rebuilds (contain user accounts, saved queries, gene lists). The `buildUserDB` stage auto-skips if the profile DB already has tables.

For AllianceMine builds using the `docker/alliancemine/` container, databases follow a versioned naming convention instead: `alliancemine_{ver}_rcN` for test builds and `alliancemine_{ver}` for production. See [ALLIANCEMINE_BUILD_GUIDE.md](ALLIANCEMINE_BUILD_GUIDE.md) for details.

## Data Sources

### AllianceMine
Data from Alliance FMS (File Management System) at `fms.alliancegenome.org`:
- `GENE-BASIC_AGR.json` - Gene basic information
- `ALLELE_AGR.json` - Allele data
- `DISEASE-ANNOTATION_AGR.json` - Disease annotations
- `PHENOTYPE-ANNOTATION_AGR.json` - Phenotype annotations
- `ORTHOLOGY-ALLIANCE_COMBINED.json` - Orthology relationships
- `GO-ANNOTATION_AGR.gaf` - GO annotations

### WormMine
Pre-provided WormBase data (mount to `/root/custom_data`):
- `annotations.gff3.gz` - Genome annotations
- `gene_association.gaf.gz` - GO annotations
- `orthologs.txt.gz` - Orthology data
- `alleles.tsv.gz` - Genetic variations
- `rnai_phenotypes.wb` - RNAi phenotypes
- `interactions.txt.gz` - Protein interactions

### MouseMine
MGI (Mouse Genome Informatics) data from `informatics.jax.org`.

### FlyMine
FlyBase data from `ftp.flybase.net`.

## Troubleshooting

### Container won't start
```bash
docker ps -a
docker logs alliancemine-builder
docker exec alliancemine-builder pg_isready -h $RDS_HOST -U $RDS_USER
```

### Build stage fails
```bash
docker exec alliancemine-builder cat /tmp/buildDB.log
python -m src.cli.build_mines stage --mine alliancemine --stage buildDB
```

### Out of memory
- Increase Docker resource limits (minimum 32 GB for AllianceMine)
- Check system memory: `docker stats`

### Database connection issues
- Verify RDS credentials in `.env`
- Check RDS security group allows inbound on port 5432
- Verify RDS endpoint: `pg_isready -h $RDS_HOST -p 5432`

## Development

```bash
uv pip install -e ".[dev]"
uv run pytest tests/ -v                          # Run tests (65 tests)
uv run pytest tests/ -v --cov=src --cov-report=html   # With coverage
uv run ruff check src/                           # Lint
uv run black src/ --check                        # Format check
uv run mypy src/                                 # Type check
```

## Contributing

When adding a new mine type:

1. Add `MineConfig` to `src/intermine_builder/mine_config.py`
2. Create Dockerfile in `docker/{mine}/`
3. Add data extraction logic
4. Add build scripts
5. Add tests to `tests/`

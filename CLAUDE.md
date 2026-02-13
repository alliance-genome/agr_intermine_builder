# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

AGR InterMine Builder is a Python-based orchestration system for building InterMine bioinformatics data warehouse instances. It manages multiple mines (AllianceMine, WormMine, FlyMine, MouseMine) that integrate genomic data from Model Organism Databases (MODs) for the Alliance of Genome Resources.

## Build Commands

### Installation
```bash
uv pip install -e .           # Install dependencies
uv pip install -e ".[dev]"    # Install with dev dependencies
```

### Building Mines
```bash
python -m src.cli.build_mines build --mine alliancemine
python -m src.cli.build_mines build-all
python -m src.cli.build_mines stage --mine alliancemine --stage buildDB
python -m src.cli.build_mines status --mine alliancemine
python -m src.cli.build_mines cleanup --mine alliancemine
python -m src.cli.build_mines list   # List available mines
```

### RDS Management
```bash
python -m src.cli.rds_manager create   # Provision RDS (interactive, creates all mine DBs)
python -m src.cli.rds_manager status   # Check RDS status
python -m src.cli.rds_manager stop     # Stop RDS (cost saving)
python -m src.cli.rds_manager start    # Start stopped RDS
python -m src.cli.rds_manager modify --instance-type db.t3.xlarge --apply-immediately
python -m src.cli.rds_manager delete   # Requires confirmation
```

### Set Alliance Release Version
```bash
python -m src.cli.set_release current  # From Alliance FMS API
python -m src.cli.set_release next     # Next release from API
python -m src.cli.set_release 8.3.0    # Specific version
python -m src.cli.set_release show     # Show current + available
```

### Docker Commands (Unified Container)
```bash
cd docker/alliancemine-unified
docker-compose build && docker-compose up -d      # Build and run webapp
docker-compose run --rm alliancemine build         # Full InterMine build
python3 build_mine.py       # Automated build with base version
python3 build_mine.py -1    # Build iteration (8.3.0-1)
```

### Testing and Linting
```bash
pytest                            # Run tests (testpaths: tests/)
pytest --cov=src --cov-report=html
black src/                        # Format (line-length: 100)
ruff check src/                   # Lint (line-length: 100, target: py39)
mypy src/                         # Type checking
```

## Architecture

### Core Module Flow

The system follows a layered orchestration pattern:

```
CLI (build_mines.py) → MineBuilder → DockerManager → BuildExecutor
                          ↓                              ↓
                     Config.from_env()          execute_command() in container
                          ↓
                    mine_config.py (MINE_CONFIGS registry)
```

**MineBuilder** (`src/intermine_builder/mine_builder.py`) is the top-level orchestrator. It coordinates the full build lifecycle: creates Docker networks, builds images, creates/starts containers, and delegates stage execution to BuildExecutor. Supports `with` statement for automatic cleanup.

**DockerManager** (`src/intermine_builder/docker_manager.py`) manages Docker container lifecycle using the `docker` Python SDK. Tracks containers and images in memory dicts keyed by `MineType`. Container naming convention: `{mine_type}-builder`.

**BuildExecutor** (`src/intermine_builder/build_executor.py`) runs the 7 sequential build stages inside containers. Most stages use `./gradlew <task>` except `extract_data` (shell script) and `project_build` (uses `project_build` script from intermine-scripts). Workdir is determined by mine type: `/root/{mine_type.value}`.

**Config** (`src/intermine_builder/config.py`) aggregates 6 nested dataclass configs (DatabaseConfig, RDSConfig, DockerConfig, EC2BuildConfig, InterMineConfig, AllianceConfig). Loads from env vars via `Config.from_env()` with dotenv support. Env var priority: `RDS_*` > `POSTGRES_*` > `DB_*` for database config.

**MineConfig** (`src/intermine_builder/mine_config.py`) defines `MineType` enum (4 mines), `BuildStage` enum (7 stages), and predefined `MineConfig` dataclasses in the `MINE_CONFIGS` dict. Each mine has specific resource limits, data sources, and tomcat ports (8080-8083).

### RDS Management (Two Implementations)

There are two RDS management paths:
- **`src/intermine_builder/rds_provisioner.py`** (`RDSProvisioner`): Used by `src/cli/rds_manager.py` CLI. Creates a single shared RDS instance with all mine databases. Uses PostgreSQL 15, creates `intermine-postgres15` parameter group.
- **`src/intermine_builder/aws/rds_manager.py`** (`RDSManager`): More advanced. Supports ephemeral build instances, build queues, instance resizing, and cost estimation. Uses PostgreSQL 13 parameter groups. Includes 7 mine configs (adds ratmine, zebrafish, yeastmine beyond the core 4).

### Build Stages (Sequential)
1. **buildDB** - Create PostgreSQL schema (Gradle)
2. **extract_data** - Download data from FMS/FTP (shell script)
3. **project_build** - Data integration, 2-4 hours (intermine-scripts)
4. **postprocess** - Indexing, summary tables (Gradle)
5. **buildUserDB** - User profile database, skipped if DB exists (Gradle + psql check)
6. **war** - Build WAR file (Gradle)
7. **deploy** / **cargoRedeployRemote** - Deploy to Tomcat, skipped if Tomcat not running (Gradle)

### Docker Configurations

Three Docker setups exist:
- **`docker/alliancemine-unified/`**: Self-contained AllianceMine (Tomcat+Solr+Build, port 8080)
- **`docker/wormmine-unified/`**: Self-contained WormMine (port 8081, uses custom_data mount)
- **`docker/multi_mine_rds/`**: Multi-mine setup with shared base image, connects to external RDS

### Database Structure (RDS Multi-tenant)
Each mine uses two databases on shared RDS: `{mine}_db` (main, rebuilt each time) and `{mine}_profiles_db` (persistent across rebuilds, contains user accounts/saved queries/gene lists). Profile DBs can be imported from production dumps via `BuildExecutor.import_profile_db()`.

## Key Patterns

- All CLI commands use `argparse` with subparsers; entry points defined in `pyproject.toml` as `build-mines` and `rds-manager`
- Configuration loads `.env` from project root automatically via `python-dotenv`
- `MineType` and `BuildStage` are the central enums used across all modules
- Docker containers get env vars for RDS connection at creation time, not runtime
- Build progress is reported via optional callbacks (`progress_callback`)
- Git hooks use `git-secrets` for pre-commit and commit-msg to prevent credential leaks

## Important Notes

- Build times: 3-6 hours per mine, `project_build` is ~53% of total time
- Profile databases are one-time creation - `stage_build_user_db` auto-skips if DB exists
- `legacy/` folder contains deprecated bash scripts (reference only)
- The `tests/` directory is configured in pyproject.toml but does not yet exist
- Python target: >=3.9 (black targets py39-py311)
- `src/builders/` and `src/lib/` directories referenced in older docs no longer exist

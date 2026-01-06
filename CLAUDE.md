# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

AGR InterMine Builder is a Python-based orchestration system for building InterMine bioinformatics data warehouse instances. It builds and manages multiple mines (AllianceMine, WormMine, FlyMine, MouseMine, etc.) that integrate genomic data from Model Organism Databases (MODs) for the Alliance of Genome Resources.

## Build Commands

### Installation
```bash
uv pip install -e .           # Install dependencies
uv pip install -e ".[dev]"    # Install with dev dependencies
```

### Building Mines

```bash
# Build a single mine
python -m src.cli.build_mines build --mine alliancemine

# Build all mines sequentially
python -m src.cli.build_mines build-all

# Execute a single build stage
python -m src.cli.build_mines stage --mine alliancemine --stage buildDB

# Check mine status
python -m src.cli.build_mines status --mine alliancemine

# Cleanup containers
python -m src.cli.build_mines cleanup --mine alliancemine
```

### RDS Management
```bash
uv run python -m src.cli.rds_manager create   # Provision RDS
uv run python -m src.cli.rds_manager status   # Check RDS status
uv run python -m src.cli.rds_manager stop     # Stop RDS (cost saving)
```

### Set Alliance Release Version
```bash
uv run python -m src.cli.set_release current  # From Alliance API
uv run python -m src.cli.set_release 8.3.0    # Specific version
uv run python -m src.cli.set_release show     # Show current
```

### Docker Commands (Unified Container)
```bash
cd docker/alliancemine-unified

# Build and run webapp
docker-compose build
docker-compose up -d

# Run full InterMine build
docker-compose run --rm alliancemine build

# Manual build steps inside container
docker-compose exec alliancemine bash
./gradlew buildDB
./project_build -b
./gradlew postprocess
./gradlew buildUserDB
./gradlew cargoRedeployRemote

# Automated build with versioning
python3 build_mine.py       # Base version
python3 build_mine.py -1    # Build iteration (8.3.0-1)
```

### Testing and Linting
```bash
pytest                            # Run tests
pytest --cov=src --cov-report=html  # With coverage
black src/                        # Format code
ruff check src/                   # Lint
mypy src/                         # Type checking
```

## Architecture

### Directory Structure
```
src/
├── builders/               # Mine build orchestration (legacy path)
├── intermine_builder/      # Core Python modules
│   ├── mine_config.py      # Mine configurations (resources, branches)
│   ├── docker_manager.py   # Docker container lifecycle
│   ├── build_executor.py   # Build stage execution
│   ├── mine_builder.py     # Main orchestrator
│   ├── config.py           # Configuration management
│   └── aws/
│       └── rds_manager.py  # AWS RDS provisioning
├── cli/
│   ├── build_mines.py      # Main CLI interface
│   ├── rds_manager.py      # RDS CLI
│   └── set_release.py      # Release version CLI
└── lib/
    └── config.py           # Additional config utilities

docker/
├── alliancemine-unified/   # Unified container (Tomcat+Solr+Build)
├── wormmine-unified/       # WormMine unified container
└── multi_mine_rds/         # Multi-mine RDS configs
    ├── alliancemine/
    └── wormmine/

legacy/                     # Deprecated bash-based system (reference only)
```

### Build Architecture

The system uses a **unified container** architecture where each mine runs in a single Docker container containing:
- Build environment (Java 8/11, Gradle, Perl)
- Apache Tomcat 9.0 (port 8080)
- Apache Solr 8.4 (port 8983)
- Connects to external AWS RDS PostgreSQL 15

### Build Stages (Sequential)
1. **buildDB** (5-10 min) - Create PostgreSQL schema
2. **extract_data** (10-30 min) - Download data from FMS/FTP
3. **project_build** (2-4 hours) - Data integration (LONGEST)
4. **postprocess** (30-60 min) - Indexing, summary tables
5. **buildUserDB** (5-10 min) - User profile database (one-time)
6. **war** (10-20 min) - Build WAR file
7. **deploy** (5-10 min) - Deploy to Tomcat

### Database Structure (RDS Multi-tenant)
Each mine uses two databases:
- Main DB: `{mine}_db` (e.g., `alliancemine_db`)
- Profile DB: `{mine}_profiles_db` (e.g., `alliancemine_profiles_db`)

Profile databases are persistent across rebuilds and contain user accounts, saved queries, and gene lists.

## Configuration

### Environment Variables (.env in project root)
```bash
RDS_HOST=your-rds-endpoint.rds.amazonaws.com
RDS_PORT=5432
RDS_USER=postgres
RDS_PASSWORD=your-password
RDS_DB_NAME=alliancemine_db
RDS_PROFILE_DB_NAME=alliancemine_profiles_db
ALLIANCE_RELEASE=8.2.0
AUTO_BUILD=false
```

### Mine Configurations
Mine-specific settings (memory, CPUs, branches) are in `src/intermine_builder/mine_config.py`:
- **AllianceMine**: 32GB RAM, 8 CPUs
- **WormMine**: 24GB RAM, 6 CPUs
- **MouseMine**: 28GB RAM, 7 CPUs
- **FlyMine**: 26GB RAM, 6 CPUs

### InterMine Properties
Generated at runtime from templates using environment variables:
- `docker/alliancemine-unified/alliancemine.properties.template`
- `docker/wormmine-unified/wormmine.properties.template`

## Key Patterns

### Python API Usage
```python
from src.intermine_builder import MineBuilder, MineType
from src.intermine_builder.config import Config

config = Config.from_env()
with MineBuilder(config) as builder:
    summary = builder.build_mine(MineType.ALLIANCEMINE)
    builder.execute_stage(MineType.WORMMINE, BuildStage.BUILD_DB)
```

### HikariCP Connection Pooling
All mines use HikariCP for database connections:
- Main DB: 15-20 connections per mine
- Profile DB: 5 connections per mine

### Data Sources
- **AllianceMine**: Alliance FMS (File Management System) - auto-download
- **WormMine**: Pre-provided WormBase data mounted to `/root/custom_data`
- Other mines: MOD-specific FTP/API sources

## Important Notes

- Build times: 3-6 hours per mine, 12-24 hours for all mines
- The `project_build` stage is the bottleneck (~53% of build time)
- Profile databases are one-time creation - skip `buildUserDB` if already exists
- Use `legacy/` folder for reference only - it contains deprecated bash scripts
- Docker resource allocation should match mine requirements (see mine_config.py)

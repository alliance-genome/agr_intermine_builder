# Python Build System for InterMine

Modern Python-based orchestration system for building InterMine instances in Docker containers with RDS support.

## Overview

This system replaces the legacy bash-based build scripts with a comprehensive Python orchestration layer that provides:

- **Automated Docker image building** for each mine type
- **Container lifecycle management** (create, start, stop, cleanup)
- **Build stage orchestration** with progress tracking
- **RDS database integration** with connection pooling
- **CLI interface** for easy operation
- **Parallel builds** support
- **Build history** and status monitoring

## Architecture

```
src/
├── builders/
│   ├── mine_config.py      # Mine configurations (AllianceMine, WormMine, etc.)
│   ├── docker_manager.py   # Docker container lifecycle
│   ├── build_executor.py   # Build stage execution
│   └── mine_builder.py     # Main orchestrator
├── cli/
│   └── build_mines.py      # CLI interface
└── lib/
    └── config.py           # Configuration management
```

## Installation

Using `uv` (recommended):

```bash
# Install dependencies
uv pip install -e .

# Or with development dependencies
uv pip install -e ".[dev]"
```

## Configuration

### Environment Variables

Create a `.env` file or set environment variables:

```bash
# RDS Configuration
RDS_HOST=your-rds-endpoint.rds.amazonaws.com
RDS_PORT=5432
RDS_USER=postgres
RDS_PASSWORD=your-password

# Optional: AWS credentials for RDS access
AWS_ACCESS_KEY_ID=your-key
AWS_SECRET_ACCESS_KEY=your-secret
AWS_REGION=us-east-1
```

### Mine Configurations

Each mine is pre-configured in `src/builders/mine_config.py`:

- **AllianceMine**: 32GB RAM, 8 CPUs, Alliance Release 8.2.0
- **WormMine**: 24GB RAM, 6 CPUs, WormBase WS290
- **MouseMine**: 28GB RAM, 7 CPUs, MGI Release 1.10
- **FlyMine**: 26GB RAM, 6 CPUs, FlyBase Release 2.0

## Usage

### CLI Commands

#### Build a Single Mine

```bash
# Build AllianceMine
python -m src.cli.build_mines build --mine alliancemine

# Build with image rebuild
python -m src.cli.build_mines build --mine wormmine --rebuild

# Build and skip certain stages
python -m src.cli.build_mines build --mine alliancemine --skip-stages deploy
```

#### Build All Mines

```bash
# Build all mines in sequence (AllianceMine → WormMine → MouseMine → FlyMine)
python -m src.cli.build_mines build-all

# Continue on failure
python -m src.cli.build_mines build-all --continue-on-error

# Force rebuild all images
python -m src.cli.build_mines build-all --rebuild
```

#### Execute Single Stage

```bash
# Execute just the buildDB stage
python -m src.cli.build_mines stage --mine alliancemine --stage buildDB

# Extract data only
python -m src.cli.build_mines stage --mine wormmine --stage extract_data
```

#### Check Status

```bash
# Check mine status
python -m src.cli.build_mines status --mine alliancemine
```

#### Cleanup

```bash
# Cleanup specific mine
python -m src.cli.build_mines cleanup --mine wormmine

# Cleanup all mines
python -m src.cli.build_mines cleanup
```

#### List Available Mines

```bash
python -m src.cli.build_mines list
```

### Python API

You can also use the Python API directly:

```python
from src.builders import MineBuilder, MineType
from src.lib.config import Config

# Load configuration
config = Config.from_env()

# Create builder
with MineBuilder(config) as builder:
    # Build a single mine
    summary = builder.build_mine(MineType.ALLIANCEMINE)

    # Build all mines
    summaries = builder.build_all_mines()

    # Execute single stage
    builder.execute_stage(MineType.WORMMINE, BuildStage.BUILD_DB)

    # Get status
    status = builder.get_mine_status(MineType.ALLIANCEMINE)
```

## Build Stages

Each mine goes through 7 build stages:

1. **buildDB** (5-10 minutes)
   - Creates PostgreSQL database schema
   - Initializes InterMine tables

2. **extract_data** (10-30 minutes)
   - Downloads data files from sources (FMS, FTP, etc.)
   - WormMine uses pre-provided custom data

3. **project_build** (2-4 hours) ⏰ **LONGEST STAGE**
   - Data integration and loading
   - Parses and loads biological data into database

4. **postprocess** (30-60 minutes)
   - Post-processing and indexing
   - Creates summary tables
   - Builds search indices

5. **buildUserDB** (5-10 minutes)
   - Creates user profile database
   - Initializes user account tables

6. **war** (10-20 minutes)
   - Builds WAR file for Tomcat deployment
   - Packages web application

7. **deploy** (5-10 minutes, optional)
   - Deploys to Tomcat
   - Skipped if Tomcat not running

**Total build time: 3-6 hours per mine**

## Docker Images

### Image Structure

Each mine has its own Dockerfile in `docker/multi_mine_rds/{mine}/`:

```
docker/multi_mine_rds/
├── alliancemine/
│   ├── Dockerfile
│   ├── build_full.sh
│   └── extract_data.sh
├── wormmine/
│   ├── Dockerfile
│   ├── build_full.sh
│   └── extract_data.sh
└── docker-compose.yml
```

### Building Images Manually

```bash
# Build AllianceMine image
cd docker/multi_mine_rds
docker build -t alliancemine-rds:latest ./alliancemine

# Build with custom branch
docker build \
  --build-arg ALLIANCEMINE_BRANCH=develop \
  -t alliancemine-rds:develop \
  ./alliancemine
```

## RDS Database Structure

Each mine uses two databases on the central RDS instance:

### AllianceMine
- **Main DB**: `alliancemine_db` (20 connections)
- **Profile DB**: `alliancemine_profiles_db` (5 connections)

### WormMine
- **Main DB**: `wormmine_db` (15 connections)
- **Profile DB**: `wormmine_profiles_db` (5 connections)

### MouseMine
- **Main DB**: `mousemine_db` (18 connections)
- **Profile DB**: `mousemine_profiles_db` (5 connections)

### FlyMine
- **Main DB**: `flymine_db` (16 connections)
- **Profile DB**: `flymine_profiles_db` (5 connections)

All databases use HikariCP connection pooling for optimal performance.

## Data Sources

### AllianceMine
Data from Alliance FMS (File Management System):
- Gene basic information
- Allele data
- Disease annotations
- Phenotype annotations
- Orthology relationships
- GO annotations

### WormMine
Pre-provided WormBase data (mount to `/root/custom_data`):
- `annotations.gff3.gz` - Genome annotations
- `gene_association.gaf.gz` - GO annotations
- `orthologs.txt.gz` - Orthology data
- `alleles.tsv.gz` - Genetic variations
- `rnai_phenotypes.wb` - RNAi phenotypes
- `interactions.txt.gz` - Protein interactions

### MouseMine
MGI (Mouse Genome Informatics) data:
- Gene data
- Phenotype data
- GO annotations

### FlyMine
FlyBase data:
- Gene data
- Allele data
- GO annotations

## Logging

Logs are written to:
- **Console**: Real-time build progress
- **Container logs**: `/tmp/*.log` inside containers
  - `buildDB.log`
  - `project_build.log`
  - `postprocess.log`
  - `buildUserDB.log`
  - `war.log`
  - `deploy.log`

View logs:
```bash
# Container logs
docker logs alliancemine-builder

# Specific stage log
docker exec alliancemine-builder cat /tmp/project_build.log

# Python CLI with verbose output
python -m src.cli.build_mines build --mine alliancemine --verbose
```

## Monitoring

### Build Progress

The system provides real-time progress updates:

```
2025-01-04 10:30:15 - INFO - Building Docker image for alliancemine...
2025-01-04 10:35:22 - INFO - Starting Stage 1: Build Database Schema
2025-01-04 10:40:18 - INFO - ✅ Build Database Schema completed in 295.3s
2025-01-04 10:41:02 - INFO - Starting Stage 2: Extract Data
...
```

### Build Summary

At completion, you'll see a summary:

```
==============================================================
AllianceMine build completed successfully!
==============================================================
Total time: 3.45 hours
Completed stages: 7/7
==============================================================
```

## Troubleshooting

### Container won't start
```bash
# Check Docker status
docker ps -a

# Check container logs
docker logs alliancemine-builder

# Check RDS connectivity
docker exec alliancemine-builder pg_isready -h $RDS_HOST -U $RDS_USER
```

### Build stage fails
```bash
# Check stage-specific log
docker exec alliancemine-builder cat /tmp/buildDB.log

# Re-run single stage
python -m src.cli.build_mines stage --mine alliancemine --stage buildDB
```

### Out of memory
- Increase Docker resource limits
- Reduce Gradle heap size in mine config
- Check system memory: `docker stats`

### Database connection issues
- Verify RDS credentials in `.env`
- Check RDS security group allows connections
- Verify RDS endpoint is accessible: `telnet $RDS_HOST 5432`

## Development

### Running Tests

```bash
# Install dev dependencies
uv pip install -e ".[dev]"

# Run tests
pytest

# With coverage
pytest --cov=src --cov-report=html
```

### Code Formatting

```bash
# Format code
black src/

# Check formatting
black --check src/

# Lint
ruff check src/
```

### Type Checking

```bash
mypy src/
```

## Comparison: Bash vs Python

### Old Bash System
```bash
# build.sh - monolithic script
./build.sh alliancemine
# - Hard to maintain
# - No progress tracking
# - Limited error handling
# - No status monitoring
```

### New Python System
```python
# Modular, object-oriented
builder.build_mine(MineType.ALLIANCEMINE)
# ✅ Easy to extend
# ✅ Progress tracking
# ✅ Comprehensive error handling
# ✅ Status monitoring
# ✅ Type safety
# ✅ Testable
```

## Contributing

When adding a new mine type:

1. Add configuration to `src/builders/mine_config.py`
2. Create Dockerfile in `docker/multi_mine_rds/{mine}/`
3. Add data extraction script
4. Add build automation script
5. Update `docker-compose.yml`
6. Test the build

## License

Alliance of Genome Resources

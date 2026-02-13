# AllianceMine Build Guide

Operational guide for building AllianceMine using the build-only Docker container with AWS RDS.

## Prerequisites

- Docker with at least 32 GB RAM and 8 CPUs allocated
- Access to the Alliance RDS PostgreSQL instance
- RDS credentials (`RDS_HOST`, `RDS_USER`, `RDS_PASSWORD`)
- The Alliance release version you are building (e.g., `8.3.0`)

## Quick Reference

```bash
cd docker/alliancemine

# First time: copy and fill in .env
cp .env.example .env

# Build the Docker image (~15 minutes)
docker compose build

# Run a test build (creates alliancemine_8_3_0_rc1)
BUILD_TYPE=test RC_NUMBER=1 docker compose run --rm alliancemine-builder build

# Promote RC to production (renames to alliancemine_8_3_0)
docker compose run --rm alliancemine-builder promote --rc 1

# Shell access for debugging
docker compose run --rm alliancemine-builder bash
```

---

## Container Architecture

The build container is a single-stage Alpine image with no Tomcat and no Solr. It exists solely to compile AllianceMine and populate databases on RDS.

```
┌──────────────────────────────────────────┐
│  alliancemine-builder container          │
│                                          │
│  Alpine 3.20 + OpenJDK 8                │
│  Perl CPAN modules (for project_build)   │
│  Python 3 (for build scripts)            │
│  PostgreSQL client (for DB operations)   │         ┌─────────────────────┐
│                                          │  JDBC   │  AWS RDS            │
│  /root/alliancemine/     (cloned repo)   │────────>│  PostgreSQL 15      │
│  /root/alliancemine-bio-sources/         │         │  500 GB gp3 storage │
│  /root/scripts/          (build scripts) │         └─────────────────────┘
│  /root/data/             (FMS downloads) │
│                                          │
│  Resources: 32 GB RAM, 8 CPUs           │
│  Image size: ~1.5 GB                    │
└──────────────────────────────────────────┘
```

What is baked into the image at build time:
- `alliancemine` and `alliancemine-bio-sources` Git repos (cloned and compiled)
- All Gradle dependencies pre-downloaded
- `project_build` script from `intermine-scripts`
- Python build scripts (`build_full.py`, `extract_data.py`, `promote_db.py`, `deploy_war.py`)
- InterMine properties template

What happens at container runtime:
- Wait for RDS connectivity
- Construct database names from version + build type
- Create databases on RDS if they don't exist
- Generate `alliancemine.properties` from template via `envsubst`
- Execute the requested command (`build`, `promote`, `deploy`, `extract`, `bash`)

---

## Configuration

### Environment Variables

Copy `.env.example` to `.env` and fill in values:

```bash
# Required
RDS_HOST=intermine-postgres.xxxxxxx.us-east-1.rds.amazonaws.com
RDS_PORT=5432
RDS_USER=postgres
RDS_PASSWORD=<your-password>
ALLIANCE_RELEASE=8.3.0

# Build control
BUILD_TYPE=test          # "test" or "production"
RC_NUMBER=1              # RC number for test builds

# Deployment (optional, only needed for WAR deploy to EC2 Tomcat)
# DEPLOY_HOST=ec2-host.example.com
# DEPLOY_PORT=9099

# Solr (optional, only needed if external Solr is running)
# SOLR_INDEX_URL=http://solr-host:8983/solr/alliancemine-search
# SOLR_AUTOCOMPLETE_URL=http://solr-host:8983/solr/alliancemine-autocomplete
```

### Properties Templates

Two properties templates are provided in `properties/`:

| Template | Use case |
|----------|----------|
| `alliancemine.properties.template` | Standard JDBC connections (default) |
| `hikaricp.properties.template` | HikariCP connection pooling (for testing) |

The entrypoint runs `envsubst` on the template to produce `/root/.intermine/alliancemine.properties` at runtime, substituting all `${RDS_*}` variables.

---

## Database Naming Convention

Database names are constructed from the release version and build type:

| Build type | Database name | Example |
|------------|---------------|---------|
| Test RC | `alliancemine_{ver}_rc{N}` | `alliancemine_8_3_0_rc1` |
| Production | `alliancemine_{ver}` | `alliancemine_8_3_0` |

Three databases are created per build:

| Database | Purpose | Lifecycle |
|----------|---------|-----------|
| Main DB | InterMine data warehouse | Rebuilt each time |
| `alliancemine_userprofile` | User accounts, saved queries, gene lists | Persistent, created once |
| `alliancemine_items` | Intermediary integration data | Can be dropped after build |

Version dots are converted to underscores: `8.3.0` becomes `8_3_0`.

---

## Build Pipeline

### The 7 Stages

The build runs 7 stages sequentially. Total time is 3-6 hours.

| # | Stage | Command | Duration | Notes |
|---|-------|---------|----------|-------|
| 1 | buildDB | `./gradlew buildDB` | 5-10 min | Creates PostgreSQL schema |
| 2 | extract_data | `python3 extract_data.py` | 10-30 min | Downloads from Alliance FMS API |
| 3 | project_build | `./project_build -b -T localhost` | 2-4 hours | Data integration. **Longest stage.** |
| 4 | postprocess | `./gradlew postprocess` | 30-60 min | Indexing, summary tables |
| 5 | buildUserDB | `./gradlew buildUserDB` | 5-10 min | **Skipped** if profile DB already has tables |
| 6 | war | `./gradlew war` | 10-20 min | Builds WAR file |
| 7 | deploy | `deploy_war.py` or `./gradlew cargoRedeployRemote` | 5-10 min | **Skipped** if no `DEPLOY_HOST` set |

### Data Downloaded in Stage 2

The `extract_data.py` script downloads these files from `fms.alliancegenome.org`:

| Data type | File | Target directory |
|-----------|------|-----------------|
| gene-basic | `GENE-BASIC_AGR.json` | `/root/data/genes/` |
| allele | `ALLELE_AGR.json` | `/root/data/alleles/` |
| disease | `DISEASE-ANNOTATION_AGR.json` | `/root/data/disease/` |
| phenotype | `PHENOTYPE-ANNOTATION_AGR.json` | `/root/data/phenotype/` |
| orthology | `ORTHOLOGY-ALLIANCE_COMBINED.json` | `/root/data/orthology/` |
| go-annotation | `GO-ANNOTATION_AGR.gaf` | `/root/data/go/` |

### Skipping and Resuming Stages

```bash
# Skip specific stages
docker compose run --rm alliancemine-builder build --skip-stages buildUserDB deploy

# Resume from a specific stage (skips all prior stages)
docker compose run --rm alliancemine-builder build --start-from postprocess

# Run only data extraction
docker compose run --rm alliancemine-builder extract
```

---

## Release Workflow

### 1. Test Build (RC)

Create a release candidate database and optionally deploy the WAR to a test Tomcat.

```bash
# .env
BUILD_TYPE=test
RC_NUMBER=1
ALLIANCE_RELEASE=8.3.0

# Run
docker compose run --rm alliancemine-builder build
```

This creates `alliancemine_8_3_0_rc1` on RDS and builds the WAR. If `DEPLOY_HOST` is set, the WAR is deployed to the test Tomcat port automatically.

### 2. Iterate on RC

If the test build needs changes, bump `RC_NUMBER` and rebuild:

```bash
RC_NUMBER=2 docker compose run --rm alliancemine-builder build
```

This creates `alliancemine_8_3_0_rc2`. Previous RC databases remain on RDS until manually dropped.

### 3. Promote to Production

Once an RC passes verification, promote it to the production name:

```bash
# Preview what will happen
docker compose run --rm alliancemine-builder promote --rc 2 --dry-run

# Execute the rename
docker compose run --rm alliancemine-builder promote --rc 2
```

This runs `ALTER DATABASE "alliancemine_8_3_0_rc2" RENAME TO "alliancemine_8_3_0"`. The script:
- Terminates active connections to the RC database
- Drops any existing production database with that name
- Renames the RC database
- Verifies the rename succeeded

### 4. Deploy to Production

After promotion, deploy the WAR to the production Tomcat on EC2:

```bash
docker compose run --rm alliancemine-builder deploy \
    --host ec2-host.example.com \
    --port 8080 \
    --manager manager \
    --password <tomcat-manager-password>
```

### 5. Cleanup

Drop old RC databases that are no longer needed:

```bash
# From inside the container
docker compose run --rm alliancemine-builder bash
psql -h $RDS_HOST -U $RDS_USER -d postgres -c 'DROP DATABASE "alliancemine_8_3_0_rc1";'
```

---

## Docker Operations

### Build the Image

```bash
cd docker/alliancemine
docker compose build
```

Build arguments (set in `.env` or pass directly):

| Argument | Default | Purpose |
|----------|---------|---------|
| `ALLIANCEMINE_BRANCH` | `master` | Git branch for alliancemine repo |
| `BIO_SOURCES_BRANCH` | `master` | Git branch for bio-sources repo |
| `IMAGE_TAG` | `latest` | Tag for the built image |

### Resource Limits

The `docker-compose.yml` enforces:
- **Limit**: 8 CPUs, 32 GB RAM
- **Reservation**: 4 CPUs, 16 GB RAM

These match the `GRADLE_OPTS` inside the container (`-Xmx16g -Xms8g`). If your Docker host has less memory, reduce both the compose limits and the Gradle heap proportionally.

### Volumes

| Host path | Container path | Purpose |
|-----------|----------------|---------|
| `./data` | `/root/data` | FMS downloaded data (persisted between runs) |

---

## Troubleshooting

### Build fails at project_build

This is the longest stage (2-4 hours). Common failures:

- **OutOfMemoryError**: Increase Docker RAM allocation. The container needs at least 32 GB.
- **Connection refused to localhost**: The `project_build` script expects `localhost` as the DB host, but the container connects to RDS. Check that `alliancemine.properties` was generated correctly:
  ```bash
  docker compose run --rm alliancemine-builder bash
  cat /root/.intermine/alliancemine.properties | grep db.production
  ```

### Cannot connect to RDS

```bash
# Test connectivity from inside the container
docker compose run --rm alliancemine-builder bash
pg_isready -h $RDS_HOST -p $RDS_PORT -U $RDS_USER
```

Check:
1. RDS security group allows inbound on port 5432 from your IP
2. RDS instance is running (not stopped for cost savings)
3. `.env` has correct `RDS_HOST`, `RDS_USER`, `RDS_PASSWORD`

### Database already exists

The entrypoint creates databases only if they don't exist. To force a fresh build:

```bash
docker compose run --rm alliancemine-builder bash
psql -h $RDS_HOST -U $RDS_USER -d postgres -c 'DROP DATABASE "alliancemine_8_3_0_rc1";'
exit

# Now rebuild
docker compose run --rm alliancemine-builder build
```

### Extract data fails

The FMS API may be temporarily unavailable. The script tries a direct URL first, then falls back to the S3 metadata API. If both fail:

```bash
# Download data separately
docker compose run --rm alliancemine-builder extract --release 8.3.0

# Then resume the build from the next stage
docker compose run --rm alliancemine-builder build --start-from project_build
```

### Viewing build logs

```bash
# Follow logs of a running container
docker logs -f alliancemine-builder

# Stage logs inside the container (if build is running)
docker exec alliancemine-builder cat /tmp/project_build.log
```

---

## Python Orchestration Layer

For programmatic builds (CI/CD, batch builds), the Python orchestration layer provides a higher-level interface.

### Installation

```bash
cd /path/to/agr_intermine_builder
uv pip install -e .
```

### CLI Commands

```bash
# Build a mine
python -m src.cli.build_mines build --mine alliancemine

# Build all mines sequentially
python -m src.cli.build_mines build-all

# Execute a single stage
python -m src.cli.build_mines stage --mine alliancemine --stage buildDB

# Check status
python -m src.cli.build_mines status --mine alliancemine

# Cleanup containers
python -m src.cli.build_mines cleanup --mine alliancemine

# List available mines
python -m src.cli.build_mines list
```

### Set Release Version

```bash
python -m src.cli.set_release current   # Current release from FMS API
python -m src.cli.set_release next      # Next release from FMS API
python -m src.cli.set_release 8.3.0     # Specific version
python -m src.cli.set_release show      # Show current + available
```

### Module Architecture

```
CLI (src/cli/build_mines.py)
  └─> MineBuilder (src/intermine_builder/mine_builder.py)
        ├─> Config.from_env() (src/intermine_builder/config.py)
        │     Loads .env, RDS credentials, Alliance release
        │     Priority: RDS_* > POSTGRES_* > DB_* > defaults
        │
        ├─> DockerManager (src/intermine_builder/docker_manager.py)
        │     Container lifecycle via docker Python SDK
        │     Containers keyed by MineType enum
        │     Naming: {mine_type}-builder (e.g., alliancemine-builder)
        │
        └─> BuildExecutor (src/intermine_builder/build_executor.py)
              7-stage pipeline: buildDB, extract_data, project_build,
              postprocess, buildUserDB, war, deploy
              Workdir: /root/{mine_type.value}
```

### Mine Registry

All mine configurations are defined in `src/intermine_builder/mine_config.py`:

| Mine | Memory | CPUs | Tomcat Port | Data Source |
|------|--------|------|-------------|-------------|
| AllianceMine | 32 GB | 8 | 8080 | Alliance FMS API |
| WormMine | 24 GB | 6 | 8081 | Pre-provided custom data |
| MouseMine | 28 GB | 7 | 8082 | MGI downloads |
| FlyMine | 26 GB | 6 | 8083 | FlyBase FTP |

AllianceMine is the primary focus. WormMine is not expected to have new releases.

---

## File Layout

```
docker/alliancemine/
├── Dockerfile                     # Single-stage Alpine build-only image
├── docker-compose.yml             # Container config with resource limits
├── .env.example                   # Environment variable template
├── entrypoint.sh                  # DB setup, envsubst, command dispatch
├── properties/
│   ├── alliancemine.properties.template   # Standard JDBC
│   └── hikaricp.properties.template       # HikariCP pooling (testing)
└── scripts/
    ├── build_full.py              # 7-stage build pipeline
    ├── extract_data.py            # FMS data downloader
    ├── promote_db.py              # RC -> production rename
    └── deploy_war.py              # WAR deployment to EC2 Tomcat

src/intermine_builder/             # Python orchestration layer
├── config.py                      # Aggregated configuration (env vars)
├── mine_config.py                 # MineType/BuildStage enums, MINE_CONFIGS
├── docker_manager.py              # Docker SDK container lifecycle
├── build_executor.py              # Build stage execution in containers
├── mine_builder.py                # Top-level orchestrator
└── rds_provisioner.py             # RDS instance management

src/cli/                           # Command-line interfaces
├── build_mines.py                 # build, build-all, stage, status, cleanup
├── rds_manager.py                 # create, status, stop, start, delete
└── set_release.py                 # current, next, show, <version>

tests/                             # Unit tests (65 tests, 57% coverage)
├── conftest.py                    # Shared fixtures
├── test_config.py                 # Config loading, validation
├── test_mine_config.py            # Docker paths, enums, naming
├── test_build_executor.py         # Stage commands, path resolution
└── test_docker_manager.py         # Container env vars, lifecycle

legacy/multi_mine_rds/             # Deprecated Docker configs (reference only)
```

---

## Development

### Running Tests

```bash
uv pip install -e ".[dev]"
uv run pytest tests/ -v
uv run pytest tests/ -v --cov=src --cov-report=html
```

### Linting and Formatting

```bash
uv run ruff check src/
uv run black src/ --check
uv run mypy src/
```

### Adding a Data Source

1. Add the FMS data type to `FILE_SPECS` in `docker/alliancemine/scripts/extract_data.py`
2. Add a corresponding `DataSource` entry in `src/intermine_builder/mine_config.py`
3. Ensure the AllianceMine `project.xml` references the new source
4. Create a data directory in the Dockerfile: `RUN mkdir -p /root/data/{new_source}`

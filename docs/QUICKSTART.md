# InterMine Builder - Quick Start Guide

## Prerequisites

- Docker installed and running (32 GB RAM, 8 CPUs minimum for AllianceMine)
- Python 3.9+
- `uv` package manager
- Access to the Alliance RDS PostgreSQL instance

## Option A: Docker Container (Recommended for AllianceMine)

The fastest path to a working build. No Python installation needed.

### 1. Configure

```bash
cd docker/alliancemine
cp .env.example .env
```

Edit `.env` with your RDS credentials (only required fields):

```bash
RDS_HOST=intermine-postgres.xxxxxxx.us-east-1.rds.amazonaws.com
RDS_PORT=5432
RDS_USER=postgres
RDS_PASSWORD=<your-password>
```

Everything else is auto-detected: `ALLIANCE_RELEASE` is fetched from the FMS API, `RC_NUMBER` is auto-incremented from RDS, and `BUILD_TYPE` defaults to `test`. See [ALLIANCEMINE_BUILD_GUIDE.md](ALLIANCEMINE_BUILD_GUIDE.md) for all options.

### 2. Build the Image

```bash
docker compose build
```

This takes ~15 minutes. It clones the alliancemine and bio-sources repos, compiles them, and installs all dependencies into the image.

### 3. Run the Build

```bash
docker compose run --rm alliancemine-builder build
```

This starts the 7-stage build pipeline:

| Stage | Duration | What it does |
|-------|----------|-------------|
| buildDB | 5-10 min | Creates PostgreSQL schema on RDS |
| extract_data | 10-30 min | Downloads data from Alliance FMS API |
| project_build | 2-4 hours | Data integration (longest stage) |
| postprocess | 30-60 min | Indexing and summary tables |
| buildUserDB | 5-10 min | Profile database (skipped if exists) |
| war | 10-20 min | Builds WAR file |
| deploy | 5-10 min | Deploys to Tomcat (skipped if no DEPLOY_HOST) |

**Total: 3-6 hours.**

The build creates database `alliancemine_8_3_0_rc1` on RDS (for test builds).

### 4. Monitor

In another terminal:

```bash
docker logs -f alliancemine-builder
```

### 5. Other Commands

```bash
# Shell access for debugging
docker compose run --rm alliancemine-builder bash

# Extract data only
docker compose run --rm alliancemine-builder extract

# Resume from a stage (e.g., after fixing an error)
docker compose run --rm alliancemine-builder build --start-from postprocess

# Skip stages
docker compose run --rm alliancemine-builder build --skip-stages buildUserDB deploy

# Promote RC to production
docker compose run --rm alliancemine-builder promote --rc 1
```

See [ALLIANCEMINE_BUILD_GUIDE.md](ALLIANCEMINE_BUILD_GUIDE.md) for the full operational guide.

---

## Option B: Python CLI (For Multi-Mine or Programmatic Builds)

The Python orchestration layer manages Docker containers for you and supports all 4 mines.

### 1. Install

```bash
cd /path/to/agr_intermine_builder
uv pip install -e .
```

### 2. Configure

Create `.env` in the project root:

```bash
RDS_HOST=intermine-postgres.xxxxxxx.us-east-1.rds.amazonaws.com
RDS_PORT=5432
RDS_USER=postgres
RDS_PASSWORD=<your-password>
ALLIANCE_RELEASE=8.3.0
```

### 3. Build

```bash
# Build AllianceMine
python -m src.cli.build_mines build --mine alliancemine

# Or build all mines sequentially (12-24 hours total)
python -m src.cli.build_mines build-all
```

What happens:
1. Builds the Docker image `alliancemine-builder:latest` from `docker/alliancemine/`
2. Creates a container with 32 GB RAM, 8 CPUs, RDS env vars
3. Starts the container and runs all 7 build stages
4. Reports progress and a build summary

### 4. Status and Cleanup

```bash
python -m src.cli.build_mines status --mine alliancemine
python -m src.cli.build_mines cleanup --mine alliancemine
python -m src.cli.build_mines list   # Show all available mines
```

### 5. Single Stage Execution

```bash
python -m src.cli.build_mines stage --mine alliancemine --stage buildDB
python -m src.cli.build_mines stage --mine alliancemine --stage extract_data
```

---

## What Gets Created on RDS

### AllianceMine (Docker container builds)

| Database | Purpose | Lifecycle |
|----------|---------|-----------|
| `alliancemine_{ver}_rcN` | Main data warehouse (test) | Rebuilt each RC |
| `alliancemine_{ver}` | Main data warehouse (production) | Promoted from RC |
| `alliancemine_userprofile` | User accounts, saved queries | Persistent, created once |
| `alliancemine_items` | Intermediary integration data | Can drop after build |

### Python CLI builds

| Mine | Main DB | Profile DB |
|------|---------|------------|
| AllianceMine | `alliancemine_db` | `alliancemine_profiles_db` |
| WormMine | `wormmine_db` | `wormmine_profiles_db` |
| MouseMine | `mousemine_db` | `mousemine_profiles_db` |
| FlyMine | `flymine_db` | `flymine_profiles_db` |

Profile databases are persistent across rebuilds.

---

## Troubleshooting

### Cannot connect to RDS

```bash
# Test from inside the container
docker compose run --rm alliancemine-builder bash
pg_isready -h $RDS_HOST -p $RDS_PORT -U $RDS_USER
```

Check: RDS security group allows inbound port 5432 from your IP. Check: RDS instance is running (not stopped).

### Build fails at project_build

This is the longest stage (2-4 hours). Usually an OutOfMemoryError. Make sure Docker has at least 32 GB RAM allocated.

### Container name already in use

```bash
python -m src.cli.build_mines cleanup --mine alliancemine
# Or manually:
docker rm -f alliancemine-builder
```

### Data extraction fails

The Alliance FMS API may be temporarily down. Download data separately and retry:

```bash
docker compose run --rm alliancemine-builder extract --release 8.3.0
docker compose run --rm alliancemine-builder build --start-from project_build
```

---

## Next Steps

- Full build container guide: [ALLIANCEMINE_BUILD_GUIDE.md](ALLIANCEMINE_BUILD_GUIDE.md)
- System architecture: [BUILD_SYSTEM.md](BUILD_SYSTEM.md)
- Docker architecture: [DOCKER_ARCHITECTURE.md](DOCKER_ARCHITECTURE.md)
- RDS setup: [RDS_SETUP.md](RDS_SETUP.md)
- Mine configurations: `src/intermine_builder/mine_config.py`

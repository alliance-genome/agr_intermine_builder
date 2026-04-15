# AllianceMine Quick Start Guide

## Prerequisites

- Docker and docker-compose installed
- AWS RDS PostgreSQL instance running
- RDS credentials configured in `.env`
- AWS CLI installed and configured (for downloading data)
- ~10GB disk space for data files

## 1. Configure Environment

Edit `.env` file with your RDS credentials:

```bash
ALLIANCE_RELEASE=8.3.0
DB_VERSION_SUFFIX=

RDS_HOST=your-rds-endpoint.rds.amazonaws.com
RDS_PORT=5432
RDS_USER=postgres
RDS_PASSWORD=your-password
```

## 2. Download Data Files

Download ALL required data files with a single command:

```bash
# Download all data (next/upcoming release - default)
python3 download_data.py

# Or download current/deployed release
python3 download_data.py --release-type current

# Dry run to see what would be downloaded
python3 download_data.py --dry-run
```

This downloads:
- **FMS API data:** Ontologies (GO, DO, ECO, etc.), disease associations, orthology, alleles, expression, GO annotations
- **Genome FASTA files:** All 7 organisms from authoritative MOD sources (WormBase, FlyBase, SGD, Ensembl)

**Total size:** ~5-10GB

All data is downloaded to `./data/` and mounted to `/root/data/` in the container.

## 3. Build Container

```bash
docker-compose build
```

This takes ~10-15 minutes and:
- Installs Java 8, Perl, PostgreSQL client
- Clones AllianceMine and bio-sources repositories
- Builds bio-sources with `gradlew install`
- Sets up Tomcat and Solr
- Reinstalls bio-sources for runtime use

## 3. Build Database (Automated)

### Option A: One Command Build (Recommended)

```bash
# Build base version
python3 build_mine.py

# Or build an iteration
python3 build_mine.py -1
```

This automatically:
1. Sets database version in `.env`
2. Restarts container
3. Runs `gradlew clean buildDB`

### Option B: Manual Steps

```bash
# Set database version (optional)
python3 set_db_version.py

# Start container
docker-compose up -d

# Run buildDB
docker-compose exec alliancemine bash -c \
  "cd /opt/intermine/alliancemine && ./gradlew clean buildDB"
```

The `buildDB` step takes ~5 minutes and:
- Creates database schema in RDS
- Generates genomic model from SO terms
- Merges all bio-source additions
- Stores metadata
- Creates search indexes

## 4. Verify Build

```bash
# Check logs
docker-compose logs -f alliancemine

# Check databases in RDS
docker-compose exec alliancemine psql -h $RDS_HOST -U $RDS_USER -d postgres -c "\l" | grep alliancemine

# Access container shell
docker-compose exec alliancemine bash
```

## Database Versions

Build multiple versions on same RDS:

```bash
# Version 8.3.0 (base)
python3 build_mine.py

# Version 8.3.0-1 (first iteration)
python3 build_mine.py -1

# Version 8.3.0-2 (second iteration)
python3 build_mine.py -2

# Version 8.3.0-test (test build)
python3 build_mine.py -test
```

Each version creates separate databases:
- `alliancemine_8_3_0`
- `alliancemine_8_3_0-1`
- `alliancemine_8_3_0-2`
- `alliancemine_8_3_0-test`

## Troubleshooting

### Container won't start
```bash
docker-compose logs alliancemine
```

### RDS connection issues
```bash
# Test connection
docker-compose exec alliancemine psql -h $RDS_HOST -U $RDS_USER -d postgres -c "SELECT 1;"
```

### Build fails
```bash
# Check Gradle output with stacktrace
docker-compose exec alliancemine bash -c \
  "cd /opt/intermine/alliancemine && ./gradlew clean buildDB --stacktrace"
```

### Rebuild container
```bash
docker-compose down
docker-compose build --no-cache
docker-compose up -d
```

## Ports

- **8080**: Tomcat (http://localhost:8080)
- **8983**: Solr (http://localhost:8983/solr)

## Useful Commands

```bash
# View logs
docker-compose logs -f alliancemine

# Shell access
docker-compose exec alliancemine bash

# Restart container
docker-compose restart alliancemine

# Stop everything
docker-compose down

# Check container status
docker-compose ps
```

# AllianceMine Quick Start Guide

Get AllianceMine running in 5 minutes!

## Prerequisites

- Docker and Docker Compose installed
- AWS RDS PostgreSQL instance created
- 32GB+ RAM available for Docker

## Step 1: Setup Environment (2 minutes)

```bash
cd docker/alliancemine-unified

# Copy environment template
cp .env.example .env

# Edit with your RDS credentials
nano .env  # or vim, code, etc.
```

Required values in `.env`:
```bash
RDS_HOST=your-rds-endpoint.us-east-1.rds.amazonaws.com
RDS_PORT=5432
RDS_USER=postgres
RDS_PASSWORD=your_secure_password

# Optional: Set AllianceMine release version
ALLIANCE_RELEASE=8.2.0

# Optional: Auto-build on first container start
AUTO_BUILD=false  # Set to 'true' for automatic build
```

## Step 2: Build Image (10-15 minutes)

```bash
# Build the Docker image
docker-compose build

# This will:
# - Download base images
# - Clone AllianceMine repositories
# - Compile bio-sources and InterMine
# - Install Tomcat and Solr
# - Create final unified image (~1.5GB)
```

## Step 3: Start Container (30 seconds)

```bash
# Start in background
docker-compose up -d

# Check status
docker-compose ps

# View logs
docker-compose logs -f
```

## Step 4: Verify Services (1 minute)

```bash
# Check Tomcat
curl http://localhost:8080/manager/status

# Check Solr
curl http://localhost:8983/solr/admin/info/system

# Check RDS connection
docker-compose exec alliancemine bash -c \
  "pg_isready -h \$RDS_HOST -p \$RDS_PORT -U \$RDS_USER"
```

## Step 5: Run Build (5-9 hours)

### Option A: Auto-Build on First Start

Set `AUTO_BUILD=true` in your `.env` file, then:
```bash
docker-compose up -d
# Build will run automatically on first start
# Check progress: docker-compose logs -f
```

The build will only run once (marker file created). Subsequent restarts will skip the build.

### Option B: Manual Build

```bash
# Run full build in background
docker-compose run -d alliancemine build

# Or run interactively to see progress
docker-compose run alliancemine build
```

### Option C: Step-by-step (for debugging)
docker-compose exec alliancemine bash
cd /opt/intermine/alliancemine
./gradlew buildDB
./project_build -b
./gradlew postprocess
./gradlew buildUserDB
./load_db_build_solr
./gradlew cargoRedeployRemote
```

## Step 6: Access AllianceMine

Once build completes:

- **Web Interface**: http://localhost:8080/alliancemine
- **API Endpoint**: http://localhost:8080/alliancemine/service
- **Solr Admin**: http://localhost:8983/solr

## Common Tasks

### View Logs

```bash
# All logs
docker-compose logs -f

# Inside container
docker-compose exec alliancemine bash
tail -f /opt/intermine/logs/intermine.log
tail -f /opt/tomcat/logs/catalina.out
```

### Restart Services

```bash
# Restart container
docker-compose restart

# Restart just Tomcat (inside container)
docker-compose exec alliancemine bash
${CATALINA_HOME}/bin/shutdown.sh
${CATALINA_HOME}/bin/startup.sh
```

### Shell Access

```bash
# Get bash shell
docker-compose exec alliancemine bash

# Or start fresh shell
docker-compose run --rm alliancemine bash
```

### Stop Everything

```bash
# Stop but keep data
docker-compose down

# Stop and remove volumes (CAREFUL!)
docker-compose down -v
```

## Troubleshooting

### "Cannot connect to RDS"

Check your RDS security group:
```bash
# From your machine
telnet your-rds-endpoint.amazonaws.com 5432

# Inside container
docker-compose exec alliancemine bash
psql -h $RDS_HOST -U $RDS_USER -d postgres
```

### "Out of memory"

Increase Docker memory limits:
```bash
# On Mac: Docker Desktop → Preferences → Resources
# On Linux: /etc/docker/daemon.json

# Then edit docker-compose.yml:
deploy:
  resources:
    limits:
      memory: 48G  # Increase this
```

### "Build failed"

```bash
# View build logs
docker-compose run alliancemine bash
cd /opt/intermine/alliancemine
./gradlew buildDB --stacktrace

# Check RDS connectivity
pg_isready -h $RDS_HOST -p $RDS_PORT -U $RDS_USER

# Check RDS databases exist
psql -h $RDS_HOST -U $RDS_USER -d postgres -c "\l"
```

## Next Steps

- Read full [README.md](README.md) for detailed documentation
- Check [Architecture](#) section for system design
- See [Monitoring](#) for production deployment
- Review [Cost Optimization](#) for AWS savings

## Support

- InterMine Docs: http://intermine.org/im-docs/
- Alliance GitHub: https://github.com/alliance-genome/alliancemine
- Issues: https://github.com/alliance-genome/agr_intermine_builder/issues

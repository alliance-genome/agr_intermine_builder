# AllianceMine Build Quick Guide

**Time estimate: 5-9 hours for full build**

## Prerequisites

✅ Docker & Docker Compose installed
✅ AWS RDS PostgreSQL instance running (see `../../RDS_SETUP.md`)
✅ 32GB+ RAM allocated to Docker
✅ 100GB+ free disk space
✅ Root `.env` file configured (at project root)

## Step 1: Verify Configuration (30 seconds)

**The unified container uses the existing configuration from the project root `.env` file.**

No need to create a local `.env` file! Just verify these values exist in `../../.env`:

```bash
# Check configuration
cd /path/to/agr_intermine_builder
cat .env | grep -E "RDS_|ALLIANCE_RELEASE|AUTO_BUILD"
```

**Should see:**
```bash
RDS_HOST=intermine-postgres.cmnnhlso7wdi.us-east-1.rds.amazonaws.com
RDS_PORT=5432
RDS_USER=postgres
RDS_PASSWORD=your_password
RDS_DB_NAME=alliancemine_db
RDS_PROFILE_DB_NAME=alliancemine_profiles_db
ALLIANCE_RELEASE=8.2.0
AUTO_BUILD=false  # Set to 'true' for automatic build
```

If any are missing, add them to the root `.env` file.

## Step 2: Build Docker Image (10-15 minutes)

```bash
cd docker/alliancemine-unified
docker-compose build
```

This downloads dependencies and creates the unified container (~1.5GB).

## Step 3: Start Container

### Option A: Manual Build (Recommended for first time)

```bash
# Start services
docker-compose up -d

# Verify services are running
docker-compose ps
curl http://localhost:8080/manager/status  # Tomcat
curl http://localhost:8983/solr/admin/info/system  # Solr

# Run build interactively (see progress)
docker-compose run alliancemine build

# Or run in background
docker-compose run -d alliancemine build

# Watch logs
docker-compose logs -f
```

### Option B: Auto-Build (Set AUTO_BUILD=true in .env)

```bash
# Just start - build happens automatically on first run
docker-compose up -d

# Watch progress
docker-compose logs -f
```

## Step 4: Monitor Build Progress

```bash
# Follow all logs
docker-compose logs -f

# Check from inside container
docker-compose exec alliancemine bash
tail -f /opt/intermine/logs/intermine.log

# Check build status
docker-compose exec alliancemine ps aux | grep -E "gradle|java"
```

## Step 5: Verify Build Completion

Build stages and approximate times:
1. ✅ **buildDB** (5-10 min) - Creates database schema
2. ✅ **Data extraction** (10-20 min) - Downloads source data
3. ✅ **project_build** (3-6 hours) - Integrates all data sources
4. ✅ **postprocess** (1-2 hours) - Creates indexes and relationships
5. ✅ **buildUserDB** (5-10 min) - Creates user profile database
6. ✅ **Solr indexing** (30-60 min) - Builds search indexes
7. ✅ **WAR deployment** (5-10 min) - Deploys web application

**Check if build succeeded:**
```bash
# Should see "BUILD SUCCESSFUL"
docker-compose logs | grep "BUILD SUCCESSFUL"

# Check web interface is available
curl http://localhost:8080/alliancemine/service/version

# Should return JSON with version info
```

## Step 6: Access AllianceMine

Once build completes:

- **Web Interface**: http://localhost:8080/alliancemine
- **API**: http://localhost:8080/alliancemine/service
- **Solr Admin**: http://localhost:8983/solr

## Common Commands

### View Logs
```bash
# All logs
docker-compose logs -f

# Last 100 lines
docker-compose logs --tail=100

# Specific log files (inside container)
docker-compose exec alliancemine tail -f /opt/intermine/logs/intermine.log
docker-compose exec alliancemine tail -f /opt/tomcat/logs/catalina.out
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

### Stop Everything
```bash
# Stop but keep data
docker-compose down

# Stop and remove volumes (⚠️ DELETES ALL DATA)
docker-compose down -v
```

### Rebuild from Scratch
```bash
# Stop and remove container
docker-compose down

# If using AUTO_BUILD, remove marker file
docker volume ls  # Find alliancemine_data volume
docker run --rm -v alliancemine_data:/data alpine rm -f /data/.build_complete

# Start again
docker-compose up -d
```

## Troubleshooting

### "Cannot connect to RDS"
```bash
# Test RDS connectivity
telnet your-rds-endpoint.amazonaws.com 5432

# Check RDS security group allows your IP
# Check .env file has correct credentials
```

### "Out of memory"
```bash
# Increase Docker memory limit
# Mac: Docker Desktop → Settings → Resources → Memory: 48GB
# Linux: /etc/docker/daemon.json

# Or reduce heap sizes in docker-compose.yml:
CATALINA_OPTS: "-Xmx12g -Xms6g"
SOLR_JAVA_MEM: "-Xmx3g -Xms2g"
```

### "Build failed"
```bash
# Get shell access
docker-compose exec alliancemine bash

# Check which step failed
cd /opt/intermine/alliancemine
./gradlew buildDB --stacktrace  # Test database creation
pg_isready -h $RDS_HOST -p $RDS_PORT -U $RDS_USER  # Test RDS connection

# View detailed logs
cat /opt/intermine/logs/intermine.log
```

### "Port already in use"
```bash
# Change ports in .env:
TOMCAT_PORT=8081
SOLR_PORT=8984

# Restart
docker-compose down
docker-compose up -d
```

## Next Steps

- Read full [README.md](README.md) for architecture details
- Check [DOCKER_ARCHITECTURE.md](../../DOCKER_ARCHITECTURE.md) for design decisions
- See [RDS_SETUP.md](../../RDS_SETUP.md) for RDS management

## Support

- InterMine Docs: http://intermine.org/im-docs/
- AllianceMine: https://github.com/alliance-genome/alliancemine
- Issues: https://github.com/alliance-genome/agr_intermine_builder/issues

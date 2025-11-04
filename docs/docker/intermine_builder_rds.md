# InterMine Builder for RDS

This Docker image provides a complete InterMine build environment that connects to AWS RDS PostgreSQL instead of a local database container.

## Features

This image includes **everything from the standard InterMine builder**:
- ✅ Java 8 (OpenJDK) 
- ✅ All required Perl modules (Ouch, LWP, URI, XML::DOM, etc.)
- ✅ Git, Maven, AWS CLI
- ✅ AllianceMine source code (cloned from GitHub)
- ✅ Bio-sources (cloned and built with `./gradlew install`)
- ✅ InterMine scripts (`project_build`, `load_db_build_solr`)
- ✅ Pre-built Gradle dependencies

**Plus RDS-specific features:**
- 🚀 Automatic RDS connection configuration
- 🔄 Connection retry with exponential backoff
- 📊 Health checks for RDS connectivity
- ⚡ HikariCP connection pooling optimized for cloud
- 🔧 Dynamic properties file generation

## Quick Start

### 1. Create ephemeral RDS instance (using main CLI)
```bash
# From project root
uv run python src/main.py rds create-build alliancemine --storage 500
# Note the endpoint returned
```

### 2. Configure environment
```bash
cd docker/intermine_builder_rds
cp .env.example .env
# Edit .env with your RDS endpoint and password
```

### 3. Build and run
```bash
# Build the image
docker-compose build

# Run the container
docker-compose up -d

# Enter the container
docker-compose exec intermine-builder-rds bash
```

### 4. Inside the container, run your build
```bash
# The container automatically configures RDS connection on startup

# Create database schema
./gradlew buildDB

# Run full InterMine build
./project_build

# Or run specific build steps
./load_db_build_solr
```

## Direct Docker Run (without docker-compose)

```bash
# Build the image
docker build -t agr-intermine-builder-rds:8.2.0 .

# Run with RDS connection
docker run -it \
  -e DB_HOST=your-rds-endpoint.rds.amazonaws.com \
  -e DB_PASSWORD=your-password \
  -e DB_USER=postgres \
  -e DB_NAME=alliancemine_db \
  -e DB_PROFILE_NAME=alliancemine_profiles_db \
  -e ALLIANCE_RELEASE_VERSION=8.2.0 \
  -v $(pwd)/logs:/root/logs \
  -v $(pwd)/data:/root/data \
  agr-intermine-builder-rds:8.2.0 bash
```

## Environment Variables

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `DB_HOST` | ✅ Yes | - | RDS endpoint |
| `DB_PASSWORD` | ✅ Yes | - | Database password |
| `DB_USER` | No | postgres | Database user |
| `DB_PORT` | No | 5432 | PostgreSQL port |
| `DB_NAME` | No | alliancemine_db | Main database |
| `DB_PROFILE_NAME` | No | alliancemine_profiles_db | Profile database |
| `ALLIANCE_RELEASE` | No | 8.2.0 | Alliance data release |
| `SOLR_HOST` | No | stage-intermine-solr.alliancegenome.org | Solr endpoint |

## Build Process Flow

1. **Container Start**: Entrypoint script runs
2. **RDS Wait**: Waits for RDS to be available (up to 30 attempts)
3. **Auth Setup**: Creates `.pgpass` for PostgreSQL authentication
4. **Database Check**: Creates databases if they don't exist
5. **Properties Configure**: Generates InterMine properties with RDS settings
6. **Ready**: Container is ready for build commands

## Monitoring

Check container health:
```bash
docker-compose exec intermine-builder-rds /rds-healthcheck.sh --comprehensive
```

View RDS connection info:
```bash
docker-compose exec intermine-builder-rds bash -c 'echo $DB_HOST:$DB_PORT'
```

Test database connection:
```bash
docker-compose exec intermine-builder-rds psql -h $DB_HOST -U $DB_USER -d $DB_NAME -c "SELECT version();"
```

## Cost Optimization

This setup is designed for **ephemeral builds**:
1. Create RDS instance → 2. Run build → 3. Dump database → 4. Terminate RDS

Typical cost: **~$5 per build** (8 hours on db.r6g.large)

vs. keeping large RDS 24/7: **~$100/month**

## Troubleshooting

### RDS Connection Failed
- Check security groups allow connection from your IP/container
- Verify DB_HOST is the full RDS endpoint
- Ensure DB_PASSWORD is correct

### Out of Memory
- Increase Docker memory limit
- Adjust GRADLE_OPTS in docker-compose.yml
- Use larger RDS instance type

### Build Fails
- Check `/root/logs/` for detailed error messages
- Verify Alliance data is accessible
- Ensure Solr endpoint is reachable

## Files in this Directory

- `Dockerfile` - Main container definition with all dependencies
- `docker-compose.yml` - Orchestration configuration
- `rds-entrypoint.sh` - Container startup script
- `configure-rds.sh` - RDS properties configuration
- `wait-for-rds.sh` - RDS availability checker
- `rds-healthcheck.sh` - Health monitoring script
- `.env.example` - Example environment configuration
# InterMine Builder for RDS

This document describes the unified Docker containers that build InterMine databases using AWS RDS PostgreSQL.

## Architecture

**Build Instance**: AllianceMineDev (172.31.60.197)
**Database**: AWS RDS PostgreSQL 15 (persistent, multi-tenant)
**Containers**: Unified images with Build + Tomcat + Solr

```
┌─────────────────────────────────────────────────────────────────┐
│  Build EC2 (AllianceMineDev) - 172.31.60.197                    │
│  ┌─────────────────────────────────────────────────────────┐    │
│  │ Docker Containers (Unified Images)                      │    │
│  │  • alliancemine-unified (Build + Tomcat + Solr)         │    │
│  │  • wormmine-unified (Build + Tomcat + Solr)             │    │
│  └─────────────────────────────────────────────────────────┘    │
│                              │                                  │
└──────────────────────────────┼──────────────────────────────────┘
                               │
                               ▼
┌─────────────────────────────────────────────────────────────────┐
│  AWS RDS PostgreSQL 15                                          │
│  intermine-postgres.cmnnhlso7wdi.us-east-1.rds.amazonaws.com    │
│                                                                 │
│  Databases (versioned naming):                                  │
│  • alliancemine_8_3_0, alliancemine_profiles_8_3_0              │
│  • wormmine_final, wormmine_userprofile                         │
└─────────────────────────────────────────────────────────────────┘
```

## Unified Container Features

Each unified container includes:
- **Java 11** (Amazon Corretto) for InterMine builds
- **Gradle 7.x** for build system
- **Apache Tomcat 9.0** for webapp testing
- **Apache Solr 8.4** (embedded) for search
- **PostgreSQL client** connecting to RDS
- **All Perl modules** (Ouch, LWP, URI, XML::DOM, etc.)
- **AWS CLI** for ECR and S3 access

## Quick Start

### 1. SSH to Build Instance

```bash
ssh ec2-user@172.31.60.197
cd agr_intermine_builder/docker/alliancemine-unified
```

### 2. Set Database Version (Optional)

```bash
# Base version (uses current release from Alliance API)
python3 set_db_version.py

# With iteration suffix
python3 set_db_version.py -1     # Creates alliancemine_8_3_0-1

# With custom suffix
python3 set_db_version.py -test  # Creates alliancemine_8_3_0-test
```

### 3. Build and Run Container

```bash
# Build the image
docker-compose build

# Start the container
docker-compose up -d

# Enter the container
docker exec -it alliancemine bash
```

### 4. Run InterMine Build

```bash
# Inside the container
./gradlew buildDB          # Build database (~4-7 hours)
./gradlew postProcess      # Run post-processors
./gradlew cargoDeployRemote # Deploy to production Tomcat
```

## Container Locations

| Mine | Directory | Container Name |
|------|-----------|----------------|
| AllianceMine | `docker/alliancemine-unified/` | alliancemine |
| WormMine | `docker/wormmine-unified/` | wormmine |

## Environment Variables

| Variable | Description | Default |
|----------|-------------|---------|
| `PGHOST` | RDS endpoint | intermine-postgres.cmnnhlso7wdi.us-east-1.rds.amazonaws.com |
| `PGPORT` | PostgreSQL port | 5432 |
| `PGUSER` | Database user | postgres |
| `PGPASSWORD` | Database password | (from .env) |
| `ALLIANCE_RELEASE` | Alliance release version | Current from API |

## Database Versioning

Databases follow a versioned naming convention:

```
<mine>_<release><suffix>
<mine>_profiles_<release><suffix>
```

**Examples:**

| Configuration | Main Database | Profile Database |
|--------------|---------------|------------------|
| Release 8.3.0 (base) | `alliancemine_8_3_0` | `alliancemine_profiles_8_3_0` |
| Release 8.3.0, iteration 1 | `alliancemine_8_3_0-1` | `alliancemine_profiles_8_3_0-1` |
| Release 8.3.0, test | `alliancemine_8_3_0-test` | `alliancemine_profiles_8_3_0-test` |
| WormMine (legacy) | `wormmine_final` | `wormmine_userprofile` |

## Automated Build Script

Use `build_mine.py` for automated builds:

```bash
# Set version and run full build
python3 build_mine.py -1

# This will:
# 1. Set database version to alliancemine_8_3_0-1
# 2. Restart container with new configuration
# 3. Run ./gradlew buildDB
```

## Build Stages

| Stage | Command | Description |
|-------|---------|-------------|
| buildDB | `./gradlew buildDB` | Full database build |
| postProcess | `./gradlew postProcess` | Run post-processors |
| buildUserDB | `./gradlew buildUserDB` | Build user profile database |
| cargoDeployRemote | `./gradlew cargoDeployRemote` | Deploy WAR to production |

## Monitoring

```bash
# Check container status
docker ps

# View build logs
docker logs alliancemine --tail 100

# Check Gradle build progress
docker exec alliancemine cat intermine_log.log

# Check RDS connectivity
docker exec alliancemine psql -h $PGHOST -U $PGUSER -c "SELECT version();"
```

## Troubleshooting

### RDS Connection Failed

```bash
# Check security groups allow connection from EC2
aws ec2 describe-security-groups --group-ids sg-xxxxx

# Test RDS connectivity
pg_isready -h intermine-postgres.cmnnhlso7wdi.us-east-1.rds.amazonaws.com -U postgres
```

### Out of Memory

```bash
# Check container memory usage
docker stats alliancemine

# Adjust JAVA_OPTS in docker-compose.yml
environment:
  - JAVA_OPTS=-Xmx8g -Xms4g
```

### Build Fails

```bash
# Check build logs
docker exec alliancemine tail -100 intermine_log.log

# Check Gradle output
docker exec alliancemine cat /root/.gradle/daemon/*/daemon-*.out.log
```

## Files in Unified Containers

```
docker/alliancemine-unified/
├── Dockerfile                    # Container definition
├── docker-compose.yml            # Orchestration config
├── alliancemine.properties.template  # InterMine config template
├── set_db_version.py             # Database version setter
├── build_mine.py                 # Automated build script
├── tomcat/
│   └── server.xml               # Tomcat configuration
└── solr/
    └── solr.xml                 # Solr configuration
```

## Related Documentation

- [EC2 Architecture](../architecture/ec2-step-functions-design.md)
- [Multi-MOD Architecture](../architecture/multi-mod-architecture.md)
- [Database Versioning](../../docker/alliancemine-unified/DATABASE_VERSIONING.md)
- [WormMine Setup](../WORMMINE_MULTITENANT_SETUP.md)

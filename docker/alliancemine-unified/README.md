# AllianceMine Unified Container

**Simplified single-container deployment for AllianceMine with AWS RDS**

This Docker image consolidates all InterMine components (except PostgreSQL) into a single optimized container:
- **Build Environment**: Java 11, Gradle, InterMine tools
- **Apache Tomcat 9.0**: Web application server
- **Apache Solr 8.4**: Search engine
- **Connects to**: AWS RDS PostgreSQL 15

## Why Unified Container?

### Previous Architecture (Multi-Container)
```
┌─────────────┐   ┌────────────┐   ┌──────────┐   ┌────────────────┐
│   Builder   │──▶│  Tomcat    │──▶│   Solr   │──▶│  PostgreSQL    │
│  Container  │   │ Container  │   │Container │   │   Container    │
└─────────────┘   └────────────┘   └──────────┘   └────────────────┘
```

### New Architecture (Unified + RDS)
```
┌────────────────────────────────┐         ┌────────────────┐
│   AllianceMine Unified         │────────▶│   AWS RDS      │
│   • Builder                    │  JDBC   │  PostgreSQL 15 │
│   • Tomcat (port 8080)         │         │                │
│   • Solr   (port 8983)         │         │  500GB gp3     │
└────────────────────────────────┘         └────────────────┘
```

### Benefits
- ✅ **Simpler deployment**: Single container to manage
- ✅ **Faster communication**: Tomcat ↔ Solr via localhost
- ✅ **Resource efficient**: Shared JVM, no network overhead
- ✅ **Easier debugging**: All logs in one place
- ✅ **InterMine standard**: How most InterMine instances run
- ✅ **Costs optimized**: RDS handles heavy database workload

## Quick Start

### Prerequisites

1. **AWS RDS instance created**:
   ```bash
   cd /path/to/agr_intermine_builder
   uv run python -m src.cli.rds_manager create
   ```

2. **Environment file configured** (`.env`):
   ```bash
   RDS_HOST=intermine-postgres.cmnnhlso7wdi.us-east-1.rds.amazonaws.com
   RDS_PORT=5432
   RDS_USER=postgres
   RDS_PASSWORD=your_password_here
   ```

### Build Image

```bash
cd docker/alliancemine-unified

# Build with defaults
docker-compose build

# Or build with custom branches
docker-compose build --build-arg ALLIANCEMINE_BRANCH=develop
```

### Run Container

**Mode 1: Web Application (Tomcat + Solr)**
```bash
docker-compose up -d

# Check status
docker-compose ps
docker-compose logs -f

# Access services
curl http://localhost:8080/alliancemine/service/version
curl http://localhost:8983/solr/admin/info/system
```

**Mode 2: Auto-Build on First Start**
```bash
# Set AUTO_BUILD=true in .env, then:
docker-compose up -d

# Build runs automatically on first start only
# Watch progress: docker-compose logs -f
```

**Mode 3: Manual Build InterMine**
```bash
# Run full build process
docker-compose run --rm alliancemine build

# Or step-by-step
docker-compose run --rm alliancemine bash
./gradlew buildDB
./project_build -b
./gradlew postprocess
./gradlew buildUserDB
./gradlew cargoRedeployRemote
```

**Mode 4: Development/Debug**
```bash
# Get shell access
docker-compose exec alliancemine bash

# Or start with bash
docker-compose run --rm alliancemine bash
```

### Custom Release Version

To build a specific AllianceMine release:

```bash
# Set in .env
ALLIANCE_RELEASE=8.3.0

# Rebuild image with new version
docker-compose build --build-arg ALLIANCE_RELEASE=8.3.0

# Or pass directly
docker-compose build --build-arg ALLIANCE_RELEASE=8.3.0

# The version appears in:
# - Web interface (project.releaseVersion)
# - Docker image label
# - Container environment
```

## Architecture Details

### Container Layers

The Dockerfile uses multi-stage builds:

**Stage 1: Builder**
- Base: `eclipse-temurin:11-jdk-alpine`
- Clones AllianceMine and bio-sources repositories
- Compiles with Gradle
- Installs Perl modules
- Size: ~2GB (discarded in final image)

**Stage 2: Solr Builder**
- Downloads and verifies Apache Solr 8.4.1
- Prepares Solr distribution
- Size: ~500MB (merged into final)

**Stage 3: Runtime** (final image)
- Base: `eclipse-temurin:11-jre-alpine` (JRE only)
- Installs Apache Tomcat 9.0
- Copies Solr from stage 2
- Copies compiled InterMine from stage 1
- Final size: ~1.5GB

### Resource Allocation

**Default Settings**:
- **Container**: 32GB RAM, 8 vCPUs
- **Tomcat Heap**: 16GB (`-Xmx16g`)
- **Solr Heap**: 4GB (`-Xmx4g`)
- **Gradle Build**: 4GB heap

**Customization** (docker-compose.yml):
```yaml
environment:
  CATALINA_OPTS: "-Xmx20g -Xms10g -XX:+UseG1GC"
  SOLR_JAVA_MEM: "-Xmx6g -Xms3g"

deploy:
  resources:
    limits:
      cpus: '16'
      memory: 48G
```

### Ports

| Service | Port | Description |
|---------|------|-------------|
| Tomcat  | 8080 | Web application, API |
| Solr    | 8983 | Search admin interface |

### Volumes

| Volume | Purpose | Size Estimate |
|--------|---------|---------------|
| `alliancemine-data` | Data files, build artifacts | ~50GB |
| `solr-data` | Solr indexes | ~10GB |
| `alliancemine-logs` | InterMine logs | ~5GB |
| `tomcat-logs` | Tomcat access/error logs | ~2GB |

## Configuration

### Environment Variables

**Required**:
- `RDS_HOST`: RDS endpoint hostname
- `RDS_PORT`: RDS port (default: 5432)
- `RDS_USER`: PostgreSQL username
- `RDS_PASSWORD`: PostgreSQL password
- `RDS_DB_NAME`: Main database name (default: alliancemine_db)
- `RDS_PROFILE_DB_NAME`: Profile database (default: alliancemine_profiles_db)

**Optional**:
- `ALLIANCE_RELEASE`: Release version (default: 8.2.0)
- `AUTO_BUILD`: Auto-build on first start (`true`/`false`, default: `false`)
- `TOMCAT_PORT`: Tomcat port (default: 8080)
- `SOLR_PORT`: Solr port (default: 8983)
- `CATALINA_OPTS`: Tomcat JVM options
- `SOLR_JAVA_MEM`: Solr heap size

**AUTO_BUILD Behavior**:
- When `AUTO_BUILD=true`, the container will automatically run the full InterMine build on first start
- A marker file (`/opt/intermine/.build_complete`) prevents rebuilding on subsequent restarts
- To rebuild, remove the marker: `docker-compose exec alliancemine rm /opt/intermine/.build_complete`
- Useful for automated deployments and CI/CD pipelines

### InterMine Properties

Properties are generated at runtime from template using environment variables.

**Location**: `/opt/intermine/.intermine/alliancemine.properties`

**Key settings**:
- HikariCP connection pooling (20 connections for main DB)
- RDS connection details (from environment)
- Tomcat manager credentials
- Solr URL (localhost:8983)

**Customization**:
1. Edit `alliancemine.properties.template`
2. Rebuild image
3. Or mount custom file:
   ```yaml
   volumes:
     - ./custom.properties:/opt/intermine/.intermine/alliancemine.properties
   ```

## Build Process

### Full Build Timeline

Typical build on db.t3.large RDS + 32GB container:

| Stage | Duration | CPU | Memory |
|-------|----------|-----|--------|
| buildDB | 5-10 min | Medium | 4GB |
| Extract data | 10-20 min | Low | 2GB |
| Project build | 3-6 hours | High | 16GB |
| Post-process | 1-2 hours | High | 12GB |
| buildUserDB | 5-10 min | Low | 2GB |
| Solr indexing | 30-60 min | High | 8GB |
| WAR deployment | 5-10 min | Medium | 4GB |
| **Total** | **5-9 hours** | - | - |

### Build Commands

**Standard build**:
```bash
docker-compose run --rm alliancemine build
```

**Individual steps**:
```bash
docker-compose exec alliancemine bash

cd /opt/intermine/alliancemine

# 1. Create database schema
./gradlew buildDB

# 2. Load data sources
./project_build -b

# 3. Post-processing (create indexes, relationships)
./gradlew postprocess

# 4. Create user profile database
./gradlew buildUserDB

# 5. Build Solr search indexes
./load_db_build_solr

# 6. Build and deploy WAR to Tomcat
./gradlew cargoRedeployRemote
```

### Incremental Builds

If data changes but schema doesn't:
```bash
# Drop and rebuild specific data source
./gradlew integrate -Psource=go-annotation

# Rebuild search indexes only
./load_db_build_solr

# Redeploy webapp
./gradlew cargoRedeployRemote
```

## Monitoring & Debugging

### Container Health

```bash
# Check container health
docker-compose ps

# View health check logs
docker inspect alliancemine | jq '.[0].State.Health'

# Manual health check
curl http://localhost:8080/alliancemine/service/version
```

### Logs

```bash
# All logs
docker-compose logs -f

# Specific log files inside container
docker-compose exec alliancemine bash
tail -f /opt/intermine/logs/intermine.log
tail -f /opt/tomcat/logs/catalina.out
tail -f /var/solr/logs/solr.log
```

### Resource Usage

```bash
# Container stats
docker stats alliancemine

# Detailed resource usage
docker-compose exec alliancemine bash
ps aux --sort=-%mem | head -20
free -h
df -h
```

### Database Connections

```bash
# Check RDS connectivity
docker-compose exec alliancemine bash
pg_isready -h $RDS_HOST -p $RDS_PORT -U $RDS_USER

# Active connections
psql -h $RDS_HOST -U $RDS_USER -d $RDS_DB_NAME \
     -c "SELECT count(*), state FROM pg_stat_activity GROUP BY state;"
```

## Troubleshooting

### Container Won't Start

**Check RDS connectivity**:
```bash
docker-compose logs alliancemine | grep -i "waiting for postgres"

# Test manually
telnet intermine-postgres.cmnnhlso7wdi.us-east-1.rds.amazonaws.com 5432
```

**Check environment variables**:
```bash
docker-compose config
docker-compose exec alliancemine env | grep RDS
```

### Build Failures

**Out of memory**:
```bash
# Increase container memory in docker-compose.yml
deploy:
  resources:
    limits:
      memory: 48G

# Or reduce heap sizes
environment:
  CATALINA_OPTS: "-Xmx12g -Xms6g"
```

**Database connection errors**:
- Check RDS security group allows access
- Verify credentials in `.env`
- Check RDS status: `uv run python -m src.cli.rds_manager status`

**Gradle build errors**:
```bash
# Clean and rebuild
docker-compose exec alliancemine bash
cd /opt/intermine/alliancemine
./gradlew clean
./gradlew buildDB --stacktrace
```

### Solr Issues

**Solr not starting**:
```bash
# Check Solr logs
docker-compose exec alliancemine bash
cat /var/solr/logs/solr.log

# Restart Solr
/opt/solr/bin/solr restart -p 8983
```

**Search not working**:
```bash
# Rebuild Solr indexes
cd /opt/intermine/alliancemine
./load_db_build_solr

# Check Solr status
curl http://localhost:8983/solr/admin/cores?action=STATUS
```

### Webapp Issues

**Tomcat not responding**:
```bash
# Check Tomcat logs
docker-compose exec alliancemine bash
tail -f /opt/tomcat/logs/catalina.out

# Restart Tomcat
${CATALINA_HOME}/bin/shutdown.sh
${CATALINA_HOME}/bin/startup.sh
```

**WAR not deployed**:
```bash
# Check webapps directory
ls -la /opt/tomcat/webapps/

# Redeploy
cd /opt/intermine/alliancemine
./gradlew cargoRedeployRemote --stacktrace
```

## Maintenance

### Backups

**Database backup** (handled by RDS):
- Automated daily snapshots (7-day retention)
- Manual snapshots before major changes

**Solr indexes**:
```bash
# Backup Solr data
docker run --rm -v alliancemine_solr:/data -v $(pwd):/backup \
    alpine tar czf /backup/solr-backup-$(date +%Y%m%d).tar.gz -C /data .
```

**Container volumes**:
```bash
# Export all volumes
docker-compose down
docker run --rm -v alliancemine_data:/data -v $(pwd):/backup \
    alpine tar czf /backup/alliancemine-data-$(date +%Y%m%d).tar.gz -C /data .
```

### Updates

**Update AllianceMine code**:
```bash
# Rebuild image with latest code
docker-compose build --no-cache

# Or specific branch
docker-compose build --build-arg ALLIANCEMINE_BRANCH=develop
```

**Update container base images**:
```bash
# Pull latest base images
docker-compose build --pull --no-cache
```

### Scaling

**Increase resources**:
1. Edit `docker-compose.yml` resource limits
2. Restart: `docker-compose up -d`

**Multiple instances** (for high availability):
- Deploy multiple containers with load balancer
- Share RDS instance (already done)
- Share Solr indexes via NFS/EBS

## Cost Optimization

### Current Setup Costs

**AWS RDS** (db.t3.large + 500GB):
- Compute: ~$105/month
- Storage: ~$55/month
- **Total**: ~$160/month

**Container hosting** (depends on platform):
- AWS ECS: ~$50-100/month (Fargate)
- AWS EC2: ~$75/month (t3.xlarge on-demand)
- Local: $0

**Total estimated**: **$210-260/month**

### Cost Savings

**Stop RDS when not building**:
```bash
# Stop RDS (saves ~$105/month)
uv run python -m src.cli.rds_manager stop

# Start when needed
uv run python -m src.cli.rds_manager start
```

**Use Spot instances** (if on EC2):
- Save 70% on compute costs
- Configure interruption handling

**Optimize RDS size**:
- Use db.t3.medium for development (~$52/month vs $105)
- Scale up only during builds

## Next Steps

1. **Test the setup**:
   ```bash
   docker-compose up -d
   docker-compose exec alliancemine bash
   ```

2. **Run a build**:
   ```bash
   docker-compose run --rm alliancemine build
   ```

3. **Monitor progress**:
   ```bash
   docker-compose logs -f
   ```

4. **Access services**:
   - WebApp: http://localhost:8080/alliancemine
   - Solr: http://localhost:8983/solr

## Support

- **InterMine Docs**: http://intermine.org/im-docs/
- **Docker Docs**: https://docs.docker.com/
- **Alliance GitHub**: https://github.com/alliance-genome/alliancemine

## License

InterMine is licensed under the LGPL.
AllianceMine is maintained by the Alliance of Genome Resources.

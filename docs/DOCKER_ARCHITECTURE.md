# Docker Architecture for AllianceMine

## Overview

This document explains the evolution of the AllianceMine Docker architecture from multi-container to unified single-container deployment with AWS RDS.

## Architecture Evolution

### Phase 1: Original Multi-Container (Legacy)

**Components** (4 separate containers):
```
┌─────────────────┐
│   Builder       │  Alpine + Java 8 + Gradle
│   Container     │  Builds InterMine application
└─────────────────┘
         ↓
┌─────────────────┐
│   PostgreSQL    │  PostgreSQL 13
│   Container     │  Stores all mine data
└─────────────────┘
         ↑
┌─────────────────┐
│   Tomcat        │  Tomcat 8.5
│   Container     │  Serves web application
└─────────────────┘
         ↑
┌─────────────────┐
│   Solr          │  Solr 8.4
│   Container     │  Search indexing
└─────────────────┘
```

**Challenges**:
- Complex orchestration (4 containers to manage)
- Network overhead between containers
- PostgreSQL container resource intensive
- Difficult debugging across containers
- High memory footprint (~40GB total)

**Location**: `legacy/old_docker_configs/`

### Phase 2: RDS Integration

**Change**: Moved PostgreSQL to AWS RDS

```
┌─────────────────┐
│   Builder       │  Alpine + Java 11 + Gradle
│   Container     │  Builds InterMine
└─────────────────┘
         ↓
┌─────────────────┐         ┌──────────────────┐
│   Tomcat        │────────▶│   AWS RDS        │
│   Container     │  JDBC   │  PostgreSQL 15   │
└─────────────────┘         │  db.t3.large     │
         ↑                  │  500GB gp3       │
┌─────────────────┐         └──────────────────┘
│   Solr          │
│   Container     │
└─────────────────┘
```

**Benefits**:
- Removed PostgreSQL container overhead
- Better database performance (RDS optimized)
- Persistent databases across builds
- Simplified backup/restore (RDS snapshots)
- Better scalability

**Location**: `legacy/multi_mine_rds/` (moved from `docker/multi_mine_rds/`)

**Created**: RDS provisioning tools
- `src/intermine_builder/rds_provisioner.py`
- `src/cli/rds_manager.py`
- InterMine-optimized PostgreSQL settings
- Shared RDS for 4 mines (8 databases)

### Phase 3: Unified Container

**Change**: Consolidated Builder + Tomcat + Solr into single container

```
┌─────────────────────────────────────┐
│   AllianceMine Unified Container    │
│                                     │
│   ┌─────────────────────────────┐  │         ┌──────────────────┐
│   │  Build Environment          │  │         │   AWS RDS        │
│   │  Java 11 + Gradle + Perl    │  │         │  PostgreSQL 15   │
│   └─────────────────────────────┘  │         │                  │
│   ┌─────────────────────────────┐  │  JDBC   │  • 500GB gp3     │
│   │  Apache Tomcat 9.0          │──┼────────▶│  • db.t3.large   │
│   │  Port 8080                  │  │         │  • 8 databases   │
│   └─────────────────────────────┘  │         │  • $160/month    │
│   ┌─────────────────────────────┐  │         └──────────────────┘
│   │  Apache Solr 8.4            │  │
│   │  Port 8983                  │  │
│   └─────────────────────────────┘  │
│                                     │
│   Resources: 32GB RAM, 8 vCPUs     │
│   Image Size: ~1.5GB                │
└─────────────────────────────────────┘
```

**Benefits**:
- ✅ Single container to manage (vs 3-4)
- ✅ Localhost communication (Tomcat ↔ Solr)
- ✅ No network overhead
- ✅ Simpler deployment
- ✅ Easier debugging (one container, one log stream)
- ✅ Reduced total memory (~32GB vs ~40GB)
- ✅ Follows InterMine best practices
- ✅ Faster startup time

**Location**: `docker/alliancemine-unified/`

**Why This Works**:
1. **PostgreSQL was the bottleneck**: With RDS handling database, containers are much lighter
2. **InterMine is monolithic**: Designed to run as single application
3. **Tomcat + Solr communicate frequently**: Localhost is faster than Docker network
4. **Simpler operations**: One container to build, deploy, monitor, debug

### Phase 4: Build-Only Container (Current) ⭐

**Change**: Separated build concerns from runtime. A dedicated build-only container handles
compilation and database population, while Tomcat and Solr run natively on EC2.

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
│  /root/scripts/          (build scripts) │         │  500 GB gp3 storage │
│  /root/data/             (FMS downloads) │         └─────────────────────┘
│                                          │
│  Resources: 32 GB RAM, 8 CPUs           │
│  Image size: ~1.5 GB                    │         ┌─────────────────────┐
│                                          │  WAR    │  EC2 Instance       │
│  No Tomcat. No Solr.                    │ deploy  │  Native Tomcat      │
│  Build-only, exits when done.           │────────>│  Native Solr        │
│                                          │         │  Caddy reverse proxy│
└──────────────────────────────────────────┘         └─────────────────────┘
```

**Benefits over Phase 3**:
- Smaller image (no Tomcat, no Solr, no multi-stage build)
- Build scripts are Python (not bash) — testable, with error handling
- Database naming convention supports RC/test and production builds
- `promote_db.py` renames RC databases to production names
- `deploy_war.py` pushes WAR to remote Tomcat via `cargoRedeployRemote`
- Entrypoint uses `envsubst` for properties (not fragile `sed` substitution)

**Location**: `docker/alliancemine/`

**Build scripts**:
- `scripts/build_full.py` — 7-stage pipeline with `--skip-stages`, `--start-from`
- `scripts/extract_data.py` — Downloads from FMS API with S3 fallback
- `scripts/promote_db.py` — `ALTER DATABASE ... RENAME TO` with dry-run
- `scripts/deploy_war.py` — Updates properties and runs Gradle deploy

**Database naming**:
- Test: `alliancemine_8_3_0_rc1` (per RC number)
- Production: `alliancemine_8_3_0` (promoted from RC)
- Profile: `alliancemine_userprofile` (persistent, shared)

See [ALLIANCEMINE_BUILD_GUIDE.md](ALLIANCEMINE_BUILD_GUIDE.md) for the full operational guide.

## Technical Details

### Build-Only Dockerfile (Phase 4)

Single-stage, no multi-stage needed since there's no runtime image to optimize:

```dockerfile
FROM alpine:3.20
# System: openjdk8, postgresql-client, perl, python3, gettext
# Perl CPAN modules for project_build
# Clone + compile alliancemine and bio-sources
# Install project_build from intermine-scripts
# Copy Python build scripts
# ENTRYPOINT ["/root/entrypoint.sh"]
```

### Unified Dockerfile (Phase 3)

### Multi-Stage Dockerfile

**Stage 1: Builder** (discarded in final image)
```dockerfile
FROM eclipse-temurin:11-jdk-alpine AS builder
# Clone repos
# Compile bio-sources
# Compile InterMine
# Size: ~2GB (not in final image)
```

**Stage 2: Solr Builder** (merged into final)
```dockerfile
FROM eclipse-temurin:11-jre-alpine AS solr-builder
# Download Solr 8.4.1
# Verify SHA512
# Size: ~500MB
```

**Stage 3: Runtime** (final image)
```dockerfile
FROM eclipse-temurin:11-jre-alpine
# Copy Tomcat 9.0
# Copy Solr from stage 2
# Copy compiled InterMine from stage 1
# Configure entrypoint
# Final size: ~1.5GB
```

### Container Modes

**Run Mode** (default):
```bash
docker-compose up -d
# Starts Tomcat + Solr for serving webapp
```

**Build Mode**:
```bash
docker-compose run alliancemine build
# Executes full InterMine build pipeline
```

**Debug Mode**:
```bash
docker-compose run alliancemine bash
# Interactive shell for debugging
```

### Resource Allocation

**Container Resources**:
- Total: 32GB RAM, 8 vCPUs
- Tomcat: 16GB heap (`-Xmx16g`)
- Solr: 4GB heap (`-Xmx4g`)
- Build: 4GB Gradle heap
- OS/Buffer: ~8GB

**RDS Resources**:
- Instance: db.t3.large (2 vCPU, 8GB RAM)
- Storage: 500GB gp3 (3000 IOPS baseline)
- Connections: 250 max (HikariCP pools)

### File Structure

```
docker/alliancemine-unified/
├── Dockerfile                          # Multi-stage build
├── docker-compose.yml                  # Orchestration
├── docker-entrypoint.sh                # Startup logic
├── alliancemine.properties.template    # InterMine config
├── tomcat-users.xml                    # Tomcat auth
├── server.xml                          # Tomcat config
├── .env.example                        # Environment template
├── .dockerignore                       # Build optimization
├── scripts/
│   ├── build_full.sh                   # Full build pipeline
│   └── extract_data.sh                 # Data download
├── README.md                           # Full documentation
└── QUICKSTART.md                       # Getting started
```

## Comparison

| Aspect | Multi-Container | RDS Integration | Unified Container | Build-Only (Current) |
|--------|----------------|-----------------|-------------------|---------------------|
| Containers | 4 | 3 | 1 | 1 (ephemeral) |
| Total Memory | ~40GB | ~36GB | ~32GB | ~32GB |
| PostgreSQL | Container | AWS RDS | AWS RDS | AWS RDS |
| Tomcat/Solr | Containers | Containers | In container | Native on EC2 |
| Build scripts | Bash | Bash | Bash | Python (testable) |
| DB naming | Fixed | Fixed | Fixed | Versioned (RC/prod) |
| DB promotion | Manual | Manual | Manual | `promote_db.py` |
| Deployment | Complex | Medium | Simple | Build exits, WAR deployed separately |
| Debugging | Difficult | Medium | Easy | Easy |
| Image Size | ~3GB total | ~2.5GB | ~1.5GB | ~1.5GB |
| Maintenance | High | Medium | Low | Low |
| Location | `legacy/` | `legacy/` | `docker/alliancemine-unified/` | `docker/alliancemine/` |

## Cost Analysis

### Multi-Container Setup
- EC2 (t3.2xlarge): ~$120/month
- Storage: ~$20/month
- **Total**: ~$140/month

### RDS Integration
- EC2 (t3.xlarge): ~$75/month
- RDS (db.t3.large): ~$105/month
- Storage (500GB): ~$55/month
- **Total**: ~$235/month

### Why More Expensive?

**Trade-offs**:
- ✅ Better database performance (RDS optimized)
- ✅ Automated backups (RDS snapshots)
- ✅ High availability option (Multi-AZ)
- ✅ Easier scaling (RDS can scale independently)
- ✅ Managed service (less ops burden)
- ✅ Persistent data (survives container restarts)

**Cost Optimization**:
- Stop RDS when not building: saves ~$105/month
- Use Reserved Instances: save 30-60%
- Use Spot for EC2: save 70%

## Migration Path

### From Multi-Container to Unified

**Step 1**: Backup existing data
```bash
# Export PostgreSQL data
docker exec postgres pg_dumpall > backup.sql
```

**Step 2**: Provision RDS
```bash
uv run python -m src.cli.rds_manager create
```

**Step 3**: Restore data to RDS (if migrating)
```bash
psql -h $RDS_HOST -U postgres < backup.sql
```

**Step 4**: Build unified image
```bash
cd docker/alliancemine-unified
cp .env.example .env
# Edit .env with RDS credentials
docker-compose build
```

**Step 5**: Test
```bash
docker-compose up -d
docker-compose logs -f
```

**Step 6**: Run build
```bash
docker-compose run alliancemine build
```

## Best Practices

### Development

- Use unified container for simplicity
- Mount local code for hot-reload testing
- Use bash mode for debugging
- Keep RDS running during active development

### Production

- Use unified container
- Enable RDS Multi-AZ for high availability
- Set up CloudWatch monitoring
- Configure auto-restart policies
- Use AWS ECS/Fargate for container hosting

### CI/CD

- Build image in pipeline
- Push to ECR registry
- Deploy to ECS with blue/green
- Run smoke tests
- Rollback on failure

## Future Enhancements

### Potential Improvements

1. **BlueGenes Integration**:
   - Add BlueGenes (modern UI) to unified container
   - Or run separately if preferred

2. **Kubernetes Support**:
   - Create Helm charts
   - StatefulSet for InterMine
   - Persistent volumes for Solr

3. **Multi-Mine Support**:
   - One unified image for all MODs
   - Environment-based mine selection
   - Shared RDS (already done)

4. **Monitoring**:
   - Prometheus metrics
   - Grafana dashboards
   - Log aggregation (ELK/CloudWatch)

5. **Performance**:
   - Redis caching layer
   - CDN for static assets
   - Read replicas for RDS

## Conclusion

The build-only container (`docker/alliancemine/`) is the recommended approach for AllianceMine builds going forward. It separates build concerns from runtime, uses testable Python scripts, and supports a versioned release workflow with RC and production database naming.

The unified container (`docker/alliancemine-unified/`) remains available for self-contained deployments where Tomcat and Solr run inside the container.

## Related Documentation

- [AllianceMine Build Guide](ALLIANCEMINE_BUILD_GUIDE.md) — Full operational guide for the build-only container
- [Build System](BUILD_SYSTEM.md) — Python orchestration layer architecture
- [Quick Start](QUICKSTART.md) — Getting started with either approach
- [RDS Setup Guide](RDS_SETUP.md)
- [RDS Integration Notes](RDS_INTEGRATION_NOTES.md)

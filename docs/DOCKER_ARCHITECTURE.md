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

### Phase 2: RDS Integration (Current - Step 1)

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

**Location**: `docker/multi_mine_rds/`

**Created**: RDS provisioning tools
- `src/intermine_builder/rds_provisioner.py`
- `src/cli/rds_manager.py`
- InterMine-optimized PostgreSQL settings
- Shared RDS for 4 mines (8 databases)

### Phase 3: Unified Container (Current - Step 2) ⭐

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

## Technical Details

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

| Aspect | Multi-Container | RDS Integration | Unified Container |
|--------|----------------|-----------------|-------------------|
| Containers | 4 | 3 | 1 |
| Total Memory | ~40GB | ~36GB | ~32GB |
| PostgreSQL | Container | AWS RDS | AWS RDS |
| Tomcat ↔ Solr | Network | Network | Localhost |
| Deployment | Complex | Medium | Simple |
| Debugging | Difficult | Medium | Easy |
| Startup Time | ~5 min | ~3 min | ~1 min |
| Image Size | ~3GB total | ~2.5GB | ~1.5GB |
| Maintenance | High | Medium | Low |

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

The unified container architecture provides the best balance of:
- **Simplicity**: One container to manage
- **Performance**: Localhost communication, RDS optimization
- **Cost**: Reasonable given managed services
- **Maintainability**: Follows InterMine standards
- **Scalability**: RDS can scale independently

This is the **recommended approach** for AllianceMine deployment going forward.

## Related Documentation

- [Unified Container README](docker/alliancemine-unified/README.md)
- [Quick Start Guide](docker/alliancemine-unified/QUICKSTART.md)
- [RDS Setup Guide](RDS_SETUP.md)
- [RDS Integration Notes](RDS_INTEGRATION_NOTES.md)

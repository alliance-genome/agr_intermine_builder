# InterMine AWS Architecture

## Overview

This architecture uses:
1. **Multi-Tenant Production EC2** - Hosts all mine webapps (24/7) with native Solr and Docker Tomcat containers
2. **Build EC2 (AllianceMineDev)** - Persistent instance running Docker build containers
3. **Persistent RDS** - Single PostgreSQL instance with all mine databases
4. **Application Load Balancer (ALB)** - Routes traffic with TLS termination
5. **BlueGenes UI** - Modern web interface for all mines
6. **Integrated CDN** - Caddy serves static assets

## Architecture Diagram

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                         PUBLIC INTERNET                                     │
└──────────────────────────────────┬──────────────────────────────────────────┘
                                   │
                                   ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                    Route 53 DNS                                             │
│  wormmine.alliancegenome.org ─────────────────────────────────────────────┐ │
│  alliancemine-proxy.alliancegenome.org ───────────────────────────────────┤ │
│  bluegenes-proxy.alliancegenome.org ──────────────────────────────────────┤ │
│                                                                       CNAME │
└──────────────────────────────────┬──────────────────────────────────────────┘
                                   │
                                   ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                 Application Load Balancer (alliancemine-lb)                 │
│                                                                             │
│  HTTPS :443 (TLS Termination with ACM Certificate)                          │
│                                                                             │
│  Listener Rules:                                                            │
│  ├── Rule 100: Host = "alliancemine-cdn-proxy.*" → alliancemine-cdn :8888   │
│  ├── Rule 200: Host = "alliancemine-proxy.*" → alliancemine :8080           │
│  ├── Rule 300: Host = "bluegenes-proxy.*" → bluegenes :5000                 │
│  ├── Rule 390: Host = "wormmine.*" AND Path = "/cdn/*" → wormmine-cdn :8888 │
│  ├── Rule 400: Host = "wormmine.*" → wormmine :8081                         │
│  └── Default: Return 404                                                    │
└──────────────────────────────────┬──────────────────────────────────────────┘
                                   │
        ┌──────────────────────────┼──────────────────────────┐
        │                          │                          │
        ▼                          ▼                          ▼
┌───────────────────┐  ┌───────────────────┐  ┌───────────────────────────────┐
│  AllianceMine EC2 │  │  Build EC2        │  │  Multi-Tenant EC2             │
│  (Production)     │  │  (AllianceMineDev)│  │  (WormMine + Future Mines)    │
│                   │  │                   │  │                               │
│  • Tomcat :8080   │  │  • 172.31.60.197  │  │  • c7i.4xlarge                │
│  • Solr :8983     │  │  • Docker builds  │  │  • 16 vCPU, 32GB RAM          │
│  • BlueGenes :5000│  │  • Persistent     │  │  • Native Solr :8983          │
│  • CDN :8888      │  │  • Unified images │  │  • Docker Tomcat containers   │
│                   │  │                   │  │  • Caddy CDN :8888            │
└─────────┬─────────┘  └─────────┬─────────┘  │  • BlueGenes :5000            │
          │                      │            └───────────────┬───────────────┘
          │                      │                            │
          └──────────────────────┼────────────────────────────┘
                                 │
                                 ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                         AWS RDS PostgreSQL 15                               │
│                                                                             │
│  Instance: db.r6g.xlarge (4 vCPU, 32GB RAM)                                 │
│  Storage: 500GB gp3                                                         │
│                                                                             │
│  Databases (versioned naming convention):                                   │
│  ├── alliancemine_8_3_0, alliancemine_profiles_8_3_0                        │
│  ├── alliancemine_8_3_0-1, alliancemine_profiles_8_3_0-1 (iteration)        │
│  ├── wormmine_final, wormmine_userprofile, wormmine_items                   │
│  ├── flymine_db, flymine_profiles_db                                        │
│  ├── mousemine_db, mousemine_profiles_db                                    │
│  └── ... (other mines)                                                      │
└─────────────────────────────────────────────────────────────────────────────┘
```

---

## Current Implementation Status

### Python Build System

The codebase includes a modern Python-based orchestration system that replaces legacy bash scripts:

```
src/
├── intermine_builder/
│   ├── mine_config.py      # Mine configurations (AllianceMine, WormMine, etc.)
│   ├── docker_manager.py   # Docker container lifecycle
│   ├── build_executor.py   # Build stage execution
│   ├── mine_builder.py     # Main orchestrator
│   ├── config.py           # Configuration management
│   └── aws/
│       └── rds_manager.py  # AWS RDS provisioning
└── cli/
    ├── build_mines.py      # Main CLI interface
    ├── rds_manager.py      # RDS CLI
    └── set_release.py      # Release version CLI
```

**CLI Commands:**
```bash
# Build a mine
python -m src.cli.build_mines build --mine alliancemine

# Build all mines
python -m src.cli.build_mines build-all

# Execute single stage
python -m src.cli.build_mines stage --mine alliancemine --stage buildDB

# Set Alliance release version
uv run python -m src.cli.set_release current    # From Alliance API
uv run python -m src.cli.set_release 8.3.0      # Specific version
```

### Unified Container Architecture

Each mine uses a unified container with:
- Build environment (Java 11, Gradle, Perl)
- Apache Tomcat 9.0
- Apache Solr 8.4 (embedded or external)
- Connects to AWS RDS PostgreSQL

Located in:
- `docker/alliancemine-unified/`
- `docker/wormmine-unified/`

---

## Components

### 1. Multi-Tenant Production EC2

**Purpose**: Host multiple InterMine webapps with shared infrastructure

**Specifications**:
- Instance Type: `c7i.4xlarge` (16 vCPU, 32 GB RAM)
- OS: Amazon Linux 2023
- Storage: 50 GB root + 30 GB data volume (gp3)
- Instance ID: i-0e7fbfd5a4440063e
- Private IP: 172.31.59.87
- Public IP: 44.206.248.213

**Memory Allocation**:
- 6-10 Tomcat containers × 2-2.5GB = 12-25GB
- Solr: 2-3GB
- BlueGenes: 1GB
- Caddy CDN: ~256MB
- System: 3-4GB

**Services**:
```
/opt/solr/              # Native Solr 8.11.2 (:8983)
├── wormmine-search         # 6,367,684 documents
├── wormmine-autocomplete   # 61,344 documents
├── alliancemine-search
├── alliancemine-autocomplete
└── [future-mine cores...]

Docker Containers:
├── wormmine        (:8081)
├── alliancemine    (:8080)
├── bluegenes       (:5000)
└── [future-mine containers...]

Caddy CDN           (:8888)
└── /data/cdn/      # Static assets
```

**Management Scripts**:
```bash
# Add a new mine (creates Solr cores + Tomcat container)
sudo add-mine <mine_name> <port> [domain]

# Remove a mine
sudo remove-mine <mine_name>

# List running mines
list-mines
```

**Cost**: ~$496/month (on-demand), ~$298/month (1-year savings plan)

---

### 2. Build EC2 (AllianceMineDev)

**Purpose**: Persistent instance for running InterMine builds using Docker containers

**Specifications**:
- Name: AllianceMineDev
- Private IP: 172.31.60.197
- OS: Amazon Linux 2023
- Storage: 500 GB gp3
- Lifecycle: Persistent (always running for development builds)

**Build Environment**:
```
/home/ec2-user/
├── agr_intermine_builder/           # Main build repository
│   ├── docker/
│   │   ├── alliancemine-unified/    # AllianceMine build container
│   │   └── wormmine-unified/        # WormMine build container
│   └── src/                         # Python orchestration
│
└── Docker containers (unified images):
    ├── alliancemine-unified         # Build + Tomcat + Solr
    └── wormmine-unified             # Build + Tomcat + Solr
```

**Unified Container Architecture**:

Each unified container includes:
- Java 11 (Amazon Corretto)
- Gradle 7.x for InterMine builds
- Apache Tomcat 9.0 for webapp deployment
- Apache Solr 8.4 (embedded)
- PostgreSQL client (connects to RDS)

**Build Process**:
```bash
# SSH to build instance
ssh ec2-user@172.31.60.197

# Navigate to mine directory
cd agr_intermine_builder/docker/alliancemine-unified

# Set database version (creates versioned database on RDS)
python3 set_db_version.py -1     # e.g., alliancemine_8_3_0-1

# Run build
docker-compose up -d
docker exec -it alliancemine bash
./gradlew buildDB                # Build database
./gradlew cargoDeployRemote      # Deploy to production
```

**Build Stages**:
1. `fetchData` - Download data sources
2. `buildDB` - Load data into PostgreSQL
3. `postProcess` - Run post-processors
4. `cargoDeployRemote` - Deploy WAR to production Tomcat

---

### 3. Persistent RDS PostgreSQL

**Purpose**: Single database instance hosting all mine databases

**Specifications**:
- Instance: `db.r6g.xlarge` (4 vCPU, 32 GB RAM)
- Storage: 500 GB gp3 (scalable)
- Endpoint: `intermine-postgres.cmnnhlso7wdi.us-east-1.rds.amazonaws.com`
- Multi-AZ: No (cost optimization)
- Backups: Automated daily snapshots

**Database Naming Convention**:

Databases follow a versioned naming scheme:
```
<mine>_<release><suffix>
<mine>_profiles_<release><suffix>
```

Where:
- `<release>` is the version with dots converted to underscores (e.g., `8_3_0`)
- `<suffix>` is optional (e.g., `-1`, `-test`, `-patch1`)

**Examples**:
| Configuration | Main Database | Profile Database |
|--------------|---------------|------------------|
| Release 8.3.0 (base) | `alliancemine_8_3_0` | `alliancemine_profiles_8_3_0` |
| Release 8.3.0, iteration 1 | `alliancemine_8_3_0-1` | `alliancemine_profiles_8_3_0-1` |
| Release 8.3.0, test | `alliancemine_8_3_0-test` | `alliancemine_profiles_8_3_0-test` |
| WormMine (legacy) | `wormmine_final` | `wormmine_userprofile` |

**Version Control Scripts**:
```bash
# In docker/alliancemine-unified/
python3 set_db_version.py        # Base version
python3 set_db_version.py -1     # First iteration
python3 set_db_version.py -test  # Test build

# Automated build with versioning
python3 build_mine.py -1         # Sets version, restarts, runs buildDB
```

**Cost**: ~$260/month (on-demand), ~$180/month (reserved)

---

### 4. Application Load Balancer (ALB)

**Purpose**: Route traffic to appropriate services with TLS termination

**Configuration**:
- Name: `alliancemine-lb`
- DNS: `alliancemine-lb-309443304.us-east-1.elb.amazonaws.com`
- Certificate: ACM certificate for `*.alliancegenome.org`

**Listener Rules** (HTTPS :443):

| Priority | Condition | Target Group | Port |
|----------|-----------|--------------|------|
| 100 | Host = `alliancemine-cdn-proxy.alliancegenome.org` | alliancemine-cdn | 8888 |
| 200 | Host = `alliancemine-proxy.alliancegenome.org` | alliancemine | 8080 |
| 300 | Host = `bluegenes-proxy.alliancegenome.org` | bluegenes | 5000 |
| 390 | Host = `wormmine.alliancegenome.org` AND Path = `/cdn/*` | wormmine-cdn | 8888 |
| 400 | Host = `wormmine.alliancegenome.org` | wormmine | 8081 |
| Default | - | Return 404 | - |

**Target Groups**:
```
wormmine        → 172.31.59.87:8081 (Health: /wormmine/service/version)
wormmine-cdn    → 172.31.59.87:8888 (Health: /)
alliancemine    → AllianceMine EC2:8080
bluegenes       → BlueGenes EC2:5000
```

---

### 5. Route 53 DNS

**CNAME Records**:
```
wormmine.alliancegenome.org → alliancemine-lb-309443304.us-east-1.elb.amazonaws.com
alliancemine-proxy.alliancegenome.org → alliancemine-lb-309443304.us-east-1.elb.amazonaws.com
bluegenes-proxy.alliancegenome.org → alliancemine-lb-309443304.us-east-1.elb.amazonaws.com
```

---

### 6. BlueGenes Integration

**Purpose**: Modern web interface for all InterMine instances

**Deployment Options**:

1. **Multi-Tenant Instance** (WormMine):
   - Container: `bluegenes`
   - Port: 5000
   - Image: `100225593120.dkr.ecr.us-east-1.amazonaws.com/agr_bluegenes:wormmine`
   - Access: `http://44.206.248.213:5000/bluegenes/wormmine`

2. **AllianceMine Production**:
   - Image tag: `:latest`
   - Access: `https://www.alliancegenome.org/bluegenes`

**Configuration** (`config/defaults/config.edn`):
```clojure
{:mines
 {:wormmine
  {:name "WormMine"
   :service {:root "https://wormmine.alliancegenome.org/wormmine"}}

  :alliancemine
  {:name "AllianceMine"
   :service {:root "https://www.alliancegenome.org/alliancemine"}}}

 :default-mine :alliancemine
 :bluegenes-deploy-path "/"
 :server-port 5000}
```

**Build and Deploy**:
```bash
# Build JAR
cd /path/to/agr_bluegenes
lein uberjar

# Build and push Docker image
docker build -t agr_bluegenes:wormmine .
docker tag agr_bluegenes:wormmine 100225593120.dkr.ecr.us-east-1.amazonaws.com/agr_bluegenes:wormmine
docker push 100225593120.dkr.ecr.us-east-1.amazonaws.com/agr_bluegenes:wormmine

# Deploy on Multi-Tenant
ssh ec2-user@172.31.59.87
sudo docker pull 100225593120.dkr.ecr.us-east-1.amazonaws.com/agr_bluegenes:wormmine
sudo docker stop bluegenes && sudo docker rm bluegenes
sudo docker run -d --name bluegenes -p 5000:5000 \
  100225593120.dkr.ecr.us-east-1.amazonaws.com/agr_bluegenes:wormmine
```

---

### 7. CDN (Content Delivery Network)

**Purpose**: Serve static JavaScript/CSS assets for InterMine webapps

**Implementation**: Caddy server on port 8888

**Directory Structure**:
```
/data/cdn/
├── js/              # JavaScript libraries (jQuery, D3, etc.)
├── css/             # Stylesheets
├── fonts/           # Web fonts
├── images/          # Shared images
├── bluegenes/       # BlueGenes static assets
├── img/
│   └── wormbase/    # WormBase footer images (local due to Cloudflare)
└── mines/           # Mine-specific assets
    ├── alliancemine/
    ├── wormmine/
    └── ...
```

**Caddy Configuration** (`/etc/caddy/Caddyfile`):
```
:8888 {
    # Strip /cdn prefix for ALB routing
    handle_path /cdn/* {
        root * /data/cdn
        file_server
        header Access-Control-Allow-Origin *
    }

    # Also serve from root for backward compatibility
    handle {
        root * /data/cdn
        file_server
        header Access-Control-Allow-Origin *
    }
}
```

**CDN Management Script**:
```bash
./scripts/manage_cdn.sh structure          # Create directory structure
./scripts/manage_cdn.sh upload <local> <cdn>  # Upload files
./scripts/manage_cdn.sh sync <dir> <cdn>   # Sync directory
./scripts/manage_cdn.sh status             # Show statistics
./scripts/manage_cdn.sh list               # List contents
```

**CDN URLs**:
- `https://wormmine.alliancegenome.org/cdn/js/jquery/2.0.3/jquery.min.js`
- `https://wormmine.alliancegenome.org/cdn/img/wormbase/logo.png`

---

### 8. ECR (Elastic Container Registry)

**Purpose**: Store Docker images for all mines

**Repository**: `100225593120.dkr.ecr.us-east-1.amazonaws.com`

**Images**:
| Image | Tag | Description |
|-------|-----|-------------|
| `agr_alliancemine` | `latest`, `8.3.0` | AllianceMine unified container |
| `agr_wormmine` | `latest`, `WS298` | WormMine unified container |
| `agr_flymine` | `latest` | FlyMine container |
| `agr_mousemine` | `latest` | MouseMine container |
| `agr_bluegenes` | `latest`, `wormmine` | BlueGenes UI |

**Push Workflow**:
```bash
# Login to ECR
aws ecr get-login-password --region us-east-1 | \
  docker login --username AWS --password-stdin \
  100225593120.dkr.ecr.us-east-1.amazonaws.com

# Build and push
cd docker/alliancemine-unified
docker-compose build
docker tag alliancemine-unified:latest \
  100225593120.dkr.ecr.us-east-1.amazonaws.com/agr_alliancemine:latest
docker push 100225593120.dkr.ecr.us-east-1.amazonaws.com/agr_alliancemine:latest
```

---

## Build Orchestration

**Current Approach**: Manual builds via Docker containers on AllianceMineDev

### Python CLI Build System

```bash
# Build a specific mine
python -m src.cli.build_mines build --mine alliancemine

# Build all mines
python -m src.cli.build_mines build-all

# Execute single stage
python -m src.cli.build_mines stage --mine alliancemine --stage buildDB

# Set release version
uv run python -m src.cli.set_release 8.3.0
```

### Docker Container Build Workflow

```bash
# 1. SSH to build instance
ssh ec2-user@172.31.60.197

# 2. Navigate to mine directory
cd agr_intermine_builder/docker/alliancemine-unified

# 3. Set database version (optional suffix for iterations)
python3 set_db_version.py -1     # Creates alliancemine_8_3_0-1

# 4. Start container
docker-compose up -d

# 5. Enter container and build
docker exec -it alliancemine bash
./gradlew buildDB                # Full database build
./gradlew cargoDeployRemote      # Deploy WAR to production

# 6. Monitor build
tail -f logs/build.log
```

### Build Monitoring

```bash
# Check container status
docker ps

# View build logs
docker logs alliancemine --tail 100

# Check Gradle build progress
docker exec alliancemine cat intermine_log.log
```

---

## Cost Analysis

### Monthly Costs (2024 Pricing)

| Component | Type | Cost | Notes |
|-----------|------|------|-------|
| **Multi-Tenant EC2** | c7i.4xlarge (24/7) | $496 | On-demand |
| **Multi-Tenant EC2** | c7i.4xlarge (reserved) | $298 | 1-year savings plan |
| **AllianceMine EC2** | m6i.2xlarge (24/7) | $280 | Production mines |
| **Build EC2** | AllianceMineDev (24/7) | $150 | Persistent build instance |
| **RDS Database** | db.r6g.xlarge (24/7) | $260 | Multi-tenant |
| **RDS Storage** | 500GB gp3 | $55 | All mine data |
| **Data Transfer** | S3, API calls | $20 | Data downloads |
| **ALB** | Application Load Balancer | $25 | Request-based |
| **EBS Volumes** | gp3 storage | $20 | EC2 attached |
| **ECR** | Container registry | $10 | Image storage |
| **Total (on-demand)** | | **~$1,316/month** | |
| **Total (optimized)** | | **~$1,000/month** | With reserved instances |

### Cost Optimization Strategies

1. **Reserved Instances**: 1-year commitment saves 30-40%
2. **Savings Plans**: EC2 compute savings plan for flexible pricing
3. **Stop Build EC2 when idle**: Stop AllianceMineDev when not building
4. **ECR Lifecycle policies**: Auto-delete old images after 30 days
5. **RDS Right-sizing**: Monitor database usage and adjust instance size

---

## Implementation Plan

### Phase 1: Infrastructure Setup (Completed)
- [x] Create Multi-Tenant EC2 with native Solr
- [x] Configure RDS with versioned database naming
- [x] Set up ALB with listener rules
- [x] Configure Route 53 DNS records
- [x] Deploy Caddy CDN
- [x] Push images to ECR
- [x] Set up Build EC2 (AllianceMineDev) with Docker containers

### Phase 2: Build Process (Completed)
- [x] Create unified Docker containers for each mine
- [x] Implement Python CLI build system
- [x] Set up database versioning workflow
- [x] Configure cargoDeployRemote for production deployments

### Phase 3: Automation (In Progress)
- [ ] GitHub Actions CI/CD pipeline
- [ ] Automated testing before deployment
- [ ] Blue/green deployment strategy
- [ ] CloudWatch dashboards and alarms

### Phase 4: Multi-Mine Scaling
- [ ] Add remaining MOD mines to multi-tenant
- [ ] Configure per-mine Solr cores
- [ ] Set up mine-specific ALB rules
- [ ] Document runbook for adding new mines

---

## Troubleshooting

### Tomcat Container Issues

```bash
# Check container logs
docker logs wormmine --tail 100

# Check Tomcat catalina.out
docker exec wormmine tail -f /usr/local/tomcat/logs/catalina.out

# Restart container
docker restart wormmine
```

### HTTPS/Mixed Content Issues

When behind ALB, Tomcat needs `RemoteIpValve` to recognize HTTPS:

```xml
<!-- In server.xml, before <Host> element -->
<Valve className="org.apache.catalina.valves.RemoteIpValve"
       remoteIpHeader="X-Forwarded-For"
       protocolHeader="X-Forwarded-Proto" />
```

### Solr Connection Issues

```bash
# Check Solr status
curl http://localhost:8983/solr/admin/cores?action=STATUS

# Check specific core
curl http://localhost:8983/solr/wormmine-search/admin/ping

# Restart Solr
sudo systemctl restart solr
```

### Database Connection Issues

```bash
# Test RDS connectivity
pg_isready -h intermine-postgres.cmnnhlso7wdi.us-east-1.rds.amazonaws.com -U postgres

# Check active connections
psql -h $RDS_HOST -U postgres -c "SELECT count(*), state FROM pg_stat_activity GROUP BY state;"
```

---

## Security Checklist

- [x] SSL certificates via ACM for ALB
- [x] Security group restricts RDS access to EC2 only
- [x] Solr admin restricted to internal network
- [x] IAM roles follow least privilege
- [x] RDS automated backups enabled
- [ ] AWS Secrets Manager for database passwords
- [ ] VPC Flow Logs enabled
- [ ] CloudTrail for audit logging

---

## Related Documentation

- [Multi-Tenant Deployment Guide](../MULTITENANT_DEPLOYMENT.md)
- [WormMine Multi-Tenant Setup](../WORMMINE_MULTITENANT_SETUP.md)
- [Database Versioning](../../docker/alliancemine-unified/DATABASE_VERSIONING.md)
- [Deployment Strategy](../DEPLOYMENT_STRATEGY.md)
- [Docker Architecture](../DOCKER_ARCHITECTURE.md)

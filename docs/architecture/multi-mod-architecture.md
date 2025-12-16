# Multi-MOD InterMine Architecture

## Vision Overview

Based on your architecture diagram, we have:

```
┌─────────────────────────────────────────────────────────────────────┐
│                     PRODUCTION ENVIRONMENT                           │
├─────────────────────────────────────────────────────────────────────┤
│                                                                     │
│  ┌────────────────────────────────────────────────────────────┐     │
│  │  Production EC2 (Multi-Instance Tomcat + Solr)             │     │
│  │  ┌──────────┐ ┌──────────┐ ┌──────────┐                    │     │
│  │  │Alliance  │ │  Worm    │ │  (future)│  ... + more        │     │
│  │  │:8080     │ │  :8081   │ │  :8082+  │                    │     │
│  │  └──────────┘ └──────────┘ └──────────┘                    │     │
│  │                                                            │     │
│  │  ┌──────────────┐                                          │     │
│  │  │ Solr Cluster │  (Shared search index)                   │     │
│  │  └──────────────┘                                          │     │
│  └────────────────────────────────────────────────────────────┘     │
│                              ↓                                      │
│  ┌────────────────────────────────────────────────────────────┐     │
│  │  RDS PostgreSQL (Multi-tenant)                             │     │
│  │  ┌─────────────┐ ┌─────────────┐ ┌─────────────┐           │     │
│  │  │alliancemine │ │  wormmine   │ │  (future)   │ + more    │     │
│  │  │_db          │ │  _db        │ │  _db        │           │     │
│  │  └─────────────┘ └─────────────┘ └─────────────┘           │     │
│  └────────────────────────────────────────────────────────────┘     │
│                              ↑                                      │
│                    Reads from (shared)                              │
│                                                                     │
└─────────────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────────────┐
│                      BUILD ENVIRONMENT                              │
├─────────────────────────────────────────────────────────────────────┤
│                                                                     │
│  ┌────────────────────────────────────────────────────────────┐     │
│  │  Build EC2 (AllianceMineDev) - 172.31.60.197               │     │
│  │  ┌──────────────────────────────────────────────────┐      │     │
│  │  │ Docker Containers (Unified Images)               │      │     │
│  │  │  - alliancemine-unified (Build + Tomcat + Solr)  │      │     │
│  │  │  - wormmine-unified (Build + Tomcat + Solr)      │      │     │
│  │  │  - Persistent instance, manual builds            │      │     │
│  │  └──────────────────────────────────────────────────┘      │     │
│  └────────────────────────────────────────────────────────────┘     │
│                              ↓                                      │
│                    Writes to (during build)                         │
│                              ↓                                      │
│  [Same RDS PostgreSQL - builds directly into production DB]         │
│                                                                     │
└─────────────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────────────┐
│                         BLUEGENES UI                                │
│  User-facing interface connected to all mines via API               │
└─────────────────────────────────────────────────────────────────────┘
```

---

## Architecture Components

### 1. Production EC2: Multi-Instance Tomcat Server

**Instance Type:** `m6i.2xlarge` (8 vCPU, 32GB RAM)
**Cost:** ~$280/month (24/7 operation)

#### Tomcat Configuration

**Multi-instance setup** - One Tomcat instance per mine:

```
/opt/tomcat/
├── shared/               # Shared libraries
│   └── lib/
├── alliancemine/         # Instance 1
│   ├── bin/
│   ├── conf/
│   │   └── server.xml   # Port 8080
│   ├── webapps/
│   │   └── alliancemine.war
│   └── logs/
├── wormmine/             # Instance 2
│   ├── conf/
│   │   └── server.xml   # Port 8081
│   └── webapps/
│       └── wormmine.war
├── flymine/              # Instance 3 (future)
│   └── ...              # Port 8082
├── mousemine/            # Port 8083
├── ratmine/              # Port 8084
├── yeastmine/            # Port 8085
└── zebrafishmine/        # Port 8086
```

**Systemd Services:**

```bash
# /etc/systemd/system/tomcat@.service
[Unit]
Description=Tomcat %i instance
After=network.target

[Service]
Type=forking
User=tomcat
Group=tomcat

Environment="CATALINA_HOME=/opt/tomcat/shared"
Environment="CATALINA_BASE=/opt/tomcat/%i"
Environment="JAVA_OPTS=-Xmx3g -Xms2g"

ExecStart=/opt/tomcat/shared/bin/startup.sh
ExecStop=/opt/tomcat/shared/bin/shutdown.sh

[Install]
WantedBy=multi-user.target
```

**Start all mines:**
```bash
systemctl start tomcat@alliancemine
systemctl start tomcat@wormmine
systemctl start tomcat@flymine
systemctl start tomcat@mousemine
systemctl start tomcat@ratmine
systemctl start tomcat@yeastmine
systemctl start tomcat@zebrafishmine
```

#### Nginx Reverse Proxy

**Front-end routing:**

```nginx
# /etc/nginx/conf.d/intermine.conf

upstream alliancemine {
    server 127.0.0.1:8080;
}

upstream wormmine {
    server 127.0.0.1:8081;
}

upstream flymine {
    server 127.0.0.1:8082;  # Future
}

# ... etc for all mines

server {
    listen 80;
    server_name intermine.alliancegenome.org;

    # AllianceMine
    location /alliancemine/ {
        proxy_pass http://alliancemine/alliancemine/;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
    }

    # WormMine
    location /wormmine/ {
        proxy_pass http://wormmine/wormmine/;
        proxy_set_header Host $host;
    }

    # ... etc
}
```

**Public URLs:**
- `https://intermine.alliancegenome.org/alliancemine/`
- `https://intermine.alliancegenome.org/wormmine/`
- `https://intermine.alliancegenome.org/flymine/` (future)
- etc.

#### Solr Configuration

**Single Solr instance with multiple cores:**

```
/opt/solr/
└── server/
    └── solr/
        ├── alliancemine/
        │   ├── conf/
        │   └── data/
        ├── wormmine/
        ├── flymine/           # Future
        ├── mousemine/         # Future
        ├── ratmine/           # Future
        ├── yeastmine/         # Future
        └── zebrafishmine/     # Future
```

**Solr endpoints:**
- `http://localhost:8983/solr/alliancemine`
- `http://localhost:8983/solr/wormmine`
- etc.

---

### 2. RDS PostgreSQL: Multi-Tenant Database

**Instance Type:** `db.r6g.2xlarge` (8 vCPU, 64GB RAM)
**Storage:** 2TB gp3 (scalable)
**Cost:** ~$520/month

#### Database Layout

**One RDS instance hosts all mine databases:**

```sql
-- List all databases
\l

Name                         | Size
-----------------------------|-------
alliancemine_db              | 150 GB
alliancemine_profiles_db     | 500 MB
wormmine_db                  | 60 GB
wormmine_profiles_db         | 150 MB
flymine_db                   | 80 GB    -- Future
flymine_profiles_db          | 200 MB   -- Future
mousemine_db                 | 120 GB   -- Future
mousemine_profiles_db        | 300 MB   -- Future
ratmine_db                   | 50 GB    -- Future
ratmine_profiles_db          | 100 MB   -- Future
yeastmine_db                 | 30 GB    -- Future
yeastmine_profiles_db        | 100 MB   -- Future
zebrafishmine_db             | 40 GB    -- Future
zebrafishmine_profiles_db    | 100 MB   -- Future
```

**Current Storage:** ~210 GB (AllianceMine + WormMine)

#### Connection Management

**HikariCP connection pools per mine:**

```properties
# Each mine gets dedicated pool
alliancemine.pool.size=20
wormmine.pool.size=15
# Future mines:
# flymine.pool.size=15
# mousemine.pool.size=15
# ratmine.pool.size=10
# yeastmine.pool.size=10
# zebrafishmine.pool.size=10

# Current total: 35 connections (well below max_connections=200)
```

#### Database Isolation

**Each mine has:**
- Separate database (logical isolation)
- Separate user profiles database
- Independent schema
- No cross-mine queries

**Security:**
- Each mine could have separate DB user (optional)
- Row-level security if needed
- Audit logging per database

---

### 3. Build EC2 (AllianceMineDev)

**Instance:** AllianceMineDev (172.31.60.197)
**Lifecycle:** Persistent (always available for builds)
**Architecture:** Docker unified containers

#### Build Environment

```
/home/ec2-user/agr_intermine_builder/
├── docker/
│   ├── alliancemine-unified/     # AllianceMine build container
│   │   ├── Dockerfile
│   │   ├── docker-compose.yml
│   │   ├── alliancemine.properties.template
│   │   ├── set_db_version.py     # Database versioning
│   │   └── build_mine.py         # Automated build script
│   └── wormmine-unified/         # WormMine build container
│       └── ...
└── src/                          # Python CLI orchestration
    └── cli/
        ├── build_mines.py
        └── set_release.py
```

#### Unified Container Architecture

Each mine uses a unified Docker container that includes:
- **Java 11** (Amazon Corretto) for InterMine
- **Gradle 7.x** for build system
- **Apache Tomcat 9.0** for webapp testing
- **Apache Solr 8.4** (embedded) for search
- **PostgreSQL client** connecting to RDS

#### Build Process Per Mine

```bash
# 1. SSH to build instance
ssh ec2-user@172.31.60.197

# 2. Navigate to mine directory
cd agr_intermine_builder/docker/alliancemine-unified

# 3. Set database version (creates versioned DB on RDS)
python3 set_db_version.py -1     # e.g., alliancemine_8_3_0-1

# 4. Start container and build
docker-compose up -d
docker exec -it alliancemine bash
./gradlew buildDB                # Build database (~4-7 hours)
./gradlew postProcess            # Run post-processors
./gradlew cargoDeployRemote      # Deploy to production Tomcat

# 5. Verify deployment
curl https://alliancemine.alliancegenome.org/alliancemine/service/version
```

---

### 4. Build Orchestration

#### Current Implementation: Docker Container Builds

**Manual builds via unified Docker containers on AllianceMineDev:**

```bash
# Python CLI for orchestration
python -m src.cli.build_mines build --mine alliancemine
python -m src.cli.build_mines build-all
python -m src.cli.build_mines stage --mine alliancemine --stage buildDB

# Or direct Docker container builds
cd docker/alliancemine-unified
docker-compose up -d
docker exec -it alliancemine ./gradlew buildDB
```

#### Build Strategies

**Sequential Builds (Current):**
- Build one mine at a time
- Simple, reliable, easy to monitor
- ~4-7 hours per mine

**Incremental Builds:**
- Only rebuild changed mines based on data releases
- Alliance releases monthly → Rebuild AllianceMine
- WormBase updates periodically → Rebuild WormMine
- Most mines: Rebuild on-demand

#### Database Versioning Workflow

```bash
# Set database version before build
python3 set_db_version.py         # Base version: alliancemine_8_3_0
python3 set_db_version.py -1      # Iteration: alliancemine_8_3_0-1
python3 set_db_version.py -test   # Test build: alliancemine_8_3_0-test

# Automated build with versioning
python3 build_mine.py -1          # Sets version, restarts, runs buildDB
```

**Typical Build Schedule:**
- AllianceMine: Monthly (with AGR releases)
- WormMine: As needed (WormBase updates)
- Other mines: On-demand

---

## Mine-Specific Configurations

### Configuration Structure

```python
# src/lib/config.py

@dataclass
class MineConfig:
    """Configuration for a specific mine."""
    mine_name: str
    organism: str
    description: str

    # Repositories
    mine_repo_url: str
    mine_branch: str = "master"
    biosources_repo_url: Optional[str] = None

    # Database names
    db_name: str = None  # Auto: {mine_name}_db
    profile_db_name: str = None  # Auto: {mine_name}_profiles_db

    # Tomcat
    tomcat_port: int = 8080

    # Build settings
    estimated_build_hours: int = 6
    data_source_urls: List[str] = field(default_factory=list)

    # Resource allocation
    memory_gb: int = 64
    requires_variants: bool = False  # VCF data needs more memory

# Define all mines
MINE_CONFIGS = {
    "alliancemine": MineConfig(
        mine_name="alliancemine",
        organism="Multi-species (7 organisms)",
        description="Alliance of Genome Resources InterMine",
        mine_repo_url="https://github.com/alliance-genome/alliancemine",
        biosources_repo_url="https://github.com/alliance-genome/agr_bio_sources",
        tomcat_port=8080,
        estimated_build_hours=7,
        requires_variants=True,
        data_source_urls=[
            "https://fms.alliancegenome.org/api/data/gene-basic/",
            "https://fms.alliancegenome.org/api/data/allele/",
            # ... etc
        ]
    ),

    "wormmine": MineConfig(
        mine_name="wormmine",
        organism="Caenorhabditis elegans",
        description="WormBase InterMine",
        mine_repo_url="https://github.com/wormbase/wormmine",
        tomcat_port=8081,
        estimated_build_hours=4,
    ),

    "flymine": MineConfig(
        mine_name="flymine",
        organism="Drosophila melanogaster",
        description="FlyBase InterMine",
        mine_repo_url="https://github.com/flybase/flymine",
        biosources_repo_url="https://github.com/flybase/flymine-bio-sources",
        tomcat_port=8082,
        estimated_build_hours=6,
        data_source_urls=[
            "https://ftp.flybase.org/releases/current/",
        ]
    ),

    "mousemine": MineConfig(
        mine_name="mousemine",
        organism="Mus musculus",
        description="MGI InterMine",
        mine_repo_url="https://github.com/mgijax/mousemine",
        tomcat_port=8083,
        estimated_build_hours=5,
        requires_variants=True,
    ),

    "ratmine": MineConfig(
        mine_name="ratmine",
        organism="Rattus norvegicus",
        description="RGD InterMine",
        mine_repo_url="https://github.com/rat-genome-database/ratmine",
        tomcat_port=8084,
        estimated_build_hours=4,
    ),

    "yeastmine": MineConfig(
        mine_name="yeastmine",
        organism="Saccharomyces cerevisiae",
        description="SGD InterMine",
        mine_repo_url="https://github.com/yeastgenome/yeastmine",
        tomcat_port=8085,
        estimated_build_hours=3,
    ),

    "zebrafishmine": MineConfig(
        mine_name="zebrafishmine",
        organism="Danio rerio",
        description="ZFIN InterMine",
        mine_repo_url="https://github.com/zfin/zebrafishmine",
        tomcat_port=8086,
        estimated_build_hours=4,
    )
}
```

---

## Deployment Workflow

### Step-by-Step Deployment

#### 1. Initial Infrastructure Setup (One-time)

```bash
# 1. Provision RDS
terraform apply -target=aws_db_instance.multi_tenant_rds

# 2. Launch Production EC2
terraform apply -target=aws_instance.production_tomcat

# 3. Install Tomcat multi-instance
ansible-playbook setup-multi-tomcat.yml

# 4. Install Solr
ansible-playbook setup-solr.yml

# 5. Create all databases
for mine in alliancemine flymine wormmine ...; do
    psql -h $RDS_ENDPOINT -c "CREATE DATABASE ${mine}_db;"
    psql -h $RDS_ENDPOINT -c "CREATE DATABASE ${mine}_profiles_db;"
done
```

#### 2. Build Mines (Docker Container Workflow)

```bash
# SSH to build instance
ssh ec2-user@172.31.60.197

# Navigate to mine directory
cd agr_intermine_builder/docker/alliancemine-unified

# Set database version
python3 set_db_version.py -1     # Creates alliancemine_8_3_0-1

# Build via Docker container
docker-compose up -d
docker exec -it alliancemine bash
./gradlew buildDB
./gradlew cargoDeployRemote      # Deploy to production

# Or use Python CLI
python -m src.cli.build_mines build --mine alliancemine
python -m src.cli.build_mines build-all
```

#### 3. Ongoing Updates (Incremental)

```bash
# Rebuild specific mine when data updates
cd docker/alliancemine-unified
python3 build_mine.py -1         # Automated: set version + restart + build

# Build schedule:
# - AllianceMine: Monthly (with AGR releases)
# - WormMine: As needed (WormBase updates)
# - Other mines: On-demand
```

---

## Cost Analysis

### Monthly Costs (2024 Pricing)

| Component | Type | Cost | Notes |
|-----------|------|------|-------|
| **Multi-Tenant EC2** | c7i.4xlarge (24/7) | $496 | WormMine + future mines |
| **AllianceMine EC2** | m6i.2xlarge (24/7) | $280 | Production |
| **Build EC2** | AllianceMineDev (24/7) | $150 | Persistent build instance |
| **RDS Database** | db.r6g.xlarge (24/7) | $260 | Multi-tenant |
| **RDS Storage** | 500GB gp3 | $55 | All mine data |
| **ALB** | Application Load Balancer | $25 | Request-based |
| **Data Transfer** | S3, API calls | $20 | Data downloads |
| **EBS Volumes** | gp3 storage | $20 | EC2 attached |
| **ECR** | Container registry | $10 | Image storage |
| **Total (on-demand)** | | **~$1,316/month** | |
| **Total (optimized)** | | **~$1,000/month** | With reserved instances |

**Cost Savings vs Individual Mines:**
- 7 separate RDS instances: ~$3,640/month
- 7 separate EC2 instances: ~$1,960/month
- **Total traditional:** ~$5,600/month
- **Multi-tenant:** ~$1,316/month
- **Savings:** ~$4,284/month (77% reduction!)

---

## Implementation Status

### Phase 1: Infrastructure Setup (Completed)

- [x] Create Multi-Tenant EC2 with native Solr (c7i.4xlarge)
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

## Related Documentation

- [EC2 Architecture Design](ec2-step-functions-design.md)
- [Multi-Tenant Deployment Guide](../MULTITENANT_DEPLOYMENT.md)
- [WormMine Multi-Tenant Setup](../WORMMINE_MULTITENANT_SETUP.md)
- [Database Versioning](../../docker/alliancemine-unified/DATABASE_VERSIONING.md)
- [Docker Architecture](../DOCKER_ARCHITECTURE.md)

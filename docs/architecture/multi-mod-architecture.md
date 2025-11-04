# Multi-MOD InterMine Architecture

## Vision Overview

Based on your architecture diagram, we have:

```
┌─────────────────────────────────────────────────────────────────────┐
│                     PRODUCTION ENVIRONMENT                           │
├─────────────────────────────────────────────────────────────────────┤
│                                                                      │
│  ┌────────────────────────────────────────────────────────────┐    │
│  │  Production EC2 (Multi-Instance Tomcat + Solr)             │    │
│  │  ┌──────────┐ ┌──────────┐ ┌──────────┐                   │    │
│  │  │Alliance  │ │  Fly     │ │  Worm    │  ... + 4 more     │    │
│  │  │:8080     │ │  :8081   │ │  :8082   │                   │    │
│  │  └──────────┘ └──────────┘ └──────────┘                   │    │
│  │                                                             │    │
│  │  ┌──────────────┐                                          │    │
│  │  │ Solr Cluster │  (Shared search index)                  │    │
│  │  └──────────────┘                                          │    │
│  └────────────────────────────────────────────────────────────┘    │
│                              ↓                                      │
│  ┌────────────────────────────────────────────────────────────┐    │
│  │  RDS PostgreSQL (Multi-tenant)                             │    │
│  │  ┌─────────────┐ ┌─────────────┐ ┌─────────────┐          │    │
│  │  │alliancemine │ │  flymine    │ │  wormmine   │ + 4 more │    │
│  │  │_db          │ │  _db        │ │  _db        │          │    │
│  │  └─────────────┘ └─────────────┘ └─────────────┘          │    │
│  └────────────────────────────────────────────────────────────┘    │
│                              ↑                                      │
│                    Reads from (shared)                              │
│                                                                      │
└─────────────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────────────┐
│                      BUILD ENVIRONMENT                               │
├─────────────────────────────────────────────────────────────────────┤
│                                                                      │
│  ┌────────────────────────────────────────────────────────────┐    │
│  │  Ephemeral Build EC2 (r6i.2xlarge, 64GB)                   │    │
│  │  ┌──────────────────────────────────────────────────┐      │    │
│  │  │ EC2Builder                                       │      │    │
│  │  │  - Builds one mine at a time                     │      │    │
│  │  │  - Auto-terminates after completion              │      │    │
│  │  └──────────────────────────────────────────────────┘      │    │
│  └────────────────────────────────────────────────────────────┘    │
│                              ↓                                      │
│                    Writes to (during build)                         │
│                              ↓                                      │
│  [Same RDS PostgreSQL - builds directly into production DB]        │
│                                                                      │
└─────────────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────────────┐
│                         BLUEGENES UI                                 │
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
├── flymine/              # Instance 2
│   ├── conf/
│   │   └── server.xml   # Port 8081
│   └── webapps/
│       └── flymine.war
├── wormmine/             # Instance 3
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
systemctl start tomcat@flymine
systemctl start tomcat@wormmine
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

upstream flymine {
    server 127.0.0.1:8081;
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

    # FlyMine
    location /flymine/ {
        proxy_pass http://flymine/flymine/;
        proxy_set_header Host $host;
    }

    # ... etc
}
```

**Public URLs:**
- `https://intermine.alliancegenome.org/alliancemine/`
- `https://intermine.alliancegenome.org/flymine/`
- `https://intermine.alliancegenome.org/wormmine/`
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
        ├── flymine/
        ├── wormmine/
        ├── mousemine/
        ├── ratmine/
        ├── yeastmine/
        └── zebrafishmine/
```

**Solr endpoints:**
- `http://localhost:8983/solr/alliancemine`
- `http://localhost:8983/solr/flymine`
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
flymine_db                   | 80 GB
flymine_profiles_db          | 200 MB
wormmine_db                  | 60 GB
wormmine_profiles_db         | 150 MB
mousemine_db                 | 120 GB
mousemine_profiles_db        | 300 MB
ratmine_db                   | 50 GB
ratmine_profiles_db          | 100 MB
yeastmine_db                 | 30 GB
yeastmine_profiles_db        | 100 MB
zebrafishmine_db             | 40 GB
zebrafishmine_profiles_db    | 100 MB
```

**Total Storage:** ~530 GB (room for growth to 2TB)

#### Connection Management

**HikariCP connection pools per mine:**

```properties
# Each mine gets dedicated pool
alliancemine.pool.size=20
flymine.pool.size=15
wormmine.pool.size=15
mousemine.pool.size=15
ratmine.pool.size=10
yeastmine.pool.size=10
zebrafishmine.pool.size=10

# Total: 95 connections (well below max_connections=200)
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

### 3. Ephemeral Build EC2

**Instance Type:** `r6i.2xlarge` (8 vCPU, 64GB RAM)
**Lifecycle:** Launch → Build → Terminate
**Cost:** ~$3.53 per build × 7 mines = ~$25 per full rebuild

#### Build Strategy: Sequential Builds

**Why Sequential?**
1. 64GB RAM sufficient for one mine, not multiple
2. RDS connection limits (max 200 connections)
3. Simplifies error handling
4. Easier to monitor

**Build Queue:**
```
Queue:
1. alliancemine (7 hours)
2. flymine (6 hours)
3. mousemine (5 hours)
4. wormmine (4 hours)
5. ratmine (4 hours)
6. zebrafishmine (4 hours)
7. yeastmine (3 hours)

Total: ~33 hours sequential
```

#### Build Process Per Mine

```python
# Pseudo-code
for mine_name in ["alliancemine", "flymine", "wormmine", ...]:
    # 1. Launch ephemeral EC2
    instance = launch_build_instance()

    # 2. Run build
    builder = EC2Builder(config)
    result = builder.build_full(mine_name)

    # 3. Deploy to production Tomcat
    deploy_webapp(mine_name, result.war_file)

    # 4. Index in Solr
    index_in_solr(mine_name)

    # 5. Terminate instance
    terminate_instance(instance)
```

---

### 4. Build Orchestration Options

#### Option A: Sequential Build (Simple)

**Pros:**
- Simple to implement
- No resource contention
- Easy error handling

**Cons:**
- 33 hours total time
- Expensive if all mines need rebuilding

**Implementation:**
```python
# src/lib/builder/multi_mine_builder.py

class MultiMineBuilder:
    def build_all_mines(self):
        mines = [
            "alliancemine",
            "flymine",
            "mousemine",
            "wormmine",
            "ratmine",
            "yeastmine",
            "zebrafishmine"
        ]

        for mine in mines:
            self.build_single_mine(mine)
```

#### Option B: Parallel Build (Advanced)

**Use multiple build instances:**
- 2-3 EC2 instances running simultaneously
- Build smaller mines in parallel
- Larger mines (AllianceMine, FlyMine) get dedicated instance

**Pros:**
- Faster: 33 hours → ~12 hours
- Better resource utilization

**Cons:**
- More complex
- Higher cost during build
- RDS connection management needed

**Implementation:**
```python
# Run in parallel
parallel_builds = [
    ["alliancemine"],  # Instance 1 (large)
    ["flymine"],       # Instance 2 (large)
    ["mousemine", "wormmine", "ratmine"]  # Instance 3 (smaller)
]
```

#### Option C: Incremental Builds (Optimal)

**Only rebuild changed mines:**

```python
def should_rebuild_mine(mine_name):
    # Check if data has changed
    last_build = get_last_build_date(mine_name)
    data_version = get_latest_data_version(mine_name)

    return data_version > last_build

# Only build what's needed
mines_to_build = [
    mine for mine in ALL_MINES
    if should_rebuild_mine(mine)
]
```

**Typical scenario:**
- Alliance releases monthly → Rebuild AllianceMine only
- FlyBase updates quarterly → Rebuild FlyMine
- Most mines: Rebuild on-demand

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

    "flymine": MineConfig(
        mine_name="flymine",
        organism="Drosophila melanogaster",
        description="FlyBase InterMine",
        mine_repo_url="https://github.com/flybase/flymine",
        biosources_repo_url="https://github.com/flybase/flymine-bio-sources",
        tomcat_port=8081,
        estimated_build_hours=6,
        data_source_urls=[
            "https://ftp.flybase.org/releases/current/",
        ]
    ),

    "wormmine": MineConfig(
        mine_name="wormmine",
        organism="Caenorhabditis elegans",
        description="WormBase InterMine",
        mine_repo_url="https://github.com/wormbase/wormmine",
        tomcat_port=8082,
        estimated_build_hours=4,
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

#### 2. Build All Mines (Initial)

```bash
# Option A: Sequential (simple)
python -m src.main build-all-mines --sequential

# Option B: Parallel (faster)
python -m src.main build-all-mines --parallel --workers 3

# What happens:
# 1. Launch build EC2(s)
# 2. For each mine:
#    a. Run EC2Builder
#    b. Build completes
#    c. Deploy WAR to Tomcat
#    d. Index in Solr
# 3. Terminate build EC2(s)
```

#### 3. Ongoing Updates (Incremental)

```bash
# Rebuild only changed mines
python -m src.main build-mine alliancemine

# Or scheduled via EventBridge:
# - AllianceMine: Monthly (when AGR releases)
# - FlyMine: Quarterly (when FlyBase releases)
# - Others: On-demand
```

---

## Cost Analysis

### Monthly Costs

| Component | Type | Cost | Notes |
|-----------|------|------|-------|
| **Production EC2** | m6i.2xlarge (24/7) | $280 | All mines running |
| **RDS Database** | db.r6g.2xlarge (24/7) | $520 | Multi-tenant |
| **RDS Storage** | 2TB gp3 | $230 | All mine data |
| **Build EC2** | r6i.2xlarge (on-demand) | $25 | ~7 builds/month |
| **Data Transfer** | S3, API calls | $20 | Data downloads |
| **Solr Storage** | EBS gp3 | $30 | Search indexes |
| **Backups** | RDS snapshots | $50 | Daily backups |
| **Total** | | **~$1,155/month** | |

**Cost Savings vs Individual Mines:**
- 7 separate RDS instances: ~$3,640/month
- 7 separate EC2 instances: ~$1,960/month
- **Total traditional:** ~$5,600/month
- **Multi-tenant:** ~$1,155/month
- **Savings:** ~$4,445/month (79% reduction!)

---

## Next Steps: Implementation

### Phase 1: Enhanced Config (Week 1)

1. Add `MineConfig` to config.py
2. Add `MINE_CONFIGS` dictionary
3. Update EC2Builder to accept MineConfig

### Phase 2: Multi-Mine Builder (Week 2)

1. Create `MultiMineBuilder` class
2. Implement sequential build
3. Add build queue management

### Phase 3: Infrastructure as Code (Week 3)

1. Terraform for RDS multi-tenant setup
2. Terraform for Production EC2
3. Ansible for Tomcat multi-instance

### Phase 4: Deployment Automation (Week 4)

1. WAR deployment to specific Tomcat instance
2. Solr core creation and indexing
3. Health checks per mine

### Phase 5: Step Functions Integration (Week 5)

1. State machine for multi-mine builds
2. Parallel build orchestration
3. Error handling and notifications

---

## Questions for You

1. **Build Strategy:** Sequential or Parallel builds?
2. **Update Frequency:** Monthly? Quarterly? On-demand?
3. **Dev Environment:** Should DEV use same RDS or separate?
4. **Bluegenes:** Single Bluegenes for all mines, or one per mine?
5. **Monitoring:** What metrics are most important?

**Ready to implement? Which phase should we start with?**

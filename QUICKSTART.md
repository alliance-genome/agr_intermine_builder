# InterMine Builder - Quick Start Guide

## 📋 Prerequisites

- **Docker** installed and running
- **Python 3.9+** installed
- **uv** package manager installed
- **RDS PostgreSQL** instance running and accessible
- **WormMine data files** (for WormMine only) in a local folder

## 🚀 Step-by-Step Usage

### Step 1: Install Dependencies

```bash
cd /path/to/agr_intermine_builder
uv pip install -e .
```

**What happens:**
- Installs Python dependencies (docker, boto3, psycopg2, etc.)
- Makes the `build-mines` CLI command available
- Sets up the project in development mode

### Step 2: Configure Environment

Create a `.env` file in the project root:

```bash
# RDS Configuration (REQUIRED)
RDS_HOST=your-rds-endpoint.rds.amazonaws.com
RDS_PORT=5432
RDS_USER=postgres
RDS_PASSWORD=your-secure-password

# Optional: AWS credentials
AWS_ACCESS_KEY_ID=your-key
AWS_SECRET_ACCESS_KEY=your-secret
AWS_REGION=us-east-1
```

**What happens:**
- These environment variables will be loaded automatically
- The system will use these credentials to connect to RDS
- Each mine will get its own database on this RDS instance

### Step 3: Prepare WormMine Data (WormMine Only)

If building WormMine, place your WormBase data files here:

```bash
mkdir -p docker/multi_mine_rds/wormmine/custom_data
# Copy your WormBase files to this directory
```

Expected files:
- `annotations.gff3.gz`
- `gene_association.gaf.gz`
- `orthologs.txt.gz`
- `alleles.tsv.gz`
- `rnai_phenotypes.wb`
- `interactions.txt.gz`

**What happens:**
- These files will be mounted into the WormMine container
- The build process will copy them to the working directory
- No download from FTP is attempted (Cloudflare protection bypass)

### Step 4: Build Your First Mine

Start with AllianceMine (downloads data automatically):

```bash
python -m src.cli.build_mines build --mine alliancemine
```

**What happens:**
1. **Docker Image Build** (10-15 minutes)
   - Pulls Alpine Linux base image
   - Installs Java 8, Gradle, Perl modules
   - Clones alliancemine and alliancemine-bio-sources repos
   - Builds bio-sources with `./gradlew install`

2. **Container Creation** (30 seconds)
   - Creates container with 32GB memory, 8 CPUs
   - Mounts data volumes
   - Sets up RDS connection parameters

3. **Container Start** (10 seconds)
   - Starts container
   - Runs entrypoint script
   - Verifies RDS connectivity

4. **Build Stages** (3-4 hours total)
   - **buildDB** (5-10 min): Creates PostgreSQL schema
   - **extract_data** (10-30 min): Downloads Alliance data from FMS
   - **project_build** (2-4 hours): ⏰ Data integration (LONGEST!)
   - **postprocess** (30-60 min): Indexing and summary tables
   - **buildUserDB** (5-10 min): Creates profile database ⚠️ **ONE-TIME ONLY**
     - Checks if profile DB already exists
     - If exists, skips creation (persistent across builds)
     - Can import from production releases
   - **war** (10-20 min): Builds web application WAR file
   - **deploy** (5-10 min): Deploys to Tomcat (optional)

5. **Final Result**
   - AllianceMine database created on RDS: `alliancemine_db`
   - Profile database created: `alliancemine_profiles_db`
   - WAR file built and ready for deployment
   - Container running and accessible

### Step 5: Monitor Progress

While building, open another terminal and check status:

```bash
# Check container status
python -m src.cli.build_mines status --mine alliancemine

# Watch Docker logs
docker logs -f alliancemine-builder

# View specific stage log
docker exec alliancemine-builder cat /tmp/project_build.log
```

**What you'll see:**
- Real-time console output showing current stage
- Progress percentages
- Stage completion times
- Any errors or warnings

### Step 6: Build Additional Mines

After AllianceMine completes, build the others:

```bash
# Build WormMine (uses your custom data)
python -m src.cli.build_mines build --mine wormmine

# Build MouseMine
python -m src.cli.build_mines build --mine mousemine

# Build FlyMine
python -m src.cli.build_mines build --mine flymine
```

**Or build all at once:**

```bash
python -m src.cli.build_mines build-all
```

**What happens:**
- Builds each mine sequentially: AllianceMine → WormMine → MouseMine → FlyMine
- Creates separate databases on RDS for each mine
- Each mine takes 3-6 hours to complete
- **Total time for all 4 mines: 12-24 hours**
- If one fails, stops (unless you use `--continue-on-error`)

## 🔧 Common Commands

### List Available Mines
```bash
python -m src.cli.build_mines list
```

### Build with Image Rebuild
```bash
python -m src.cli.build_mines build --mine alliancemine --rebuild
```

### Execute Single Stage
```bash
# Just create the database schema
python -m src.cli.build_mines stage --mine alliancemine --stage buildDB

# Just extract data
python -m src.cli.build_mines stage --mine alliancemine --stage extract_data
```

### Skip Stages
```bash
# Build but skip deployment
python -m src.cli.build_mines build --mine alliancemine --skip-stages deploy

# Skip buildUserDB if profile already exists
python -m src.cli.build_mines build --mine alliancemine --skip-stages buildUserDB
```

### Import Profile Database from Production
```bash
# Place your pg_dump file in a mounted volume, then:
from src.intermine_builder import MineBuilder, MineType, BuildExecutor
from src.intermine_builder.config import Config

config = Config.from_env()
with MineBuilder(config) as builder:
    # Create container
    builder.docker_manager.create_container(...)
    builder.docker_manager.start_container(MineType.ALLIANCEMINE)

    # Import profile DB
    executor = BuildExecutor(builder.docker_manager, mine_config)
    executor.import_profile_db("/root/data/alliancemine_profiles.sql")
```

### Cleanup
```bash
# Cleanup specific mine
python -m src.cli.build_mines cleanup --mine alliancemine

# Cleanup all mines
python -m src.cli.build_mines cleanup
```

## 📊 What Gets Created

### On RDS PostgreSQL

| Mine | Main Database | Profile Database | Connections | Profile Notes |
|------|--------------|------------------|-------------|---------------|
| AllianceMine | `alliancemine_db` | `alliancemine_profiles_db` | 20 main / 5 profile | Created once, persistent |
| WormMine | `wormmine_db` | `wormmine_profiles_db` | 15 main / 5 profile | Created once, persistent |
| MouseMine | `mousemine_db` | `mousemine_profiles_db` | 18 main / 5 profile | Created once, persistent |
| FlyMine | `flymine_db` | `flymine_profiles_db` | 16 main / 5 profile | Created once, persistent |

**Profile Database Notes:**
- **One-time creation**: Profile databases are checked before creation
- **Persistent**: Survives rebuilds - only created if doesn't exist
- **Unique per mine**: Each mine has its own profile DB
- **Importable**: Can import from production via `import_profile_db()`
- **Contains**: User accounts, saved queries, gene lists, templates

### On Docker

- **Images**: `alliancemine-rds:latest`, `wormmine-rds:latest`, etc.
- **Containers**: `alliancemine-builder`, `wormmine-builder`, etc.
- **Volumes**: Persistent data and log storage
- **Network**: `intermine-network` bridge network

### Files Generated

```
docker/multi_mine_rds/
├── alliancemine/
│   └── Dockerfile, build_full.sh, extract_data.sh
├── wormmine/
│   ├── Dockerfile, build_full.sh, extract_data.sh
│   └── custom_data/        # Your WormBase files
└── docker-compose.yml
```

## 🐛 Troubleshooting

### Build Fails at project_build
**Symptom:** Container runs out of memory during data integration

**Solution:**
```bash
# Increase Docker resources in Docker Desktop settings
# Or reduce Gradle heap in src/intermine_builder/mine_config.py
```

### Can't Connect to RDS
**Symptom:** "Connection refused" or timeout errors

**Solution:**
1. Check RDS security group allows connections from your IP
2. Verify RDS endpoint: `telnet $RDS_HOST 5432`
3. Check `.env` file has correct credentials

### WormMine Can't Find Data
**Symptom:** "No custom data found" error

**Solution:**
```bash
# Ensure data is in correct location
ls -lh docker/multi_mine_rds/wormmine/custom_data/

# Files must be exactly as expected (check QUICKSTART.md Step 3)
```

### Container Already Exists
**Symptom:** "Container name already in use"

**Solution:**
```bash
# Cleanup and rebuild
python -m src.cli.build_mines cleanup --mine alliancemine
python -m src.cli.build_mines build --mine alliancemine
```

## ⏱️ Time Estimates

| Stage | Duration | Notes |
|-------|----------|-------|
| Image Build | 10-15 min | One-time per mine (cached afterwards) |
| buildDB | 5-10 min | Creates schema |
| extract_data | 10-30 min | Downloads data (AllianceMine) |
| project_build | 2-4 hours | ⚠️ LONGEST STAGE - data integration |
| postprocess | 30-60 min | Indexing |
| buildUserDB | 5-10 min | Profile DB |
| war | 10-20 min | Web app build |
| deploy | 5-10 min | Optional |
| **TOTAL** | **3-6 hours** | Per mine |

## 📖 Next Steps

- Read full documentation: `BUILD_SYSTEM.md`
- Check Python API examples: `examples/quick_start.py`
- Review mine configurations: `src/intermine_builder/mine_config.py`
- Customize build stages: `src/intermine_builder/build_executor.py`

## 💡 Tips

1. **Start with AllianceMine** - It has automatic data download and is well-tested
2. **Monitor the first build** - Watch logs to understand the process
3. **Use screen/tmux** - Builds take hours, use a terminal multiplexer
4. **Check RDS first** - Ensure RDS connectivity before starting
5. **Have patience** - The project_build stage is slow but normal

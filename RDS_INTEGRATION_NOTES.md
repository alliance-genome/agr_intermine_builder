# RDS Integration Notes

## Current Status

The RDS instance has been successfully created with the following details:
- **Host**: `intermine-postgres.cmnnhlso7wdi.us-east-1.rds.amazonaws.com`
- **Port**: `5432`
- **User**: `postgres`
- **PostgreSQL Version**: `15`
- **Instance Type**: `db.t3.large` (Intel x86)
- **Storage**: `200GB gp3`
- **Parameter Group**: `intermine-postgres15` (custom optimized for InterMine)

## What Was Updated

### 1. Environment Configuration (`.env`)

Added RDS credentials to `.env`:
```bash
RDS_HOST=intermine-postgres.cmnnhlso7wdi.us-east-1.rds.amazonaws.com
RDS_PORT=5432
RDS_USER=postgres
RDS_PASSWORD=zpS-4BNKUAOiulFtIUOZE2kvDlWi9mKmuak8Zs9LJz0
```

### 2. Configuration Loading (`src/intermine_builder/config.py`)

**Changes made**:
- Added `from dotenv import load_dotenv` and `load_dotenv()` to automatically load `.env` file
- Updated `DatabaseConfig.from_env()` to prioritize `RDS_*` environment variables:
  ```python
  user=os.getenv("RDS_USER", os.getenv("POSTGRES_USER", "postgres"))
  password=os.getenv("RDS_PASSWORD", os.getenv("POSTGRES_PASSWORD", "postgres"))
  host=os.getenv("RDS_HOST", os.getenv("POSTGRES_HOST", os.getenv("DB_HOST", "postgres")))
  port=int(os.getenv("RDS_PORT", os.getenv("POSTGRES_PORT", os.getenv("DB_PORT", "5432"))))
  ```

**Backward compatibility**: The system still supports `POSTGRES_*` and `DB_*` environment variables as fallbacks.

### 3. RDS Provisioner (`src/intermine_builder/rds_provisioner.py`)

**Changes made**:
- Changed PostgreSQL version from `16.4` to `15` (AWS compatibility)
- Changed parameter group family from `postgres16` to `postgres15`
- Fixed `synchronous_commit` parameter value from `'0'` to `'off'` (AWS requirement)
- Fixed tag values to use `+` instead of `,` (AWS tag restrictions)
- Fixed gp3 IOPS/throughput settings (only apply when storage >= 400GB)

## How It Works Now

### Build Flow

1. **Configuration Loading**:
   - When you run `uv run python -m src.cli.build_mines build --mine alliancemine`
   - The CLI calls `Config.from_env()` which loads `.env` file automatically
   - RDS credentials are loaded into `config.database`

2. **Docker Container Creation**:
   - `MineBuilder.build_mine()` passes RDS config to `DockerManager.create_container()`
   - Container is created with environment variables:
     ```python
     RDS_HOST=intermine-postgres.cmnnhlso7wdi.us-east-1.rds.amazonaws.com
     RDS_PORT=5432
     RDS_USER=postgres
     RDS_PASSWORD=zpS-4BNKUAOiulFtIUOZE2kvDlWi9mKmuak8Zs9LJz0
     RDS_DB_NAME=alliancemine_db
     RDS_PROFILE_DB_NAME=alliancemine_profiles_db
     ```

3. **Build Scripts**:
   - Inside the container, build scripts use these environment variables to connect to RDS
   - No local PostgreSQL container needed
   - All mines share the same RDS instance but use different databases

## Database Layout

The RDS instance hosts **8 databases**:

| Database | Purpose | Mine |
|----------|---------|------|
| `alliancemine_db` | Main data | AllianceMine |
| `alliancemine_profiles_db` | User profiles | AllianceMine |
| `wormmine_db` | Main data | WormMine |
| `wormmine_profiles_db` | User profiles | WormMine |
| `mousemine_db` | Main data | MouseMine |
| `mousemine_profiles_db` | User profiles | MouseMine |
| `flymine_db` | Main data | FlyMine |
| `flymine_profiles_db` | User profiles | FlyMine |

These databases are:
- **Persistent**: Created once, reused across builds
- **Isolated**: Each mine has its own schemas
- **Profile DBs**: Created once and never dropped (user data persists)

## InterMine Optimizations Applied

The custom parameter group `intermine-postgres15` includes:

| Parameter | Value | Purpose |
|-----------|-------|---------|
| max_connections | 250 | InterMine production recommendation |
| shared_buffers | 25% of RAM (~2GB) | Caching frequently accessed data |
| effective_cache_size | 50% of RAM (~4GB) | Query planner optimization |
| work_mem | 512MB | Sort and hash operations |
| maintenance_work_mem | 1GB | VACUUM, CREATE INDEX operations |
| default_statistics_target | 250 | Better query plans |
| synchronous_commit | off | Performance boost (InterMine rec) |
| autovacuum_max_workers | 3 | Critical for data loading |

**Source**: [InterMine PostgreSQL Documentation](https://intermine.readthedocs.io/en/latest/system-requirements/software/postgres/postgres/)

## What Still Needs to Be Done

### 1. Verify Docker Build Scripts

Check that the Dockerfiles and build scripts inside the containers properly use the RDS environment variables:

**Files to check**:
- `docker/multi_mine_rds/alliancemine/Dockerfile`
- `docker/multi_mine_rds/alliancemine/build_intermine.sh` (or similar build scripts)
- Any `.properties` files that configure database connections

**Expected behavior**:
- Build scripts should read `$RDS_HOST`, `$RDS_PORT`, `$RDS_USER`, `$RDS_PASSWORD`, `$RDS_DB_NAME`
- Should **NOT** try to start a local PostgreSQL container
- Should **NOT** try to create databases (already created by RDS provisioner)

### 2. Test End-to-End Build

Try running a build to verify everything works:

```bash
# Test connection to RDS first
psql -h intermine-postgres.cmnnhlso7wdi.us-east-1.rds.amazonaws.com \
     -U postgres \
     -d alliancemine_db

# Then try a build
uv run python -m src.cli.build_mines build --mine alliancemine
```

### 3. Check Database Creation

Verify that all 8 databases were created properly:

```bash
psql -h intermine-postgres.cmnnhlso7wdi.us-east-1.rds.amazonaws.com \
     -U postgres \
     -c "\l" | grep mine
```

Expected output:
```
alliancemine_db        | postgres | ...
alliancemine_profiles_db | postgres | ...
wormmine_db            | postgres | ...
wormmine_profiles_db   | postgres | ...
mousemine_db           | postgres | ...
mousemine_profiles_db  | postgres | ...
flymine_db             | postgres | ...
flymine_profiles_db    | postgres | ...
```

### 4. Security Group Access

Ensure your local machine can connect to RDS:
- RDS security group allows port 5432 from your IP
- Or from `0.0.0.0/0` (less secure but easier for development)

You can check with:
```bash
telnet intermine-postgres.cmnnhlso7wdi.us-east-1.rds.amazonaws.com 5432
```

### 5. Cost Management

Consider stopping the RDS instance when not building:
```bash
# Stop instance (saves ~$105/month, keeps data)
uv run python -m src.cli.rds_manager stop

# Start when needed
uv run python -m src.cli.rds_manager start
```

## Troubleshooting

### Connection Refused

If builds fail with "connection refused" errors:

1. **Check security group**: RDS security group must allow inbound port 5432
   ```bash
   aws ec2 describe-security-groups --group-ids sg-07ef19e107f3f172e
   ```

2. **Verify RDS status**: Instance must be "available"
   ```bash
   uv run python -m src.cli.rds_manager status
   ```

3. **Test connection manually**:
   ```bash
   psql -h $RDS_HOST -U postgres -d postgres
   ```

### "Too Many Connections"

If you hit connection limits:

1. **Check current connections**:
   ```sql
   SELECT count(*), state FROM pg_stat_activity GROUP BY state;
   ```

2. **Kill idle connections**:
   ```sql
   SELECT pg_terminate_backend(pid)
   FROM pg_stat_activity
   WHERE state = 'idle'
     AND state_change < now() - interval '1 hour';
   ```

3. **Verify max_connections setting**:
   ```sql
   SHOW max_connections;  -- Should be 250
   ```

### Build Scripts Not Finding Database

If build scripts complain about missing database:

1. **Verify environment variables are passed to container**:
   ```bash
   docker exec alliancemine-builder env | grep RDS
   ```

2. **Check database exists**:
   ```bash
   psql -h $RDS_HOST -U postgres -c "\l" | grep alliancemine_db
   ```

3. **Verify build scripts use environment variables**:
   - Check Dockerfile and build scripts
   - Ensure they're using `$RDS_DB_NAME` not hardcoded values

## Next Steps

1. ✅ RDS instance created successfully
2. ✅ Configuration system updated to use RDS credentials
3. ⏳ **TODO**: Verify Docker build scripts use RDS environment variables
4. ⏳ **TODO**: Test end-to-end build with AllianceMine
5. ⏳ **TODO**: Update remaining mines (MouseMine, FlyMine) if needed

## References

- **RDS Setup Guide**: `RDS_SETUP.md`
- **Build System Docs**: `BUILD_SYSTEM.md`
- **Mine Configurations**: `src/intermine_builder/mine_config.py`
- **Docker Manager**: `src/intermine_builder/docker_manager.py`
- **Config Module**: `src/intermine_builder/config.py`

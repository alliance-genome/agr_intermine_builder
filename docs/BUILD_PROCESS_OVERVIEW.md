# AllianceMine Build Process — Complete Walkthrough

## What you have

A single build-only Docker container (`docker/alliancemine/`) that compiles AllianceMine and populates databases on AWS RDS. No Tomcat, no Solr inside the container — it builds, writes to RDS, and exits. Tomcat and Solr run natively on EC2.

```
┌──────────────────────────────────────┐
│  alliancemine-builder container      │
│                                      │
│  Alpine 3.20 + OpenJDK 8            │
│  Perl (for project_build)            │         ┌───────────────────┐
│  Python 3 (for build scripts)        │  JDBC   │  AWS RDS          │
│  PostgreSQL client                   │────────>│  PostgreSQL 15    │
│                                      │         │                   │
│  /root/alliancemine/    (compiled)   │         │  55 GB main DB    │
│  /root/scripts/         (Python)     │         │  16 MB profile DB │
│  /root/data/            (FMS data)   │         └───────────────────┘
│                                      │
│  32 GB RAM, 8 CPUs                  │         ┌───────────────────┐
│                                      │  WAR    │  EC2 Instance     │
│  Exits when done.                   │────────>│  Tomcat + Solr    │
└──────────────────────────────────────┘         └───────────────────┘
```

---

## Step 1: Configuration (minimal)

```bash
cd docker/alliancemine
cp .env.example .env
```

Edit `.env` — **only RDS credentials are required**:

```bash
RDS_HOST=intermine-postgres.cmnnhlso7wdi.us-east-1.rds.amazonaws.com
RDS_PORT=5432
RDS_USER=postgres
RDS_PASSWORD=<your-password>
```

Everything else is auto-detected:

| Parameter | What happens if not set |
|-----------|------------------------|
| `ALLIANCE_RELEASE` | Container calls `https://fms.alliancegenome.org/api/releaseversion/next` and parses `releaseVersion` from the JSON response (e.g., `9.0.0`) |
| `FMS_RELEASE_TYPE` | Defaults to `next`. Set to `current` if you want the published release instead of the upcoming one |
| `BUILD_TYPE` | Defaults to `test` |
| `RC_NUMBER` | Container queries RDS: finds all databases matching `alliancemine_{ver}_rcN`, gets the highest N, adds 1 |
| `COPY_PROFILE_DB` | Defaults to `false`. If `true`, test builds get an isolated copy of the profile DB |
| `DEPLOY_HOST` | If not set, WAR deployment is skipped |

So a completely hands-off test build is just:

```bash
docker compose run --rm alliancemine-builder build
```

No version number, no RC number — the container figures it out.

---

## Step 2: Build the Docker image (~15 minutes, one-time)

```bash
docker compose build
```

This bakes into the image:
- Clones `alliance-genome/alliancemine` and `alliance-genome/alliancemine-bio-sources` from GitHub
- Compiles bio-sources with Gradle (`./gradlew install`)
- Pre-downloads all Gradle dependencies
- Installs `project_build` Perl script from `intermine-scripts`
- Copies the Python build scripts and properties template

You only need to rebuild the image when the alliancemine or bio-sources repos change.

---

## Step 3: Container startup (what `entrypoint.sh` does)

When you run `docker compose run --rm alliancemine-builder build`, the entrypoint executes this sequence:

### 3a. Resolve release version

```
ALLIANCE_RELEASE not set in env?
  → wget https://fms.alliancegenome.org/api/releaseversion/next
  → Parse JSON: {"releaseVersion": "9.0.0", ...}
  → Export ALLIANCE_RELEASE=9.0.0
```

### 3b. Wait for RDS

```
pg_isready -h $RDS_HOST -p $RDS_PORT
  → Retries up to 60 times (2s intervals)
  → Fails if RDS is stopped or unreachable
```

### 3c. Auto-detect RC number

```
RC_NUMBER not set in env?
  → Sanitize version: 9.0.0 → 9_0_0
  → Query RDS:
      SELECT max(substring(datname from 'alliancemine_9_0_0_rc([0-9]+)')::int)
      FROM pg_database
      WHERE datname ~ '^alliancemine_9_0_0_rc[0-9]+'
  → Found rc2? → Set RC_NUMBER=3
  → Found nothing? → Set RC_NUMBER=1
```

### 3d. Construct database names

```
BUILD_TYPE=test, ALLIANCE_RELEASE=9.0.0, RC_NUMBER=3:
  Main DB:    alliancemine_9_0_0_rc3
  Profile DB: alliancemine_userprofile_test      (default for test builds)
              alliancemine_userprofile_rc3        (if COPY_PROFILE_DB=true)
  Items DB:   alliancemine_items

BUILD_TYPE=production, ALLIANCE_RELEASE=9.0.0:
  Main DB:    alliancemine_9_0_0
  Profile DB: alliancemine_userprofile            (production)
  Items DB:   alliancemine_items
```

### 3e. Set up profile database

Three modes depending on build type:

- **Test builds (default)**: Uses `alliancemine_userprofile_test`. If it doesn't exist, it's created as a template copy of the production `alliancemine_userprofile`. This is the safe default — test builds never touch production user data.

- **Test builds + `COPY_PROFILE_DB=true`**: Creates a fresh `alliancemine_userprofile_rcN` from production each time. Use this when you want a clean snapshot per RC.

- **Production builds**: Uses `alliancemine_userprofile` directly — the real production profile DB with user accounts, saved queries, and gene lists.

### 3f. Create databases on RDS

```
For each of [main, items, profile]:
  Does it exist? → skip
  Doesn't exist? → CREATE DATABASE
```

### 3g. Generate properties file

```
envsubst < /root/.intermine/alliancemine.properties.template \
         > /root/.intermine/alliancemine.properties
```

This substitutes all environment variables into the InterMine properties file that Gradle reads:

| Template variable | Example value | Property |
|-------------------|---------------|----------|
| `${RDS_HOST}` | `intermine-postgres.xxx.rds.amazonaws.com` | `db.production.datasource.serverName` |
| `${RDS_DB_NAME}` | `alliancemine_9_0_0_rc3` | `db.production.datasource.databaseName` |
| `${RDS_PROFILE_DB_NAME}` | `alliancemine_userprofile_test` | `db.userprofile-production.datasource.databaseName` |
| `${RDS_ITEMS_DB_NAME}` | `alliancemine_items` | `db.common-tgt-items.datasource.databaseName` |
| `${RDS_USER}` | `postgres` | `db.*.datasource.user` |
| `${RDS_PASSWORD}` | *(your password)* | `db.*.datasource.password` |
| `${ALLIANCE_RELEASE}` | `9.0.0` | `project.releaseVersion` |
| `${DEPLOY_HOST}` | `ec2-host.example.com` | `webapp.hostname` |
| `${DEPLOY_PORT}` | `8080` | `webapp.port` |
| `${SOLR_INDEX_URL}` | `http://solr:8983/solr/alliancemine-search` | `index.solrurl` |
| `${SOLR_AUTOCOMPLETE_URL}` | `http://solr:8983/solr/alliancemine-autocomplete` | `autocomplete.solrurl` |

---

## Step 4: The 7-stage build pipeline (`build_full.py`)

The Python script runs 7 stages sequentially. Total time: 3-6 hours.

| # | Stage | What it does | Duration |
|---|-------|-------------|----------|
| 1 | **buildDB** | `./gradlew buildDB` — creates the PostgreSQL schema (tables, indexes, constraints) on RDS | 5-10 min |
| 2 | **extract_data** | `python3 extract_data.py` — downloads gene, allele, disease, phenotype, orthology, GO data from the Alliance FMS API into `/root/data/` | 10-30 min |
| 3 | **project_build** | `./project_build -b -T localhost /root/data/dump` — the Perl data integration script. Reads all downloaded files, transforms them, and loads into the database. **This is the longest stage.** | 2-4 hours |
| 4 | **postprocess** | `./gradlew postprocess` — builds search indexes, summary tables, precomputed templates | 30-60 min |
| 5 | **buildUserDB** | `./gradlew buildUserDB` — initializes the profile database schema. **Automatically skipped** if the profile DB already has tables (checks `information_schema.tables`) | 5-10 min |
| 6 | **war** | `./gradlew war` — compiles the web application into a WAR file | 10-20 min |
| 7 | **deploy** | `deploy_war.py` → `./gradlew cargoRedeployRemote` — deploys the WAR to a remote Tomcat via the Tomcat manager API. **Skipped** if no `DEPLOY_HOST` is set | 5-10 min |

You can skip or resume:

```bash
# Skip stages
docker compose run --rm alliancemine-builder build --skip-stages buildUserDB deploy

# Resume from a specific stage (e.g., after fixing a postprocess error)
docker compose run --rm alliancemine-builder build --start-from postprocess
```

---

## Step 5: After the build

The build created a database like `alliancemine_9_0_0_rc3` on RDS, 50-60 GB of integrated genomic data. The WAR file sits in `webapp/build/libs/` inside the container (or was already deployed to EC2 if `DEPLOY_HOST` was set).

---

## Step 6: Release workflow

### Iterate on RCs

```bash
# Each run auto-increments: rc1, rc2, rc3...
docker compose run --rm alliancemine-builder build
docker compose run --rm alliancemine-builder build
docker compose run --rm alliancemine-builder build
```

### Promote an RC to production

```bash
# Preview
docker compose run --rm alliancemine-builder promote --rc 3 --dry-run

# Execute: ALTER DATABASE "alliancemine_9_0_0_rc3" RENAME TO "alliancemine_9_0_0"
docker compose run --rm alliancemine-builder promote --rc 3
```

The promote script:
1. Terminates all connections to the RC database
2. Drops any existing production database with that name (if re-promoting)
3. Renames `alliancemine_9_0_0_rc3` → `alliancemine_9_0_0`
4. Verifies the rename succeeded

### Deploy to production Tomcat

```bash
docker compose run --rm alliancemine-builder deploy \
    --host ec2-host.example.com --port 8080
```

### Cleanup old RCs

```bash
docker compose run --rm alliancemine-builder bash
psql -h $RDS_HOST -U $RDS_USER -d postgres \
    -c 'DROP DATABASE "alliancemine_9_0_0_rc1";'
psql -h $RDS_HOST -U $RDS_USER -d postgres \
    -c 'DROP DATABASE "alliancemine_9_0_0_rc2";'
```

---

## What's on RDS after a typical release cycle

| Database | Size | What it is |
|----------|------|-----------|
| `alliancemine_9_0_0` | ~55 GB | Production data warehouse (promoted from rc3) |
| `alliancemine_userprofile` | ~16 MB | Shared profile DB (user accounts, saved queries, gene lists) |
| `alliancemine_userprofile_test` | ~16 MB | Test copy (safe to modify freely) |
| `alliancemine_items` | ~8 KB | Intermediary data (safe to drop) |

---

## The Python orchestration layer (alternative path)

For CI/CD or batch builds, the Python layer wraps Docker for you:

```bash
uv pip install -e .

# Builds the Docker image, creates a container, runs all 7 stages
python -m src.cli.build_mines build --mine alliancemine

# Single stage
python -m src.cli.build_mines stage --mine alliancemine --stage buildDB

# Status / cleanup
python -m src.cli.build_mines status --mine alliancemine
python -m src.cli.build_mines cleanup --mine alliancemine
```

This uses the same Docker image and the same entrypoint — it just manages the container lifecycle programmatically via the Docker SDK instead of `docker compose`.

---

## Summary of what changed from the old system

| Before | After |
|--------|-------|
| Fragmented Docker setups (`multi_mine_rds/`, `alliancemine-unified/`) | Single `docker/alliancemine/` |
| Bash build scripts (fragile, no error handling) | Python build scripts (structured, testable) |
| Manual `ALLIANCE_RELEASE` required | Auto-fetched from FMS API |
| Manual `RC_NUMBER` required | Auto-incremented from RDS |
| Shared profile DB always (risk of corruption) | `COPY_PROFILE_DB=true` for isolated testing |
| `sed` substitution for properties | `envsubst` templates |
| Fixed DB names | Versioned: `alliancemine_{ver}_rcN` → `alliancemine_{ver}` |
| No promotion workflow | `promote_db.py` with dry-run |
| No tests | 65 unit tests, 57% coverage |
| Stale docs referencing deleted paths | Updated docs matching actual code |

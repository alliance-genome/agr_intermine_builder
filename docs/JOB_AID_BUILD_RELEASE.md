# AllianceMine Build & Release — Job Aid

Quick reference for running an AllianceMine build. For full details see `ALLIANCEMINE_BUILD_AND_RELEASE.md`.

---

## Before You Start

```bash
# Check RDS free storage (need 250+ GB)
aws cloudwatch get-metric-statistics --namespace AWS/RDS \
  --metric-name FreeStorageSpace \
  --dimensions Name=DBInstanceIdentifier,Value=intermine-postgres \
  --start-time $(date -u -d '5 minutes ago' +%Y-%m-%dT%H:%M:%S) \
  --end-time $(date -u +%Y-%m-%dT%H:%M:%S) \
  --period 300 --statistics Average \
  --query 'Datapoints[0].Average' --output text | awk '{printf "%.0f GB\n", $1/1024/1024/1024}'

# Drop old RC databases if needed
PGPASSWORD='...' psql -h intermine-postgres.cmnnhlso7wdi.us-east-1.rds.amazonaws.com \
  -U postgres -d postgres -c "SELECT datname, pg_size_pretty(pg_database_size(datname))
  FROM pg_database WHERE datname LIKE 'alliancemine_%' ORDER BY pg_database_size(datname) DESC"
```

---

## Step 1: Create Solr Cores (once per release)

```bash
python3 scripts/create_solr_cores.py \
  --release 9.0.0 \
  --solr-host 172.31.59.87 \
  --ssh-key ~/.ssh/AGR-ssl3.pem
```

---

## Step 2: Configure

```bash
ssh -i ~/.ssh/AGR-ssl3.pem ec2-user@172.31.60.197
cd ~/agr_intermine_builder/docker/alliancemine
```

Edit `.env` — set `ALLIANCE_RELEASE`, Solr URLs, credentials.

---

## Step 3: Build Image + Compile

```bash
docker compose build                                    # ~5 min
docker compose run -d --rm alliancemine-builder          # start for compilation
# Wait for compilation (~15 min):
CNAME=$(docker ps --format '{{.Names}}' | grep builder)
while docker exec $CNAME ls /root/.needs_compile 2>/dev/null; do sleep 30; done
docker commit $CNAME alliancemine-builder:9.0.0-compiled # save compiled image
docker stop $CNAME
```

Update `docker-compose.yml` → `image: alliancemine-builder:9.0.0-compiled`

---

## Step 4: Run Build

```bash
tmux new-session -s build
docker compose run --rm alliancemine-builder build       # ~5-8 hours
```

Monitor: `tail -f /tmp/alliancemine-9.0.0-build.log`

Detach tmux: `Ctrl+B D` — Reattach: `tmux attach -t build`

---

## Step 5: During Build — Manage Checkpoints

```bash
# List checkpoint databases
psql -h ... -d postgres -c \
  "SELECT datname, pg_size_pretty(pg_database_size(datname))
   FROM pg_database WHERE datname LIKE 'alliancemine_%rc%:%'"

# Drop old ones (keep the latest)
psql -h ... -d postgres -c 'DROP DATABASE "alliancemine_9_0_0_rcN:old-checkpoint"'
```

---

## Step 6: Fix Solr URLs + Rerun Indexes (if needed)

```bash
CNAME=$(docker ps --format '{{.Names}}' | grep builder)

# Patch hardcoded URLs
docker exec $CNAME sed -i \
  "s|index.solrurl = .*|index.solrurl = http://172.31.59.87:8983/solr/alliancemine-search-9.0.0|" \
  /root/alliancemine/dbmodel/resources/keyword_search.properties

docker exec $CNAME sed -i \
  "s|autocomplete.solrurl = .*|autocomplete.solrurl = http://172.31.59.87:8983/solr/alliancemine-autocomplete-9.0.0|" \
  /root/alliancemine/dbmodel/resources/objectstoresummary.config.properties

# Rerun indexes
docker exec $CNAME sh -c 'cd /root/alliancemine && ./gradlew postprocess -Pprocess=create-search-index --stacktrace'
docker exec $CNAME sh -c 'cd /root/alliancemine && ./gradlew postprocess -Pprocess=create-autocomplete-index --stacktrace'
```

---

## Step 7: Deploy

```bash
# Start Tomcat container on multitenant
ssh -i ~/.ssh/AGR-ssl3.pem ec2-user@172.31.59.87
docker run -d --name alliancemine-9.0.0 \
  --add-host agr.stage.alliancemine.solr.server:host-gateway \
  -p 8082:8080 intermine-tomcat:latest

# Deploy WAR (from AllianceMineDev)
docker compose run --rm alliancemine-builder release \
  --tomcat-host 172.31.59.87 --tomcat-port 8082
```

---

## Step 8: Verify

```bash
# Version endpoint
curl -s http://172.31.59.87:8082/alliancemine/service/version
# Expected: 35

# Solr cores
curl -s 'http://172.31.59.87:8983/solr/alliancemine-search-9.0.0/select?q=*:*&rows=0'
# Expected: numFound > 12,000,000
```

---

## If Build Fails — Resume

```bash
docker compose run --rm -e RC_NUMBER=N alliancemine-builder build \
  --start-from project_build --resume
```

Uses `-l` flag to load last DB checkpoint. **Do not** combine with a fresh build (`-b` flag).

---

## Key Numbers

| Metric | Value |
|--------|-------|
| Full build time | 5-8 hours |
| Main DB size | ~57 GB |
| Each checkpoint | 30-60 GB |
| RDS total storage | 500 GB |
| Search index | ~12.5M docs |
| Autocomplete index | ~53K docs |
| JVM heap | 48 GB |
| Container memory limit | 56 GB |
| FMS data files | 49 |
| Data download | ~16 GB |

---

## Emergency Contacts

| System | Who to Contact |
|--------|----------------|
| RDS storage full | Alliance DevOps |
| SGD database credentials | SGD team |
| Solr down | Check multitenant host |
| NCBI Entrez failures | Retry — transient |

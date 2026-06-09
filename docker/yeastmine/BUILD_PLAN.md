# YeastMine Build Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Take the `docker/yeastmine/` scaffold to a full end-to-end YeastMine data integration on RDS, through `:webapp:war`, reusing AllianceMine's SGD plumbing in the FlyMine/WormMine build style.

**Architecture:** A build-only Alpine/Java-8 image with the YeastMine + yeastmine-bio-sources source *baked in* (COPY-from-`source/`, compiled at image-build time), pushed to ECR. At runtime the entrypoint configures RDS + SGD datasources and creates DBs; `extract_data.py` stages file sources from S3 + ontology downloads; the operator drives `project_build` integration and gradle postprocess/war manually; `finalize_build.sh` regenerates the object-store summary and WAR.

**Tech Stack:** Docker (buildx, linux/amd64), Alpine 3.20, OpenJDK 8, Gradle (InterMine 1.x), PostgreSQL (RDS + SGD external), Python 3 (`extract_data.py`), AWS CLI (S3 + ECR), bash.

**Companion design:** `docker/yeastmine/BUILD_DESIGN.md` (read first).

**Scope boundary:** through `:webapp:war` on RDS. `create-search-index` postprocess is skipped this round (§9 of the design); webapp deploy, Solr cores, ALB, and public URL are out of scope.

---

## File Structure

| File | Responsibility | Action |
|---|---|---|
| `docker/yeastmine/.gitignore` | Keep `source/` (local fork) + `data/` out of git | Create |
| `docker/yeastmine/source/yeastmine/` | Operator's local YeastMine fork (rsynced in by build script) | Create (staged, gitignored) |
| `docker/yeastmine/source/yeastmine-bio-sources/` | Operator's local bio-sources fork | Create (staged, gitignored) |
| `docker/yeastmine/Dockerfile` | COPY-from-source, bintray strip, gradle heap, build-time compile | Rewrite |
| `docker/yeastmine/scripts/build_and_push.sh` | Stage fork → buildx amd64 → content-hash tag → ECR push | Create |
| `docker/yeastmine/properties/yeastmine.properties.template` | Add `db.sgd` datasource block + Solr URLs | Modify |
| `docker/yeastmine/docker-compose.yml` | Add `SGD_DB_*` + `SOLR_*` env | Modify |
| `docker/yeastmine/.env.example` | Document `SGD_DB_*` + `SOLR_*` | Modify |
| `docker/yeastmine/entrypoint.sh` | Add Solr URL derivation; compile-after-properties ordering | Modify |
| `docker/yeastmine/scripts/extract_data.py` | S3 sync of SGD file sources + ontology downloads | Create |
| `docker/yeastmine/scripts/finalize_build.sh` | summariseObjectStore + WAR rebuild (+ future patch SQL) | Create |
| `source/yeastmine/project.xml` (in the fork) | File-source paths `/data/intermine` → `/root/data/intermine`; drop `create-search-index` | Modify |

---

## Task 1: Convert Dockerfile to COPY-from-source + build-time compile

Brings YeastMine to the FlyMine image pattern: source baked in, compiled at build time, bintray plugins stripped, heap set, dbmodel Solr URL pointed at multitenant.

**Files:**
- Create: `docker/yeastmine/.gitignore`
- Modify: `docker/yeastmine/Dockerfile` (replace lines 63-108, the clone + runtime-compile blocks)

- [ ] **Step 1: Create `.gitignore` so the staged fork and data never get committed**

Create `docker/yeastmine/.gitignore`:
```gitignore
# Operator's local fork, staged in by scripts/build_and_push.sh — never commit source
source/
# Build data volume
data/*
!data/.gitkeep
# env with secrets
.env
```

- [ ] **Step 2: Replace the clone + runtime-compile blocks in the Dockerfile**

In `docker/yeastmine/Dockerfile`, replace everything from the `# Clone YeastMine Repositories` block through the `RUN touch /root/.needs_compile` line (current lines 63-108) with the COPY-from-source + build-time-compile blocks below. Keep lines 1-62 (base image, apk, cpanm, GRADLE_OPTS, WORKDIR, `.intermine`) and the final block (WORKDIR/HEALTHCHECK/ENTRYPOINT) unchanged.

```dockerfile
# ============================================
# YeastMine source — COPYed from staged build context (Approach A).
# We do NOT clone upstream. The operator's local fork at
# source/{yeastmine, yeastmine-bio-sources} carries the project.xml path
# rewrites (/data/intermine -> /root/data/intermine) and the dropped
# create-search-index postprocess. scripts/build_and_push.sh rsyncs the
# fork into source/ before `docker build`.
# ============================================
COPY source/yeastmine /root/yeastmine
COPY source/yeastmine-bio-sources /root/yeastmine-bio-sources

# ============================================
# Install project_build from intermine-scripts (upstream variant).
# ============================================
RUN git clone --depth 1 https://github.com/intermine/intermine-scripts.git /opt/intermine-scripts && \
    cp /opt/intermine-scripts/project_build /root/yeastmine/project_build && \
    chmod +x /root/yeastmine/project_build && \
    rm -rf /opt/intermine-scripts

# Fake ssh wrapper for project_build's checkpoint createdb step (RDS rejects
# real SSH). Drops the host arg and execs the command locally.
RUN printf '#!/bin/sh\nshift\nexec "$@"\n' > /usr/local/bin/ssh && \
    chmod +x /usr/local/bin/ssh

# ============================================
# Bake in runtime patches at build time:
#   1. Strip dead JCenter/bintray classpaths from bio-sources build.gradle
#   2. Append -Xmx48g to yeastmine/gradle.properties (no default heap upstream)
#   3. Point dbmodel keyword_search/objectstoresummary solrurl at multitenant
#      (only matters once create-search-index is re-enabled at deploy time).
# ============================================
RUN BS=/root/yeastmine-bio-sources/build.gradle && \
    if [ -f "$BS" ] && grep -q 'jfrog.bintray' "$BS"; then \
        sed -i '/com\.jfrog\.bintray\.gradle:gradle-bintray-plugin/d' "$BS" && \
        sed -i '/org\.jfrog\.buildinfo:build-info-extractor-gradle/d' "$BS" && \
        sed -i "/apply plugin: 'com\.jfrog\.bintray'/d" "$BS"; \
    fi && \
    GP=/root/yeastmine/gradle.properties && \
    if [ -f "$GP" ] && ! grep -q 'org.gradle.jvmargs.*-Xmx48g' "$GP"; then \
        echo '' >> "$GP" && \
        echo 'org.gradle.jvmargs=-Xmx48g -XX:+HeapDumpOnOutOfMemoryError' >> "$GP"; \
    fi && \
    KS=/root/yeastmine/dbmodel/resources/keyword_search.properties && \
    OS=/root/yeastmine/dbmodel/resources/objectstoresummary.config.properties && \
    [ -f "$KS" ] && sed -i 's|http://localhost:8983|http://172.31.59.87:8983|g' "$KS" || true && \
    [ -f "$OS" ] && sed -i 's|http://localhost:8983|http://172.31.59.87:8983|g' "$OS" || true
```

- [ ] **Step 3: Add Properties / entrypoint / scripts COPY block + build-placeholder properties + build-time compile**

Immediately after the block from Step 2 (and before the final `WORKDIR /root/yeastmine` block), the Dockerfile must COPY properties, entrypoint, and scripts, then compile. The existing lines 90-99 already COPY the properties template + entrypoint and append the heap; **delete those now-duplicated lines** (the heap append is handled in Step 2; properties/entrypoint COPY moves here) and replace with:

```dockerfile
# ============================================
# Properties + entrypoint + scripts
# ============================================
COPY properties/yeastmine.properties.template /root/.intermine/yeastmine.properties.template
COPY entrypoint.sh /root/entrypoint.sh
RUN chmod +x /root/entrypoint.sh

COPY scripts/extract_data.py /root/scripts/extract_data.py
COPY scripts/finalize_build.sh /root/scripts/finalize_build.sh
RUN chmod +x /root/scripts/extract_data.py /root/scripts/finalize_build.sh && \
    ln -sf /root/scripts/finalize_build.sh /usr/local/bin/finalize_build

RUN mkdir -p /root/data/dump /root/data/intermine

# ============================================
# Build-placeholder properties so webapp gradle config (which reads
# webapp.port as an int) succeeds at image-build time. The entrypoint
# overwrites /root/.intermine/yeastmine.properties via envsubst at runtime.
# ============================================
RUN cat > /root/.intermine/yeastmine.properties <<'EOF'
db.production.datasource.class=com.zaxxer.hikari.HikariDataSource
db.production.datasource.serverName=BUILD_PLACEHOLDER
db.production.datasource.databaseName=BUILD_PLACEHOLDER
db.production.datasource.user=BUILD_PLACEHOLDER
db.production.datasource.password=BUILD_PLACEHOLDER
db.production.driver=org.postgresql.Driver
db.production.platform=PostgreSQL
db.common-tgt-items.datasource.class=com.zaxxer.hikari.HikariDataSource
db.common-tgt-items.datasource.serverName=BUILD_PLACEHOLDER
db.common-tgt-items.datasource.databaseName=BUILD_PLACEHOLDER
db.common-tgt-items.datasource.user=BUILD_PLACEHOLDER
db.common-tgt-items.datasource.password=BUILD_PLACEHOLDER
db.common-tgt-items.driver=org.postgresql.Driver
db.common-tgt-items.platform=PostgreSQL
db.userprofile-production.datasource.class=com.zaxxer.hikari.HikariDataSource
db.userprofile-production.datasource.serverName=BUILD_PLACEHOLDER
db.userprofile-production.datasource.databaseName=BUILD_PLACEHOLDER
db.userprofile-production.datasource.user=BUILD_PLACEHOLDER
db.userprofile-production.datasource.password=BUILD_PLACEHOLDER
db.userprofile-production.driver=org.postgresql.Driver
db.userprofile-production.platform=PostgreSQL
db.sgd.datasource.class=org.postgresql.ds.PGPoolingDataSource
db.sgd.datasource.dataSourceName=db.sgd
db.sgd.datasource.serverName=BUILD_PLACEHOLDER
db.sgd.datasource.databaseName=BUILD_PLACEHOLDER
db.sgd.datasource.user=BUILD_PLACEHOLDER
db.sgd.datasource.password=BUILD_PLACEHOLDER
db.sgd.datasource.portNumber=5432
db.sgd.driver=org.postgresql.Driver
db.sgd.platform=PostgreSQL
project.title=YeastMine
project.subTitle=An integrated database of Saccharomyces cerevisiae genomics
project.releaseVersion=build-placeholder
project.sitePrefix=http://localhost:8080
webapp.deploy.url=http://localhost:8080
webapp.baseurl=http://localhost:8080
webapp.path=yeastmine
webapp.manager=manager
webapp.password=manager
webapp.port=8080
webapp.hostname=localhost
tomcat.user=manager
tomcat.pwd=manager
superuser.account=superuser@mail_account
superuser.initialPassword=secret
batch.size=1000
webapp.os.alias=os.production
webapp.query.cache.size=10000
webapp.query.cache.timeout=300
EOF

# ============================================
# Compile bio-sources + yeastmine + webapp WAR at IMAGE BUILD TIME.
# Runtime entrypoint compile is then a no-op (no /root/.needs_compile).
# ============================================
RUN cd /root/yeastmine-bio-sources && ./gradlew clean install --stacktrace --no-daemon && \
    cd /root/yeastmine && ./gradlew install --stacktrace --no-daemon && \
    rm -rf /root/.gradle/caches/transforms-* /root/.gradle/caches/journal-* /tmp/* 2>/dev/null || true
```

> Note: this removes the `RUN touch /root/.needs_compile` marker. The runtime
> `compile_if_needed()` already early-returns when the marker is absent, so the
> entrypoint needs no change for this. (Task 4 still touches the entrypoint for
> Solr + ordering, which is fine.)

- [ ] **Step 4: Stage a throwaway source tree and build the image (verifies the COPY pattern compiles)**

This task can't build until Task 2's script exists, so verification happens at the end of Task 2. Leave this checkbox and proceed to Task 2.

- [ ] **Step 5: Commit**

```bash
cd /Users/nuin/Projects/alliance/agr_intermine_builder
git add docker/yeastmine/.gitignore docker/yeastmine/Dockerfile
git commit -m "yeastmine: Dockerfile COPY-from-source + build-time compile (flymine pattern)"
```

---

## Task 2: Add `build_and_push.sh`

Stages the operator's local YeastMine fork into `source/`, builds `linux/amd64` via buildx, content-hash tags, optionally pushes to ECR. Modeled on `docker/flymine/scripts/build_and_push.sh`.

**Files:**
- Create: `docker/yeastmine/scripts/build_and_push.sh`

- [ ] **Step 1: Write the script**

Create `docker/yeastmine/scripts/build_and_push.sh`:
```bash
#!/usr/bin/env bash
#
# build_and_push.sh — stage the operator's local YeastMine fork, build the
# Docker image with source baked in, push to ECR.
#
# Usage:
#   ./scripts/build_and_push.sh               # build + push :latest
#   ./scripts/build_and_push.sh --no-push     # build only (local smoke test)
#   ./scripts/build_and_push.sh --tag v0.1    # custom tag
#
# Env overrides:
#   YEASTMINE_SRC_DIR              — default ${HOME}/Projects/alliance/new_yeastmine/yeastmine
#   YEASTMINE_BIO_SOURCES_SRC_DIR  — default ${HOME}/Projects/alliance/new_yeastmine/yeastmine-bio-sources
#   ECR_ACCOUNT / ECR_REGION / ECR_REPO

set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SRC_MINE="${YEASTMINE_SRC_DIR:-${HOME}/Projects/alliance/new_yeastmine/yeastmine}"
SRC_BIO="${YEASTMINE_BIO_SOURCES_SRC_DIR:-${HOME}/Projects/alliance/new_yeastmine/yeastmine-bio-sources}"
ECR_ACCOUNT="${ECR_ACCOUNT:-100225593120}"
ECR_REGION="${ECR_REGION:-us-east-1}"
ECR_HOST="${ECR_ACCOUNT}.dkr.ecr.${ECR_REGION}.amazonaws.com"
ECR_REPO="${ECR_REPO:-yeastmine-builder}"

TAG="latest"
PUSH=1
while [[ $# -gt 0 ]]; do
    case "$1" in
        --tag) TAG="$2"; shift 2 ;;
        --no-push) PUSH=0; shift ;;
        --help|-h) sed -n '2,20p' "$0"; exit 0 ;;
        *) echo "unknown arg: $1" >&2; exit 2 ;;
    esac
done

for d in "$SRC_MINE" "$SRC_BIO"; do
    if [[ ! -d "$d" ]]; then
        echo "ERROR: source dir does not exist: $d"
        echo "  Set YEASTMINE_SRC_DIR + YEASTMINE_BIO_SOURCES_SRC_DIR if your fork lives elsewhere."
        exit 1
    fi
done

STAGE="${HERE}/source"
echo "==> Staging local fork into ${STAGE} (rsync, excluding build artifacts)..."
mkdir -p "${STAGE}/yeastmine" "${STAGE}/yeastmine-bio-sources"
RSYNC_EXCLUDES=(
    --exclude='.git' --exclude='.gradle' --exclude='build/'
    --exclude='bin/' --exclude='out/' --exclude='*.log'
    --exclude='intermine-*.log' --exclude='.idea/' --exclude='.vscode/'
)
rsync -a --delete "${RSYNC_EXCLUDES[@]}" "${SRC_MINE}/" "${STAGE}/yeastmine/"
rsync -a --delete "${RSYNC_EXCLUDES[@]}" "${SRC_BIO}/"  "${STAGE}/yeastmine-bio-sources/"

SRC_HASH=$(find "${STAGE}" -type f -print0 | sort -z | xargs -0 sha256sum 2>/dev/null \
    | sha256sum | cut -c1-12)
HASH_TAG="src-${SRC_HASH}"
echo "==> Source hash: ${HASH_TAG}"

PLATFORM="linux/amd64"

if [[ ${PUSH} -eq 0 ]]; then
    docker buildx build --platform "${PLATFORM}" --load \
        -t "yeastmine-builder:${TAG}" -t "yeastmine-builder:${HASH_TAG}" "${HERE}"
    echo "==> --no-push set; skipping ECR push."
    docker images yeastmine-builder --format 'table {{.Repository}}:{{.Tag}}\t{{.Size}}\t{{.CreatedAt}}' | head -5
    exit 0
fi

echo "==> ECR login (${ECR_HOST})..."
aws ecr describe-repositories --region "${ECR_REGION}" --repository-names "${ECR_REPO}" >/dev/null 2>&1 \
    || aws ecr create-repository --region "${ECR_REGION}" --repository-name "${ECR_REPO}" >/dev/null
aws ecr get-login-password --region "${ECR_REGION}" \
    | docker login --username AWS --password-stdin "${ECR_HOST}"

docker buildx build --platform "${PLATFORM}" --push \
    -t "${ECR_HOST}/${ECR_REPO}:${TAG}" -t "${ECR_HOST}/${ECR_REPO}:${HASH_TAG}" "${HERE}"

echo "==> Done. Pull on AllianceMineDev:"
echo "    docker pull ${ECR_HOST}/${ECR_REPO}:${TAG} && docker tag ${ECR_HOST}/${ECR_REPO}:${TAG} yeastmine-builder:${TAG}"
```

- [ ] **Step 2: Make it executable**

Run: `chmod +x docker/yeastmine/scripts/build_and_push.sh`

- [ ] **Step 3: Clone the fork (one-time operator setup)**

Run:
```bash
mkdir -p ~/Projects/alliance/new_yeastmine
git clone https://github.com/yeastgenome/yeastmine.git ~/Projects/alliance/new_yeastmine/yeastmine
git clone https://github.com/yeastgenome/yeastmine-bio-sources.git ~/Projects/alliance/new_yeastmine/yeastmine-bio-sources
```
Expected: two repos cloned. (Task 5 edits `project.xml` in this fork.)

- [ ] **Step 4: Local build smoke test (verifies Task 1 + Task 2 together — M1)**

Run: `cd docker/yeastmine && scripts/build_and_push.sh --no-push 2>&1 | tail -30`
Expected: image `yeastmine-builder:latest` + `yeastmine-builder:src-<hash>` built; the build-time `./gradlew install` for bio-sources and yeastmine both complete without bintray or heap errors.

- [ ] **Step 5: Verify dbmodel assembles (M1 gate)**

Run:
```bash
docker run --rm yeastmine-builder:latest \
  bash -c 'cd /root/yeastmine && ./gradlew :dbmodel:assemble --no-daemon --console=plain' 2>&1 | tail -15
```
Expected: `BUILD SUCCESSFUL`. (Note: the entrypoint will try to reach RDS first; for this assemble-only check, override with `--entrypoint bash` if RDS is unreachable from the build host: `docker run --rm --entrypoint bash yeastmine-builder:latest -c 'cd /root/yeastmine && ./gradlew :dbmodel:assemble --no-daemon'`.)

- [ ] **Step 6: Commit**

```bash
git add docker/yeastmine/scripts/build_and_push.sh
git commit -m "yeastmine: add build_and_push.sh (stage fork, buildx amd64, ECR)"
```

---

## Task 3: Wire the SGD datasource (`db.sgd` + `SGD_DB_*`)

The five YeastMine database sources (`sgd`, `sgd-complementation-db`, `go-annotation-db`, `disease`, `sgd-complexes`) read from `db.sgd`, which the scaffold's properties template lacks.

**Files:**
- Modify: `docker/yeastmine/properties/yeastmine.properties.template` (after the User Profile Database block)
- Modify: `docker/yeastmine/docker-compose.yml` (environment block)
- Modify: `docker/yeastmine/.env.example`

- [ ] **Step 1: Add the `db.sgd` block to the properties template**

In `docker/yeastmine/properties/yeastmine.properties.template`, immediately after the `db.userprofile-production.*` block (before the `Project Configuration` section), insert:
```properties
# ============================================
# SGD Database (external, read-only) — feeds the 5 DB sources:
# sgd, sgd-complementation-db, go-annotation-db, disease, sgd-complexes
# ============================================
db.sgd.datasource.class=org.postgresql.ds.PGPoolingDataSource
db.sgd.datasource.dataSourceName=db.sgd
db.sgd.datasource.serverName=${SGD_DB_HOST}
db.sgd.datasource.databaseName=${SGD_DB_NAME}
db.sgd.datasource.user=${SGD_DB_USER}
db.sgd.datasource.password=${SGD_DB_PASSWORD}
db.sgd.datasource.maxConnections=10
db.sgd.datasource.portNumber=${SGD_DB_PORT}
db.sgd.driver=org.postgresql.Driver
db.sgd.platform=PostgreSQL
```

- [ ] **Step 2: Add `SGD_DB_*` to the compose environment**

In `docker/yeastmine/docker-compose.yml`, inside the `environment:` map (after the `Webapp` group), add:
```yaml
      # SGD Database (external, read-only) — the 5 DB sources read from here
      SGD_DB_HOST: ${SGD_DB_HOST:-}
      SGD_DB_NAME: ${SGD_DB_NAME:-sgd}
      SGD_DB_USER: ${SGD_DB_USER:-}
      SGD_DB_PASSWORD: ${SGD_DB_PASSWORD:-}
      SGD_DB_PORT: ${SGD_DB_PORT:-5432}
```

- [ ] **Step 3: Document `SGD_DB_*` in `.env.example`**

In `docker/yeastmine/.env.example`, add (after the RDS block):
```bash
# SGD Database (external, read-only) — REQUIRED for the 5 DB sources.
# Same instance AllianceMine uses. Credentials in .env only, never committed.
SGD_DB_HOST=www-rds-primary.yeastgenome.org
SGD_DB_NAME=sgd
SGD_DB_USER=
SGD_DB_PASSWORD=
SGD_DB_PORT=5432
```

- [ ] **Step 4: Verify the rendered properties contain a resolved `db.sgd` block**

After filling `.env` (RDS_PASSWORD + SGD_DB_USER/PASSWORD), run:
```bash
cd docker/yeastmine
docker compose run --rm yeastmine-builder \
  bash -c 'grep -A2 "db.sgd.datasource.serverName" /root/.intermine/yeastmine.properties'
```
Expected: `db.sgd.datasource.serverName=www-rds-primary.yeastgenome.org` (no literal `${SGD_DB_HOST}`).

- [ ] **Step 5: Verify SGD DB reachability from the build host (M2 gate)**

Run:
```bash
docker compose run --rm yeastmine-builder \
  bash -c 'PGPASSWORD="$SGD_DB_PASSWORD" pg_isready -h "$SGD_DB_HOST" -p "$SGD_DB_PORT" -U "$SGD_DB_USER"'
```
Expected: `... accepting connections`. If it times out, the build host has no route to `www-rds-primary.yeastgenome.org` — STOP and resolve networking before integration (this is the M2 risk in the design).

- [ ] **Step 6: Commit**

```bash
git add docker/yeastmine/properties/yeastmine.properties.template docker/yeastmine/docker-compose.yml docker/yeastmine/.env.example
git commit -m "yeastmine: wire db.sgd datasource + SGD_DB_* env for the 5 DB sources"
```

---

## Task 4: Add Solr URL derivation + fix compile ordering in entrypoint

Mirror flymine's entrypoint: derive `SOLR_INDEX_URL`/`SOLR_AUTOCOMPLETE_URL` and run compile *after* properties are rendered.

**Files:**
- Modify: `docker/yeastmine/entrypoint.sh`
- Modify: `docker/yeastmine/docker-compose.yml` (add `SOLR_*` env)
- Modify: `docker/yeastmine/.env.example`

- [ ] **Step 1: Add Solr URL derivation to `configure_properties()`**

In `docker/yeastmine/entrypoint.sh`, inside `configure_properties()`, before the `envsubst` call, add:
```bash
    # Solr URLs — multitenant Solr. Cores are `yeastmine-search` /
    # `yeastmine-autocomplete` (no release suffix). Used only once
    # create-search-index is re-enabled at deploy time (skipped this round).
    local solr_host="${SOLR_HOST:-172.31.59.87}"
    local solr_port="${SOLR_PORT:-8983}"
    export SOLR_INDEX_URL="${SOLR_INDEX_URL:-http://${solr_host}:${solr_port}/solr/yeastmine-search}"
    export SOLR_AUTOCOMPLETE_URL="${SOLR_AUTOCOMPLETE_URL:-http://${solr_host}:${solr_port}/solr/yeastmine-autocomplete}"
    echo "  Solr index URL:        ${SOLR_INDEX_URL}"
    echo "  Solr autocomplete URL: ${SOLR_AUTOCOMPLETE_URL}"
```

- [ ] **Step 2: Move `compile_if_needed` to after `setup_databases`**

In `docker/yeastmine/entrypoint.sh`, the current `Main` section calls `compile_if_needed` at the very top (line ~before `resolve_release`). Remove that early top-level `compile_if_needed` call, and in the `Main` section change the ordering so it reads:
```bash
wait_for_postgres
resolve_rc_number
construct_db_names
configure_properties
setup_databases

# Compile AFTER configure_properties: webapp/build.gradle reads webapp.port as
# an int at config time, so ${DEPLOY_PORT} must already be substituted.
compile_if_needed
```
(With the build-time compile from Task 1, `/root/.needs_compile` is absent and this is a no-op — but keeping the correct ordering protects the dev path where someone forces a recompile.)

- [ ] **Step 3: Add `SOLR_*` to compose + `.env.example`**

In `docker/yeastmine/docker-compose.yml` `environment:` add:
```yaml
      # Solr (external, on multitenant). Cores: yeastmine-search / yeastmine-autocomplete
      SOLR_HOST: ${SOLR_HOST:-172.31.59.87}
      SOLR_PORT: ${SOLR_PORT:-8983}
      SOLR_INDEX_URL: ${SOLR_INDEX_URL:-}
      SOLR_AUTOCOMPLETE_URL: ${SOLR_AUTOCOMPLETE_URL:-}
```
In `docker/yeastmine/.env.example` add:
```bash
# Solr (external, multitenant). Cores created at deploy time, not this round.
# SOLR_HOST=172.31.59.87
# SOLR_PORT=8983
```

- [ ] **Step 4: Verify the entrypoint still renders properties and starts a shell**

Run:
```bash
cd docker/yeastmine
docker compose run --rm yeastmine-builder \
  bash -c 'echo "$SOLR_INDEX_URL"; grep -c BUILD_PLACEHOLDER /root/.intermine/yeastmine.properties'
```
Expected: prints `http://172.31.59.87:8983/solr/yeastmine-search` and `0` (no leftover placeholders in the rendered file).

- [ ] **Step 5: Commit**

```bash
git add docker/yeastmine/entrypoint.sh docker/yeastmine/docker-compose.yml docker/yeastmine/.env.example
git commit -m "yeastmine: derive Solr URLs + compile-after-properties ordering"
```

---

## Task 5: Edit the fork's `project.xml` — paths + drop create-search-index

The fork is where path rewrites and the skipped postprocess live (Approach A). These edits are made in `~/Projects/alliance/new_yeastmine/yeastmine/project.xml` and baked in at the next `build_and_push.sh`.

**Files:**
- Modify: `~/Projects/alliance/new_yeastmine/yeastmine/project.xml`

- [ ] **Step 1: Rewrite file-source data paths `/data/intermine` → `/root/data/intermine`**

Run:
```bash
cd ~/Projects/alliance/new_yeastmine/yeastmine
cp project.xml project.xml.orig
sed -i.bak 's#"/data/intermine/#"/root/data/intermine/#g' project.xml
```

- [ ] **Step 2: Verify no `/data/intermine` paths remain and the `/root/data` ones are present**

Run: `grep -c '"/data/intermine/' project.xml; grep -c '"/root/data/intermine/' project.xml`
Expected: first count `0`; second count `> 0` (one per file source — ~14).

- [ ] **Step 3: Drop `create-search-index` from the `<post-processing>` section (design §9)**

Open `project.xml`, find the `<post-processing>` block, and delete the line:
```xml
    <post-process name="create-search-index"/>
```
(Leave every other `<post-process .../>` intact.) If the exact element name differs in this fork, grep for it first: `grep -n 'create-search-index' project.xml` and remove that single line.

- [ ] **Step 4: Verify it is gone**

Run: `grep -c 'create-search-index' project.xml`
Expected: `0`.

- [ ] **Step 5: Rebuild + push the image so the edited project.xml is baked in**

Run: `cd /Users/nuin/Projects/alliance/agr_intermine_builder/docker/yeastmine && scripts/build_and_push.sh --no-push`
Expected: build succeeds; `source/yeastmine/project.xml` inside the image now contains `/root/data/intermine` paths and no `create-search-index`.

> No repo commit here — the edits live in the operator's fork, not in
> `agr_intermine_builder`. Record the fork's commit SHA in the build log.

---

## Task 6: Create `extract_data.py` (S3 sync + ontology downloads)

A self-contained, YeastMine-specific fetcher. Unlike alliancemine's, there is no FMS or API-fetcher machinery — only an S3 sync of the SGD file-source subset and a handful of ontology downloads.

**Files:**
- Create: `docker/yeastmine/scripts/extract_data.py`

- [ ] **Step 1: Write the fetcher**

Create `docker/yeastmine/scripts/extract_data.py`:
```python
#!/usr/bin/env python3
"""YeastMine data extraction.

Stages the FILE sources referenced by yeastmine/project.xml into
/root/data/intermine/. The DATABASE sources (sgd, sgd-complementation-db,
go-annotation-db, disease, sgd-complexes) need no extraction — they read live
from db.sgd.

Two passes:
  1. S3 sync of the SGD subset from s3://agr-db-backups/alliancemine/intermine/
     (yeast_orthologs/*, protein-properties, protein-ntermini, gff, gff-utr,
     db-utr, psi-mi.obo, goslim_yeast.obo) — the same data AllianceMine stages.
  2. Direct downloads of the ontologies YeastMine wants in their canonical form
     (go-basic.obo, doid.obo, eco.obo, so.obo) into ontology/.

Use --skip-s3 / --skip-ontology to run only one pass.
"""
import argparse
import logging
import subprocess
import sys
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import urlretrieve

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("yeastmine-extract")

DATA_DIR = Path("/root/data")
INTERMINE_DIR = DATA_DIR / "intermine"

S3_DATA_BUCKET = "agr-db-backups"
S3_DATA_PREFIX = "alliancemine/intermine/"

# Ontologies YeastMine reads at the exact paths in project.xml (relative to
# /root/data/intermine/). Pulled from OBO Foundry canonical URLs.
ONTOLOGY_DOWNLOADS = [
    ("ontology/go-basic.obo", "http://purl.obolibrary.org/obo/go/go-basic.obo"),
    ("ontology/doid.obo", "http://purl.obolibrary.org/obo/doid.obo"),
    ("ontology/eco.obo", "http://purl.obolibrary.org/obo/eco.obo"),
    ("ontology/so.obo", "http://purl.obolibrary.org/obo/so.obo"),
]


def sync_s3() -> bool:
    """aws s3 cp the SGD/external subset into /root/data/intermine/."""
    INTERMINE_DIR.mkdir(parents=True, exist_ok=True)
    s3_uri = f"s3://{S3_DATA_BUCKET}/{S3_DATA_PREFIX}"
    logger.info(f"Syncing SGD/external data from {s3_uri} -> {INTERMINE_DIR}/ ...")
    try:
        result = subprocess.run(
            ["aws", "s3", "cp", s3_uri, str(INTERMINE_DIR), "--recursive"],
            capture_output=True, text=True, timeout=900,
        )
        if result.returncode != 0:
            logger.error(f"  S3 sync failed: {result.stderr.strip()}")
            return False
        files = sum(1 for _ in INTERMINE_DIR.rglob("*") if _.is_file())
        size = sum(f.stat().st_size for f in INTERMINE_DIR.rglob("*") if f.is_file())
        logger.info(f"  S3 sync complete: {files} files, {size / (1024**2):.1f} MB")
        return True
    except FileNotFoundError:
        logger.error("  aws CLI not found")
        return False
    except subprocess.TimeoutExpired:
        logger.error("  S3 sync timed out after 900s")
        return False


def download_ontologies() -> int:
    """Download the canonical-form ontologies. Returns failure count."""
    failures = 0
    for rel_path, url in ONTOLOGY_DOWNLOADS:
        out = INTERMINE_DIR / rel_path
        out.parent.mkdir(parents=True, exist_ok=True)
        logger.info(f"Downloading {url} -> {out}")
        try:
            urlretrieve(url, out)
            mb = out.stat().st_size / (1024 * 1024)
            logger.info(f"  OK ({mb:.1f} MB)")
        except (HTTPError, URLError, OSError) as e:
            logger.error(f"  FAILED: {e}")
            failures += 1
    return failures


def main() -> int:
    ap = argparse.ArgumentParser(description="YeastMine data extraction")
    ap.add_argument("--skip-s3", action="store_true", help="skip the S3 sync pass")
    ap.add_argument("--skip-ontology", action="store_true", help="skip ontology downloads")
    args = ap.parse_args()

    ok = True
    if not args.skip_s3:
        ok = sync_s3() and ok
    else:
        logger.info("Skipping S3 sync (--skip-s3)")

    if not args.skip_ontology:
        failures = download_ontologies()
        ok = (failures == 0) and ok
    else:
        logger.info("Skipping ontology downloads (--skip-ontology)")

    if not ok:
        logger.error("extract_data finished with errors")
        return 1
    logger.info("extract_data complete")
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 2: Make executable + ensure the Dockerfile COPYs it (already added in Task 1 Step 3)**

Run: `chmod +x docker/yeastmine/scripts/extract_data.py`
Confirm `docker/yeastmine/Dockerfile` contains `COPY scripts/extract_data.py /root/scripts/extract_data.py` (added in Task 1).

- [ ] **Step 3: Rebuild image, then run the fetcher (M3 gate)**

Run:
```bash
cd docker/yeastmine && scripts/build_and_push.sh --no-push
docker compose run --rm yeastmine-builder python3 /root/scripts/extract_data.py 2>&1 | tail -20
```
Expected: `S3 sync complete: N files`; four ontology `OK` lines; `extract_data complete`.

- [ ] **Step 4: Verify the staged tree matches the fork's project.xml paths**

Run:
```bash
docker compose run --rm yeastmine-builder bash -c '
  for p in gff gff-utr db-utr protein-properties protein-ntermini \
           yeast_orthologs ontology/go-basic.obo ontology/doid.obo \
           ontology/psi-mi.obo ontology/goslim_yeast.obo; do
    test -e "/root/data/intermine/$p" && echo "OK  $p" || echo "MISS $p"
  done'
```
Expected: all `OK`. Any `MISS` for an S3-sourced path means that file is not under the alliancemine S3 prefix — note it and add a targeted download (the design's §5b/§5c split). `MISS` for `psi-mi.obo`/`goslim_yeast.obo` would mean the S3 subset doesn't carry them; add them to `ONTOLOGY_DOWNLOADS` or copy from the alliancemine FMS set.

- [ ] **Step 5: Commit**

```bash
git add docker/yeastmine/scripts/extract_data.py
git commit -m "yeastmine: add extract_data.py (S3 sync + ontology downloads)"
```

---

## Task 7: Create `finalize_build.sh`

The post-integration wrapper: regenerate the object-store summary and rebuild the WAR. Modeled on flymine's, minus the data-patch SQL (none known for YeastMine yet — they are added as discovered, exactly as flymine's were).

**Files:**
- Create: `docker/yeastmine/scripts/finalize_build.sh`

- [ ] **Step 1: Write the script**

Create `docker/yeastmine/scripts/finalize_build.sh`:
```bash
#!/bin/bash
# finalize_build.sh — regenerate the object-store summary and rebuild the WAR
# after integration + postprocess. Yeast-specific SQL patches (if any are found
# during the first build) get added here as numbered patch_*.sql calls BEFORE
# the summary step, the same way docker/flymine/scripts/finalize_build.sh does.
#
# Usage:
#   finalize_build              # summariseObjectStore + WAR
#   finalize_build --skip-war   # summary only
#
# Reads DB connection from /root/.intermine/yeastmine.properties.
set -euo pipefail

SKIP_WAR=0
for a in "$@"; do
    case "$a" in
        --skip-war) SKIP_WAR=1 ;;
        --help|-h) sed -n '2,12p' "$0"; exit 0 ;;
    esac
done

PROPS=${PROPS:-/root/.intermine/yeastmine.properties}
PG_HOST=$(awk -F= '/^db.production.datasource.serverName/{print $2}' "$PROPS")
PG_DB=$(awk -F= '/^db.production.datasource.databaseName/{print $2}' "$PROPS")
PG_USER=$(awk -F= '/^db.production.datasource.user/{print $2}' "$PROPS")
PG_PASS=$(awk -F= '/^db.production.datasource.password/{print $2}' "$PROPS")
PG_PORT=${PG_PORT:-5432}

if [ -z "$PG_HOST" ] || [ -z "$PG_DB" ]; then
    echo "ERROR: could not read DB connection from $PROPS" >&2
    exit 1
fi
export PGPASSWORD="$PG_PASS"
echo "==> Target DB: ${PG_DB} on ${PG_HOST}"

# --- Future: yeast-specific patch_*.sql calls go here (before summarise) ---
# HERE=$(dirname "$(readlink -f "$0")")
# psql -h "$PG_HOST" -p "$PG_PORT" -U "$PG_USER" -d "$PG_DB" -v ON_ERROR_STOP=1 -f "$HERE/patch_xxx.sql"

cd /root/yeastmine

echo "==> :webapp:summariseObjectStore"
./gradlew :webapp:summariseObjectStore --no-daemon --console=plain

if [ $SKIP_WAR -eq 1 ]; then
    echo "==> --skip-war set; not building WAR."
    exit 0
fi

echo "==> :webapp:war"
./gradlew :webapp:war --no-daemon --console=plain
echo "==> Done. WAR at /root/yeastmine/webapp/build/libs/"
```

- [ ] **Step 2: Make executable + confirm Dockerfile COPY (added Task 1 Step 3)**

Run: `chmod +x docker/yeastmine/scripts/finalize_build.sh`
Confirm the Dockerfile has `COPY scripts/finalize_build.sh ...` and the `finalize_build` symlink (added in Task 1).

- [ ] **Step 3: Commit**

```bash
git add docker/yeastmine/scripts/finalize_build.sh
git commit -m "yeastmine: add finalize_build.sh (summariseObjectStore + WAR)"
```

---

## Task 8: End-to-end integration run-book (M2→M5)

Operational sequence run inside the container against RDS. Not committed code — record outcomes in the build log. **Rebuild + push the image first** so all prior tasks are baked in: `scripts/build_and_push.sh` (push to ECR, pull on AllianceMineDev).

- [ ] **Step 1: Sanity-check the build target before any builddb (CLAUDE.md rule)**

Run:
```bash
docker compose run --rm yeastmine-builder \
  bash -c 'grep db.production.datasource.databaseName /root/.intermine/yeastmine.properties'
```
Expected: `...databaseName=yeastmine_<release>_rc<N>` (a test RC DB, **not** a production name).

- [ ] **Step 2: Build the schema**

Run: `docker compose run --rm yeastmine-builder bash -c 'cd /root/yeastmine && ./gradlew builddb --no-daemon --console=plain' 2>&1 | tee /root/data/builddb.log`
Expected: `BUILD SUCCESSFUL`; the `yeastmine_<release>_rc<N>` DB now has the InterMine schema.

- [ ] **Step 3: Stage file data**

Run: `docker compose run --rm yeastmine-builder python3 /root/scripts/extract_data.py`
Expected: `extract_data complete` (verified in Task 6).

- [ ] **Step 4: Validate the SGD connection with a single DB source (M2 gate — canonical-converter risk)**

Run, in a persistent shell so the same container holds the integration:
```bash
docker compose run --rm yeastmine-builder bash -c '
  cd /root/yeastmine && ./gradlew integrate -Psource=sgd --no-daemon --console=plain' \
  2>&1 | tee /root/data/integrate_sgd.log
```
Expected: `BUILD SUCCESSFUL` and a non-trivial row count in the log (`Processing ... size of ...: N`, N > 0). A fast (<30s) "success" with no row counts means 0 rows loaded — STOP and investigate the canonical `SgdConverter` vs the reachable SGD schema (design §7) before running the full integration.

- [ ] **Step 5: Full integration, ordered, tee'd, resumable**

Run:
```bash
docker compose run --rm yeastmine-builder bash -c '
  cd /root/yeastmine && ./project_build -b -v localhost /root/data/dump/yeastmine' \
  2>&1 | tee /root/data/project_build.log
```
Expected: every source integrates; checkpoint DBs `yeastmine_<release>_rc<N>:<source>` appear on RDS. On failure, resume with the last-checkpoint flag: re-run appending `-l` (per project_build resume convention — never `-r`). Watch RDS storage (checkpoints are 30-60 GB each).

- [ ] **Step 6: Postprocess (create-search-index already removed from project.xml in Task 5)**

Run:
```bash
docker compose run --rm yeastmine-builder bash -c '
  cd /root/yeastmine && ./gradlew postprocess --no-daemon --console=plain' \
  2>&1 | tee /root/data/postprocess.log
```
Expected: `BUILD SUCCESSFUL`; no attempt to contact Solr (the `create-search-index` post-process is absent).

- [ ] **Step 7: Finalize — summary + WAR (M5 gate)**

Run:
```bash
docker compose run --rm yeastmine-builder finalize_build 2>&1 | tee /root/data/finalize.log
docker compose run --rm yeastmine-builder bash -c 'ls -lh /root/yeastmine/webapp/build/libs/*.war'
```
Expected: `summariseObjectStore` + `:webapp:war` both `BUILD SUCCESSFUL`; a `*.war` exists. **This is the end-to-end-on-RDS completion gate.**

- [ ] **Step 8: Record the result**

Append to `docker/yeastmine/README.md` "Known follow-ups" → mark the SGD-data-fetcher and project.xml items done; note the release built, RC number, row counts, and WAR size. Commit:
```bash
git add docker/yeastmine/README.md
git commit -m "yeastmine: record first end-to-end integration on RDS"
```

---

## Self-Review

**Spec coverage:**
- Design §3 layout → Tasks 1-7 (every file mapped). ✓
- §4 Approach A fork/COPY/ECR → Tasks 1, 2, 5. ✓
- §5a DB sources / §4 `db.sgd` gap → Task 3. ✓
- §5b/§5c file sources + ontologies → Task 6 (with a MISS-detection step for the S3/FMS split). ✓
- §6 build flow steps 1-8 → Task 8 run-book. ✓
- §9 skip `create-search-index` → Task 5 Step 3 + Task 6/8. ✓
- §7 risks: canonical-converter → Task 8 Step 4 gate; SGD reachability → Task 3 Step 5 gate; path edits → Task 5 Step 2 gate. ✓
- §8 milestones M1 (Task 2 Steps 4-5), M2 (Task 3 Step 5 + Task 8 Step 4), M3 (Task 6 Step 3), M4 (Task 8 Step 5), M5 (Task 8 Step 7). ✓

**Placeholder scan:** The only "future" marker is the patch-SQL hook in Task 7, which is intentional and matches flymine's discovered-empirically pattern — not a gap. No "TBD/handle edge cases/write tests for the above". ✓

**Type/name consistency:** `yeastmine-builder` image name, `db.sgd.*`, `SGD_DB_*`, `SOLR_INDEX_URL`/`SOLR_AUTOCOMPLETE_URL`, `/root/data/intermine`, `yeastmine-search`/`yeastmine-autocomplete` cores, `--skip-s3`/`--skip-ontology` — used consistently across tasks. ✓

**Known soft spot:** Task 5/Task 6 assume the fork's `project.xml` file-source paths are exactly `/data/intermine/...` and that the alliancemine S3 prefix carries every file source. Task 6 Step 4 detects any miss; if the fork uses a different base path, adjust the Step-1 `sed` accordingly. This is verified, not assumed-away.

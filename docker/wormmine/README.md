# WormMine Build Container

A build-only Docker image for WormMine + wormmine-bio-sources, modeled
on the AllianceMine builder pattern in `../alliancemine/` and the
FlyMine builder in `../flymine/`.

**Status:** Image-build skeleton. Data fetching, `project.xml` rewrites,
Solr, and Tomcat deploy are deferred to follow-on sessions. The image
as-is can compile dbmodel and the webapp WAR; it cannot run a full
integration without WormBase data wired into `/root/data/wormbase/`.

## What ships in the image

| Path | Source |
|---|---|
| `/root/wormmine/` | `git clone https://github.com/WormBase/WormMine.git` (branch via `WORMMINE_BRANCH`, default `im-298`) |
| `/root/wormmine-bio-sources/` | `git clone https://github.com/WormBase/wormmine-bio-sources.git` (branch via `WORMMINE_BIO_SOURCES_BRANCH`, default `im-293`) |
| `/root/wormmine/project_build` | `intermine-scripts` (matches AllianceMine/FlyMine pattern) |
| `/root/scripts/find_and_copy_wormbase_files.sh` | WormBase FTP/data fetcher (preserved from the previous unified container) |
| `/root/.intermine/wormmine.properties` | rendered from `properties/wormmine.properties.template` via `envsubst` at container start |

WormBase forks of WormMine and wormmine-bio-sources are used (not the
upstream `intermine/wormmine`), since WormBase carries fixes the
upstream lacks.

## Build

```bash
cd docker/wormmine
cp .env.example .env       # fill in RDS_PASSWORD, optionally WORMBASE_RELEASE
docker compose build       # ~5 min on a warm Maven cache
```

To pin to a specific WormBase release:
```bash
echo 'WORMMINE_BRANCH=im-299' >> .env
echo 'WORMMINE_BIO_SOURCES_BRANCH=im-294' >> .env
echo 'WORMBASE_RELEASE=WS299' >> .env
docker compose build --no-cache wormmine-builder
```

## Run

```bash
# Interactive shell (entrypoint sets up DBs first)
docker compose run --rm wormmine-builder bash

# Compile dbmodel only (proves the genomic model assembles)
docker compose run --rm wormmine-builder \
    bash -c 'cd /root/wormmine && ./gradlew :dbmodel:assemble --stacktrace'

# Build the WAR
docker compose run --rm wormmine-builder \
    bash -c 'cd /root/wormmine && ./gradlew :webapp:war --stacktrace'
# WAR lands in /root/wormmine/webapp/build/libs/webapp.war

# Fetch WormBase data files
docker compose run --rm wormmine-builder \
    /root/scripts/find_and_copy_wormbase_files.sh /root/data/wormbase
```

## What entrypoint.sh does

On every container start:
1. Compile `wormmine-bio-sources` and `wormmine` (first run only — marker
   file `/root/.needs_compile`)
2. Resolve `WORMBASE_RELEASE` (env var, or default to `YYYYMMDD`)
3. Auto-detect next `RC_NUMBER` for test builds (queries RDS for
   highest existing `wormmine_<release>_rcN`)
4. Construct DB names: `wormmine_{release}[_rcN]`, `wormmine_items`,
   `wormmine_userprofile{,_test,_rc<N>}`
5. Render `wormmine.properties` from the template via `envsubst`
6. Create the main / items / profile DBs on RDS if missing
7. Exec the user-supplied command (default: `bash`)

## What's intentionally NOT in this image (vs the previous unified container)

- **No Tomcat 9** — WAR is built here, deployed externally to the
  multitenant Tomcat host
- **No Solr 8.4.1** — Solr cores live on the multitenant Solr host
  (172.31.59.87:8983); image references their URLs in properties only
- **No internal `intermine` user** — single-user container, runs as root
- **No `server.xml` / `tomcat-users.xml`** — Tomcat config now lives
  with the multitenant Tomcat deployment

## What's intentionally NOT in this image (vs alliancemine/)

- **No FMS API resolution** — no Alliance FMS for WormBase data;
  operator sets `WORMBASE_RELEASE` explicitly
- **No SGD database connection** (no SGD source for WormMine)
- **No Solr core preflight** (Solr setup is multitenant-side)
- **No `extract_data.py` / `build_full.py` / `release.py`** — pipeline
  orchestration deferred to follow-on sessions
- **No `SgdConverter` patch** (SGD-specific)

## Differences from WormMine upstream

The image applies one runtime modification to the cloned WormMine
source tree:

- Appends `org.gradle.jvmargs=-Xmx48g -XX:+HeapDumpOnOutOfMemoryError`
  to `/root/wormmine/gradle.properties`. Without this the build risks
  OOM on real-sized WormBase data with the default ~1 GB heap.

That's the only patch.

## Image size

Target: under 1.5 GB after build. The Alpine + JDK 8 + Perl modules
base is shared in pattern with `alliancemine/` and `flymine/`. Source
repo clones add ~50 MB.

## Pushing to ECR (manual)

The repo's existing `scripts/auto-push-ecr.sh` references a Python
backend that doesn't exist on this branch. Manual push for now:

```bash
aws ecr get-login-password --region us-east-1 | \
  docker login --username AWS --password-stdin \
  100225593120.dkr.ecr.us-east-1.amazonaws.com

cd docker/wormmine
docker compose build

TAG="$(date +%Y%m%d)"   # or WS298, or $(git rev-parse --short HEAD)
docker tag wormmine-builder:latest \
  100225593120.dkr.ecr.us-east-1.amazonaws.com/agr_wormmine_builder:${TAG}
docker tag wormmine-builder:latest \
  100225593120.dkr.ecr.us-east-1.amazonaws.com/agr_wormmine_builder:latest
docker push 100225593120.dkr.ecr.us-east-1.amazonaws.com/agr_wormmine_builder:${TAG}
docker push 100225593120.dkr.ecr.us-east-1.amazonaws.com/agr_wormmine_builder:latest
```

If the ECR repo `agr_wormmine_builder` doesn't exist yet:
```bash
aws ecr create-repository --repository-name agr_wormmine_builder \
  --region us-east-1 --image-scanning-configuration scanOnPush=true
```

## See also

- `../alliancemine/README.md` — the full-pipeline reference implementation
- `../flymine/README.md` — sibling builder-only image (FlyMine)

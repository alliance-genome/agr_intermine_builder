# MouseMine Build Container

A build-only Docker image for MouseMine + mousemine-bio-sources, modeled on
the AllianceMine builder pattern in `../alliancemine/`.

**Status:** Image-build skeleton. Data fetching, `project.xml` rewrites
for AGR data paths, Solr, and Tomcat deploy are deferred to follow-on
sessions. The image as-is can compile dbmodel and the webapp WAR; it
cannot run a full integration without data wired into `/root/data/`.

## What ships in the image

| Path | Source |
|---|---|
| `/root/mousemine/` | `git clone https://github.com/intermine/mousemine.git` (branch via `MOUSEMINE_BRANCH`) |
| `/root/mousemine-bio-sources/` | `git clone https://github.com/intermine/mousemine-bio-sources.git` (branch via `MOUSEMINE_BIO_SOURCES_BRANCH`) |
| `/root/mousemine/project_build` | `intermine-scripts` (matches AllianceMine pattern) |
| `/root/.intermine/mousemine.properties` | rendered from `properties/mousemine.properties.template` via `envsubst` at container start |

The MouseMine repo's existing `project.xml` ships unmodified — it has 67
sources but no `<dump>` checkpoints and references `/micklem/data/`
paths that don't exist in this image. A future session will rewrite it
once a data fetcher is decided.

## Build

```bash
cd docker/mousemine
cp .env.example .env       # fill in RDS_PASSWORD, optionally MOUSEMINE_RELEASE
docker compose build       # ~5 min on a warm Maven cache
```

To pin the image to a specific upstream branch:
```bash
echo 'MOUSEMINE_BRANCH=some-feature-branch' >> .env
docker compose build --no-cache mousemine-builder
```

## Run

```bash
# Interactive shell (entrypoint sets up DBs first)
docker compose run --rm mousemine-builder bash

# Compile dbmodel only (proves the genomic model assembles)
docker compose run --rm mousemine-builder \
    bash -c 'cd /root/mousemine && ./gradlew :dbmodel:assemble --stacktrace'

# Build the WAR
docker compose run --rm mousemine-builder \
    bash -c 'cd /root/mousemine && ./gradlew :webapp:war --stacktrace'
# WAR lands in /root/mousemine/webapp/build/libs/webapp.war
```

## What entrypoint.sh does

On every container start:
1. Compile `mousemine-bio-sources` and `mousemine` (first run only — marker
   file `/root/.needs_compile`)
2. Resolve `MOUSEMINE_RELEASE` (env var, or default to `YYYYMMDD`)
3. Auto-detect next `RC_NUMBER` for test builds (queries RDS for
   highest existing `mousemine_<release>_rcN`)
4. Construct DB names: `mousemine_{release}[_rcN]`, `mousemine_items`,
   `mousemine_userprofile{,_test,_rc<N>}`
5. Render `mousemine.properties` from the template via `envsubst`
6. Create the main / items / profile DBs on RDS if missing
7. Exec the user-supplied command (default: `bash`)

## What's intentionally NOT in this image (vs alliancemine/)

- **No `extract_data.py`** — no FMS API for MouseMine; data fetcher TBD
- **No `build_full.py`** — pipeline orchestration deferred
- **No `create_solr_cores.py`** — MouseMine ships without Solr by default
- **No `release.py` / `deploy_war.py` / `promote_*.py`** — deployment
  pipeline TBD
- **No `SgdConverter` patch** — that's SGD-specific
- **No SGD database connection block** in the properties template
- **No `db.sgd.*` env vars** in `docker-compose.yml`

## Differences from MouseMine upstream

The image applies one runtime modification to the cloned MouseMine source
tree:

- Appends `org.gradle.jvmargs=-Xmx48g -XX:+HeapDumpOnOutOfMemoryError`
  to `/root/mousemine/gradle.properties`. The upstream file doesn't set
  this at all; without the append, the JVM starts with the default
  ~1 GB heap and OOMs on real-sized data.

That's the only patch.

## Image size

Target: under 1.5 GB after build. The bulk is the Alpine + JDK 8 + Perl
modules base layer, shared across mines. Source repo clones add ~50 MB.

## Pushing to ECR (manual)

The repo's existing `scripts/auto-push-ecr.sh` references
`uv run python src/main.py ecr push`, which targets a Python module
that lived on the now-deleted `from-scratch` branch. Until that helper
is reconstructed, push manually:

```bash
# 1. Authenticate to ECR
aws ecr get-login-password --region us-east-1 | \
  docker login --username AWS --password-stdin \
  100225593120.dkr.ecr.us-east-1.amazonaws.com

# 2. Build (if not already built locally)
cd docker/mousemine
docker compose build

# 3. Tag and push (pick a meaningful tag — release version, date, or git sha)
TAG="$(date +%Y%m%d)"   # or 52.2026.04, or $(git rev-parse --short HEAD)
docker tag mousemine-builder:latest \
  100225593120.dkr.ecr.us-east-1.amazonaws.com/agr_mousemine_builder:${TAG}
docker tag mousemine-builder:latest \
  100225593120.dkr.ecr.us-east-1.amazonaws.com/agr_mousemine_builder:latest
docker push 100225593120.dkr.ecr.us-east-1.amazonaws.com/agr_mousemine_builder:${TAG}
docker push 100225593120.dkr.ecr.us-east-1.amazonaws.com/agr_mousemine_builder:latest
```

If the ECR repository `agr_mousemine_builder` doesn't exist yet, create
it first (one-time, requires AWS console / IaC):
```bash
aws ecr create-repository --repository-name agr_mousemine_builder \
  --region us-east-1 --image-scanning-configuration scanOnPush=true
```

## See also

- `../alliancemine/README.md` — the reference implementation this is
  modeled on
- `../wormmine/README.md` — sibling all-in-one container (different
  pattern: Tomcat+Solr+Build in one image)
- `/Users/nuin/Projects/alliance/mousemine/CLAUDE.md` (in the MouseMine
  source repo) — full MouseMine architecture

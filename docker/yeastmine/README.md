# YeastMine Build Container

A build-only Docker image for YeastMine + yeastmine-bio-sources, modeled on
the AllianceMine builder pattern in `../alliancemine/` and the WormMine
builder in `../wormmine/`.

**Status:** Image-build skeleton. Data fetching, `project.xml` rewrites for
the SGD download paths, Solr, and Tomcat deploy are deferred to follow-on
sessions. The image as-is can compile dbmodel and the webapp WAR; it cannot
run a full integration without SGD source data wired into `/root/data/sgd/`.

## What ships in the image

| Path | Source |
|---|---|
| `/root/yeastmine/` | `git clone https://github.com/yeastgenome/yeastmine.git` (branch via `YEASTMINE_BRANCH`, default `master`) |
| `/root/yeastmine-bio-sources/` | `git clone https://github.com/yeastgenome/yeastmine-bio-sources.git` (branch via `YEASTMINE_BIO_SOURCES_BRANCH`, default `master`) |
| `/root/yeastmine/project_build` | `intermine-scripts` (matches AllianceMine / WormMine pattern, not the in-repo variant) |
| `/root/.intermine/yeastmine.properties` | rendered from `properties/yeastmine.properties.template` via `envsubst` at container start |

The canonical YeastMine repos are under `yeastgenome/` — `intermine/yeastmine`
on GitHub is a 404. Both repos last saw upstream commits in May 2024.

## Build

```bash
cd docker/yeastmine
cp .env.example .env       # fill in RDS_PASSWORD, optionally YEASTMINE_RELEASE
docker compose build       # ~5 min on a warm Maven cache
```

To pin the image to specific upstream branches:
```bash
echo 'YEASTMINE_BRANCH=R64-5-1' >> .env
echo 'YEASTMINE_BIO_SOURCES_BRANCH=R64-5-1' >> .env
docker compose build --no-cache yeastmine-builder
```

## Run

```bash
# Interactive shell (entrypoint sets up DBs first)
docker compose run --rm yeastmine-builder bash

# Compile dbmodel only (proves the genomic model assembles)
docker compose run --rm yeastmine-builder \
    bash -c 'cd /root/yeastmine && ./gradlew :dbmodel:assemble --stacktrace'

# Build the WAR
docker compose run --rm yeastmine-builder \
    bash -c 'cd /root/yeastmine && ./gradlew :webapp:war --stacktrace'
```

## Database conventions

Mirrors AllianceMine / WormMine naming:

| DB | Name | Lifetime |
|---|---|---|
| Main | `yeastmine_{release}_rc{N}` (test) or `yeastmine_{release}` (production) | per-build |
| Profile | `yeastmine_userprofile` (persists across releases); `yeastmine_userprofile_test` for test builds | long-lived |
| Items | `yeastmine_items` | per-integration |
| Checkpoints | `yeastmine_{release}_rc{N}:{source-name}` | created by `project_build` during integration |

Release strings have `.` and `-` characters converted to `_` for the DB name
(e.g. `R64-5-1` → `yeastmine_R64_5_1` and `yeastmine_R64_5_1_rc1`).

## Known follow-ups

| Item | Why |
|---|---|
| SGD data fetcher | The upstream `project.xml` references `/data/intermine/gff`, `/data/intermine/sgd/` etc. — paths that don't exist in this image. Need a fetcher script (probably an S3 sync similar to `docker/alliancemine/scripts/extract_data.py`) before integration can run. |
| Solr cores | YeastMine ships `keyword_search.properties` baked into the WAR with a hardcoded Solr URL. Must be patched at runtime same way AllianceMine does (see `docs/INTERMINE_TOMCAT_DOCKER.md`). |
| Tomcat deploy | WAR is built here, deployed externally to multitenant Tomcat. Pattern matches WormMine. |
| `superuser.account` placeholder | The default template renders `superuser@mail_account` which the InitialiserPlugin rejects with `Userprofile does not have a super user`. Override `SUPERUSER_ACCOUNT` in `.env` or fix the deployed WAR per `docs/PRODUCTION_CUTOVER_RC20.md` lessons (MouseMine hit this same trap). |
| Empty-theme trap | If the deployed WAR ends up with no `theme=` property set, JSPs emit `themes//theme.css` and inner pages render unstyled. Add `theme = yeastmine` (matches the theme dir bundled in WAR) post-deploy if needed. |

## Container resources

`docker-compose.yml` reserves 24G / limits 56G. JVM heap is set to `-Xmx48g`
in `GRADLE_OPTS`. The 8G headroom is for native memory used by gradle workers
and the JVM itself. YeastMine is smaller than AllianceMine in row count but
SGD's `chromosomal_feature.tab` + the Java `SgdConverter` are memory-heavy
during the SGD source pass.

## Cross-references

- `docker/alliancemine/README.md` — the canonical AGR mine builder this is
  modeled on.
- `docker/wormmine/README.md` — WormMine equivalent; same single-org pattern.
- `docker/mousemine/README.md` — MouseMine equivalent; older but still single-org.
- `docs/PRODUCTION_CUTOVER_RC20.md` — yeast template fixes shipped in rc20;
  the YeastMine container is what would let those fixes be regenerated from
  source rather than patched in `savedtemplatequery` at runtime.
- `docs/AMPLIFY_AND_NGINX_CLEANUP_2026_05_14.md` — related cleanup tracked
  alongside the yeastmine container work.

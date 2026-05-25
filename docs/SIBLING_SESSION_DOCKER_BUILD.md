# Sibling Claude session guide — Docker build for FlyMine / YeastMine

Audience: another Claude Code session whose user has asked to build
FlyMine or YeastMine. The build pipeline lives **here** in
`~/Projects/alliance/agr_intermine_builder/docker/<minename>/`. Do NOT
attempt host-side `./gradlew` in `new_flymine/` / `new_yeastmine/` —
that path has hit JCenter-sunset, DB-conn-timeout, and Java-DNS-cache
issues. The Docker pipeline in this repo wraps all of those.

Read this file first via `Read` on the absolute path:
`/Users/nuin/Projects/alliance/agr_intermine_builder/docs/SIDE_BY_SIDE_BUILD_GUIDE.md`.

## Where to work

```
~/Projects/alliance/agr_intermine_builder/docker/
├── alliancemine/        # reference impl, full build pipeline
├── mousemine/           # working build container, MGI sources
├── wormmine/            # working build container, WormBase sources
├── flymine/             # ← scaffold, no full integration yet
└── yeastmine/           # ← scaffold, no full integration yet
```

Each subdirectory is self-contained: `Dockerfile`, `docker-compose.yml`,
`entrypoint.sh`, `.env.example`, `properties/<mine>.properties.template`,
`README.md`. The README has the per-mine quickstart. **Read your mine's
README before doing anything.**

Status as of 2026-05-20:

| Mine | Image build | dbmodel compile | Integration run | Tomcat deploy |
|---|---|---|---|---|
| alliancemine | proven | proven | proven (rc20 in prod) | proven (ALB → 8086) |
| mousemine | proven | proven | proven (mgi-base etc.) | proven (mousemine.alliancegenome.org) |
| wormmine | proven | proven | external WormBase data wired in | proven (wormmine.alliancegenome.org) |
| **flymine** | proven | proven | **not attempted** | not attempted |
| **yeastmine** | proven | proven | **not attempted** | not attempted |

For flymine / yeastmine your job is: get dbmodel compile working in
the container, then drive at least one source integrate, then iterate.

## Build sequence

```bash
cd ~/Projects/alliance/agr_intermine_builder/docker/<mine>
cp .env.example .env
# Edit .env: set RDS_PASSWORD (ask user) + optionally <MINE>_RELEASE
docker compose build           # ~5 min cold, ~30s warm
docker compose run --rm <mine>-builder bash
```

Inside the container shell, the entrypoint already:

- Waited for RDS to be reachable
- Created `<mine>_<release>_rcN` + `<mine>_items` + `<mine>_userprofile_test` DBs
- Rendered `~/.intermine/<mine>.properties` from the envsubst template
- Compiled bio-sources + mine via `./gradlew install` on first run

From the shell:

```bash
# Validate model
cd /root/<mine> && ./gradlew :dbmodel:assemble --stacktrace

# Build the schema in RDS
./gradlew builddb --stacktrace

# Integrate one source as a smoke test (small, no external deps)
./gradlew --no-daemon --stacktrace integrate -Psource=so   # Sequence Ontology
# Or for flymine: integrate -Psource=update-publications etc.

# Build the WAR
cd /root/<mine> && ./gradlew :webapp:war --stacktrace
```

For a full build, use the `project_build` perl wrapper (installed by
the Dockerfile from `intermine-scripts`):

```bash
cd /root/<mine>
./project_build -E UTF8 -l <starting_source>     # -l = resume from last checkpoint
```

`-E UTF8` is required for RDS (RDS locale is `en_US.UTF-8`, default
`SQL_ASCII` will fail with `encoding does not match locale`).

## RDS vs local Postgres

The Docker pipeline targets RDS by default:
`intermine-postgres.cmnnhlso7wdi.us-east-1.rds.amazonaws.com`. You need
the password from the user (lives in their local `.env` files, not in
any repo). The entrypoint connects via `RDS_HOST` env var.

For a local-only smoke test against Postgres.app on the same laptop,
override in `.env`:

```
RDS_HOST=host.docker.internal
RDS_USER=postgres
RDS_PASSWORD=postgres
RDS_PORT=5432
```

You'll need Postgres.app's `pg_hba.conf` to accept connections from the
Docker bridge IP range (default is `127.0.0.1/32` only — won't work
from container). Easiest: open it to `0.0.0.0/0 trust` for dev,
listen_addresses = `*`, restart Postgres.app. (Don't push that config
anywhere. Don't run this on a machine that's exposed to a hostile
network.)

## What's broken in upstream you need to know

### Trap 1 — JCenter dead

YeastMine + FlyMine bio-sources `build.gradle` reference
`com.jfrog.bintray.gradle:gradle-bintray-plugin:1.8.0` and
`org.jfrog.buildinfo:build-info-extractor-gradle:4.6.2` on classpath.
Both lived only on JCenter (sunset 2021). Build fails with `Could not
find com.jfrog.bintray.gradle:...`

The Dockerfile in this repo does NOT patch these — bio-sources is
cloned fresh at image build, with the broken plugin refs. You'll hit
this on first integrate. Fix by editing the buildscript inside the
container:

```bash
# Inside container:
cd /root/<mine>-bio-sources
sed -i '/com.jfrog.bintray.gradle:gradle-bintray-plugin/d;/org.jfrog.buildinfo:build-info-extractor-gradle/d' build.gradle
sed -i "/apply plugin: 'com.jfrog.bintray'/d" build.gradle
./gradlew install
```

The proper fix is to bake this patch into the Dockerfile via a `RUN sed`
step after the clone. Once you've validated it works, send the patch
back to this session and we'll commit it.

### Trap 2 — Data paths in `project.xml`

Upstream `project.xml` hardcodes `src.data.dir` to paths that don't
exist in the container (e.g. `/data/intermine/gff`, `/micklem/data/`).
You need to either:

- Sync data from S3 (yeastmine subset: `aws s3 sync s3://agr-db-backups/alliancemine/intermine/ /root/data/intermine/`)
- Replace the paths in `project.xml` to point at where you mounted data
- Use the `data` volume in `docker-compose.yml` (binds `./data` →
  `/root/data` in container)

FlyMine's source list references FlyBase + Ensembl Fly data. Those
files are NOT in `s3://agr-db-backups/`. Either fetch from upstream
sources (likely slow, may be broken given 3.5y-old `project.xml`) or
trim the project.xml to a smaller working subset.

### Trap 3 — SGD external DB (yeastmine only)

YeastMine's `sgd` source reads from the live SGD Postgres at Stanford:
`www-rds-primary.yeastgenome.org`. Read-only creds are in
`docker/alliancemine/.env.example` (operator's `.env`):
- user: `webb`
- password: `readonly4alliance`
- db: `sgd`

These need to be in `.env` for the yeastmine container too. Set:

```
SGD_DB_HOST=www-rds-primary.yeastgenome.org
SGD_DB_NAME=sgd
SGD_DB_USER=webb
SGD_DB_PASSWORD=readonly4alliance
SGD_DB_PORT=5432
```

Then add the `db.sgd.*` block to the `properties/yeastmine.properties.template`
(see `docker/alliancemine/properties/alliancemine.properties.template`
for the format — it has the same block). Currently the yeastmine
template does NOT have this block; you need to add it before
`integrate -Psource=sgd` will work.

### Trap 4 — `os.query.max-time` cap

Already fixed in the template here. Don't worry about it unless
enrichment widgets fail post-deploy.

### Trap 5 — Theme + CDN + superuser placeholders

Already fixed in the template here. Don't worry unless the deployed
webapp shows blank page or unstyled inner pages.

## When you finish

If you get a successful integrate of even one source, write up:

- Branch / SHA pinned in `.env` (the upstream HEAD you built against)
- Sources integrated + their row counts
- Any patches you applied inside the container (and whether they should
  be baked into the Dockerfile)
- Time spent + remaining unknowns

Push branch / SHA notes to this session so we can commit the Dockerfile
patches centrally. **DO NOT commit to this repo from your session.**

## Coordinating with this session

Both Claude sessions share the same machine. Conflicts to avoid:

| Resource | Convention |
|---|---|
| Docker container names | `flymine-builder`, `yeastmine-builder`. Don't `docker rm` containers you didn't create. |
| Docker images | `flymine-builder:latest`, `yeastmine-builder:latest`. Multiple `docker compose build` runs OK. |
| RDS production DBs | `alliancemine_*`, `mousemine_*`, `wormmine_*` are prod. Don't touch. Your build creates `flymine_*` / `yeastmine_*` DBs — own them. |
| Local Postgres.app DBs | `alliancemine`, `items-alliancemine`, `userprofile-alliancemine` are owned by `~/Projects/alliance/new_alliancemine` sessions. |
| `~/.m2/repository/org/intermine/` | Bio-source JARs. Multiple mines publish overlapping subsets — last writer wins; installs are idempotent. Don't `rm -rf ~/.m2`. |
| AWS infra | Don't create / modify TGs, listener rules, R53 records, security groups, or restart prod containers from your session. Ask user; user routes to this session if AWS changes needed. |
| Memory + commits in this repo | Owned by this session. If you want a doc updated, ask user. |

## Useful cross-references in this repo

| File | Purpose |
|---|---|
| `CLAUDE.md` | Top-level orientation for the Docker build pipeline |
| `docker/<mine>/README.md` | Per-mine quickstart |
| `docker/alliancemine/properties/alliancemine.properties.template` | Reference for what a working template looks like — all 5 traps fixed |
| `docs/PRODUCTION_CUTOVER_RC20.md` | AllianceMine rc20 cutover, template fix list |
| `docs/MOUSEMINE_PUBLIC_URL_RELEASE_2026_05_20.md` | Most recent public-URL release, full trap catalog |
| `docs/MOUSEMINE_ENRICHMENT_WIDGET_FIX_2026_05_15.md` | `os.query.max-time` fix story |
| `docs/WORMMINE_MULTITENANT_SETUP.md` | WormMine release pattern (note: its `webapp.baseurl` convention is wrong — see Mousemine doc Trap 3) |
| `docs/RELEASE_PROCESS.md` | End-to-end release workflow |
| `docs/BUILD_TROUBLESHOOTING.md` | Common errors and fixes |

## Escalate to user (and via user to this session) when

- A Dockerfile patch worked and should be committed
- Upstream branch / SHA pinned for reproducibility
- A new template fix needed in `properties/<mine>.properties.template`
- AWS infra change requested (TG / listener / R53 / SG / container restart)
- The build is ready for a public URL release

That's it. Read your mine's README, build the image, get past the JCenter
trap, and report back with a row count.

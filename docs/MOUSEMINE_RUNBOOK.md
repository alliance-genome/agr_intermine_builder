# MouseMine Runbook — Build, Manage, Update

Short operator reference. For deep dives see `MOUSEMINE_BUILD_GUIDE.md`, `JOB_AID_MOUSEMINE.md`, and the incident/fix docs (`MOUSEMINE_RC3_BUILD_2026_06_16.md`, `MOUSEMINE_CDN_FIX_2026_07_01.md`).

## Where things live

| Thing | Location |
|---|---|
| **Build container** | `mousemine` on **AllianceMineDev** `172.31.60.197` (Ant / InterMine 1.x, Java 8/11) |
| **Runtime container** | `mousemine-1x` on **multitenant** `172.31.59.87`, port **8084**, image `…/agr_mousemine:runtime-1x` |
| **Public URL** | `https://mousemine.alliancegenome.org/mousemine/` |
| **RDS** | `intermine-postgres.cmnnhlso7wdi.us-east-1.rds.amazonaws.com` — prod DB `mousemine_rc2`; profile `mousemine_userprofile` (persistent) |
| **Source/ETL data** | build container `/data/etl_output/…` (from `update.tar.gz`); project `/intermine/mousemine` |
| **Keyword search** | legacy **Lucene** (not Solr); index bind-mounted `/home/ec2-user/mousemine-data/keyword_search_index` |

SSH: `ssh -i ~/.ssh/AGR-ssl3.pem ec2-user@<host>`. RDS password lives in `.env` only — never commit it.

---

## Build a new release

Run inside the `mousemine` container on AllianceMineDev. MouseMine is **Ant-based** (not Gradle).

```bash
docker exec -it mousemine bash

# 1. new DB on RDS
psql … -c "CREATE DATABASE mousemine_rc<N> ENCODING 'UTF8' TEMPLATE template0"

# 2. point properties at it
sed -i 's/mousemine_rc<OLD>/mousemine_rc<N>/g' /root/.intermine/mousemine.properties

# 3. schema — from dbmodel/, NO -Drelease flag
cd /intermine/mousemine/dbmodel && ant build-db          # ~227 tables

# 4. integrate all sources (~hours; mgi-base alone ~12h)
cd /intermine/mousemine
/intermine/bio/scripts/project_build -b -E UTF8 localhost /data/dump/mousemine_rc<N>
#   -b build-db first · -E UTF8 REQUIRED for RDS · resume: -l · start-at: -a <source>-

# 5. postprocess (all 10)
/intermine/bio/scripts/project_build -E UTF8 -a do-sources- localhost /data/dump/mousemine_rc<N>

# 6. WAR (no `war` target — run webapp default)
cd /intermine/mousemine/webapp && ant default            # -> webapp/dist/mousemine-webapp.war
```

**Known build gotchas** (all fixed once, will recur on a clean image — see `MOUSEMINE_RC3_BUILD_2026_06_16.md`):
- **`0x00` UTF-8 COPY error** → patch `PostgresDataOutputStream.writeLargeUTF` (strip nulls + `getBytes(UTF_8)`); **patch all 3 copies** of `intermine-objectstore.jar`. Do NOT pre-strip source files (corrupts XML).
- **mgi-base duplicate items** → add `<property name="ignore.duplicates" value="true"/>` to the source.
- **mgi-base field conflict** → add `BioEntity.name = mgi-base, *` to `genomic_priorities.properties` (all 3 copies). Don't also add `Gene.name`/`Chromosome.name` (throws "multiple priorities").
- **Skip** `interpro`, `protein2ipr`, `update-publications` (converter bugs / ProxyReference).
- **RDS storage**: each `project_build` checkpoint is a full DB copy (~150–250 GB). Ensure RDS free ≥ 2× final DB size; watch `FreeStorageSpace` (storage-full takes ALL mines down).
- `ant build-db` must run **without** `-Drelease` (else it looks for `mousemine.properties.1.8`).

---

## Manage the running mine

```bash
# on multitenant 172.31.59.87
docker restart mousemine-1x            # safe — Lucene index is bind-mounted, no re-extract
docker logs --tail 50 mousemine-1x
docker stats --no-stream mousemine-1x  # CPU/mem
```

Common issues:
- **504 / "internal error" / queries hang, site up** → usually the JVM is wedged (OOM/GC or a stale pool). `docker restart mousemine-1x`. Check heap: `docker exec mousemine-1x sh -c 'ps -eo args | grep -o "\-Xmx[0-9]*[gm]"'`.
- **Templates page blank / "Can't find variable: jQuery"** → CDN misconfig. `head.cdn.location` must be **`https://mousemine.alliancegenome.org/cdn`** (public HTTPS), NOT `http://172.31.59.87:8888` (mixed-content/private-IP). File: `…/mousemine/WEB-INF/global.web.properties`. See `MOUSEMINE_CDN_FIX_2026_07_01.md`.
- **Search slow/empty after restart** → Lucene warms on first search; run one query and wait (self-clears).
- **Change heap without recreating** (preserves the cp'd WAR): write `/usr/local/tomcat/bin/setenv.sh` with `export JAVA_OPTS="… -Xmx<N>g -Xms2g"`, then `docker restart` (never `docker rm` — the WAR is not baked/mounted and would be lost).
- **Runaway query backstop**: `os.query.max-time` in `default.intermine.properties` (set to `3600000` = 1h).

⚠️ **Runtime edits in the container (CDN, setenv.sh, properties) survive `docker restart` but REVERT on recreate / image re-pull.** The permanent home is the image/WAR.

---

## Update / cut over to a new release

After a successful build (WAR at `mousemine:/intermine/mousemine/webapp/dist/mousemine-webapp.war`):

```bash
# 1. copy WAR build-host -> multitenant (relay via laptop; dev host has no key to multitenant)
docker cp mousemine:/intermine/mousemine/webapp/dist/mousemine-webapp.war /tmp/mousemine.war
scp … dev:/tmp/mousemine.war ./ ; scp … ./mousemine.war multitenant:/home/ec2-user/mine-wars/mousemine.war

# 2. point the runtime container's properties at the new DB (mousemine_rc<N>), fix head.cdn.location,
#    set -Xmx via setenv.sh, deploy the new WAR
# 3. docker restart mousemine-1x  (or recreate with the WAR bind-mounted — preferred, avoids cp fragility)

# 4. verify
curl -s -o /dev/null -w "%{http_code}\n" https://mousemine.alliancegenome.org/mousemine/service/version
#   + begin.do body has no "internal error"; run a query; warm keyword search
```

Keep the previous prod DB (`mousemine_rc<OLD>`) as rollback until the new one is verified ≥ a few days, then drop it to reclaim RDS space.

**Current status:** `mousemine_rc3` is built (259 GB, 1.56M genes) but **NOT cut over** — `mousemine_rc2` still serves production.

---

## Quick reference

| Task | Command |
|---|---|
| Enter build container | `docker exec -it mousemine bash` (dev host) |
| Restart runtime | `docker restart mousemine-1x` (multitenant) |
| Resume a failed build | `project_build -l -E UTF8 localhost /data/dump/mousemine_rc<N>` |
| DB size | `psql … -c "SELECT pg_size_pretty(pg_database_size('mousemine_rc<N>'))"` |
| RDS free space | CloudWatch `FreeStorageSpace` on `intermine-postgres` |
| Public health | `curl https://mousemine.alliancegenome.org/mousemine/service/version` |

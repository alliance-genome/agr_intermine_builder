# Runtime Container Backup to ECR

How to snapshot a deployed mine container (Tomcat + WAR + patched configs) into ECR so we can restore in seconds after a disaster.

## Why

`docker commit` captures the container's filesystem — including:

- Deployed WAR (`/usr/local/tomcat/webapps/<mine>.war` and exploded dir)
- Tomcat `conf/server.xml`, `context.xml`, manager `web.xml` (RemoteIpValve, manager auth, upload limits)
- `/etc/hosts` lines (e.g. `agr.stage.alliancemine.solr.server`)
- Any in-place patches applied after deploy

It does **not** capture:

- Container runtime flags (port maps, `--add-host`, env vars, memory limits)
- External state (RDS, Solr cores, Caddy CDN)

So: snapshot the FS to ECR, document the run flags here, restore = pull + `docker run` with the recorded flags.

## ECR repos

| Repo | Tag pattern | Contents |
|------|-------------|----------|
| `agr_alliancemine` | `runtime-<version>` (rolling) | Deployed Tomcat with WAR + patches |
| `agr_alliancemine` | `runtime-<version>-<YYYYMMDD-HHMM>` | Point-in-time snapshot |
| `agr_alliancemine` | `<version>` (e.g. `9.0.0`) | **Builder** image (do not confuse) |

Same convention applies to `agr_wormmine`, `agr_mousemine`, etc. when we snapshot those.

## Snapshot procedure

Run on the host where the container lives (multitenant, `172.31.59.87`).

```bash
CONTAINER=alliancemine-9.0.0
VERSION=9.0.0
REPO=100225593120.dkr.ecr.us-east-1.amazonaws.com/agr_alliancemine
STAMP=$(date +%Y%m%d-%H%M)

docker commit -m "${CONTAINER} snapshot" "$CONTAINER" "$REPO:runtime-$VERSION"
docker tag    "$REPO:runtime-$VERSION" "$REPO:runtime-$VERSION-$STAMP"

aws ecr get-login-password --region us-east-1 \
  | docker login --username AWS --password-stdin 100225593120.dkr.ecr.us-east-1.amazonaws.com

docker push "$REPO:runtime-$VERSION"
docker push "$REPO:runtime-$VERSION-$STAMP"
```

Image size for AllianceMine 9.0.0: ~696 MB (Tomcat 9.0.112 + JDK 11 + 132 MB WAR).

## AllianceMine 9.0.0 — recorded run flags (snapshot 2026-05-01 19:30 UTC)

```bash
docker pull 100225593120.dkr.ecr.us-east-1.amazonaws.com/agr_alliancemine:runtime-9.0.0

docker run -d \
  --name alliancemine-9.0.0 \
  -p 8082:8080 \
  --add-host agr.stage.alliancemine.solr.server:172.17.0.1 \
  -e JAVA_OPTS="-Dorg.apache.el.parser.SKIP_IDENTIFIER_CHECK=true -Xmx4g -Xms2g" \
  100225593120.dkr.ecr.us-east-1.amazonaws.com/agr_alliancemine:runtime-9.0.0
```

Externals the running container depends on:

| Resource | Value |
|---|---|
| Production DB | `alliancemine_9_0_0_rc18` on `intermine-postgres` RDS |
| Profile DB | `alliancemine_userprofile` (shared, persistent) |
| Solr search core | `http://172.31.59.87:8983/solr/alliancemine-search-9.0.0` |
| Solr autocomplete core | `http://172.31.59.87:8983/solr/alliancemine-autocomplete-9.0.0` |
| `webapp.deploy.url` baked into WAR | `http://172.31.59.87:8082` |
| Tomcat manager creds | `manager` / `manager` |

DB names + Solr URLs are baked into the WAR (`web.properties`, `intermine.properties`, `keyword_search.properties`, `objectstoresummary.config.properties`). They're already correct in the snapshot — re-running from this image needs no property patches.

## Verify after restore

```bash
# Tomcat reachable
curl -sS -o /dev/null -w "%{http_code}\n" http://localhost:8082/

# Manager reachable + creds work
curl -sS -u manager:manager http://localhost:8082/manager/text/list | head

# Webapp deployed and serving
curl -sS -o /dev/null -w "%{http_code}\n" http://localhost:8082/alliancemine/service/version
```

If all three return 200, restore is complete.

## Cadence

- **Before each property/WAR change** to a deployed container — snapshot first as rollback insurance.
- **After confirmed-good deploy** — overwrite `runtime-<version>` rolling tag, keep a fresh dated tag.
- **Prune dated tags** older than 90 days, retain at minimum the 2 most recent.

## Related disasters

- 2026-04-30: `docker system prune -a -f` deleted alliancemine + wormmine containers because they had Exited from disk-full. Had no ECR snapshot, had to rebuild WAR from scratch and re-apply all patches manually. See `docs/INCIDENT_2026_04_30_to_05_01.md`.
- This doc exists so that never happens again.

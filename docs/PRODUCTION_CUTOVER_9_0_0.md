# AllianceMine 9.0.0 Production Cutover

Date: 2026-05-01
Operator: pnuin
Outcome: live at `https://alliancemine.alliancegenome.org`

## Summary

Promoted AllianceMine 9.0.0 to production by swapping the ALB target from
`172.31.59.87:8080` (old 8.3.0 container, dead from earlier disk-full incident)
to `172.31.59.87:8082` (new 9.0.0 container).

No new target group, no new listener rule. Just deregister + register inside
the existing TG `alliancemine-multitenant`.

## Pre-cutover state

| Component | Value |
|---|---|
| ALB | `alliancemine-lb` (`alliancemine-lb-309443304.us-east-1.elb.amazonaws.com`) |
| Listener | HTTPS:443 |
| Rule priority 250 | host-header `alliancemine.alliancegenome.org` → TG `alliancemine-multitenant` |
| Target group | `alliancemine-multitenant` (port attr 8080, hc path `/alliancemine/service/version`, codes 200, hc port `traffic-port`) |
| Old target | `172.31.59.87:8080` — UNHEALTHY (404 from old container that was empty after `docker system prune` on 2026-04-30) |

## Build & deploy of 9.0.0 container

Container `alliancemine-9.0.0` was built piecemeal during 2026-05-01 recovery:

- Image base: `intermine-tomcat:latest` (Tomcat 9.0.112, JDK 11)
- WAR: `alliancemine.war` (132 MB), built on AllianceMineDev from
  `~/alliancemine` source pointing at `alliancemine_9_0_0_rc18` + `alliancemine_userprofile`
  + Solr `-9.0.0` cores
- Patches inside container:
  - `server.xml` — RemoteIpValve (trusts 10/8, 172.16/12, 192.168/16, 127/8)
  - manager `context.xml` — RemoteAddrValve removed (allow remote deploy)
  - manager `web.xml` — `<max-file-size>524288000</max-file-size>` (500 MB)
  - `/etc/hosts` — `172.17.0.1 agr.stage.alliancemine.solr.server`
- Run flags:
  ```
  -p 8082:8080
  --add-host agr.stage.alliancemine.solr.server:172.17.0.1
  -e JAVA_OPTS="-Dorg.apache.el.parser.SKIP_IDENTIFIER_CHECK=true -Xmx4g -Xms2g"
  ```
- Snapshot to ECR before cutover: `agr_alliancemine:runtime-9.0.0` +
  `runtime-9.0.0-20260501-1930` (see `docs/RUNTIME_CONTAINER_BACKUP.md`)

## Bag-upgrade deadlock during init (resolved)

On startup, `InitialiserPlugin.initSearch` runs `UpgradeBagList` for the
superuser account. The thread acquires the `PrecomputedTableManager` HashMap
lock, runs `synchroniseWithDatabase` (a JDBC query), and the JDBC socket
hung indefinitely on `socketRead0` — RDS showed zero active queries while
the JVM was waiting for a response that would never arrive (likely a
half-closed TCP after the bag upgrade query finished).

All Tomcat threads queued behind that lock. Webapp 100% blocked.

**Fix applied:** `pg_terminate_backend` on every JDBC connection from the
container to `alliancemine_9_0_0_rc18`. The held conn died, JVM threw
SQLException, lock released, all queued threads ran, Hikari rebuilt the
pool with fresh conns.

The bag-upgrade thread itself died from the SQLException, leaving 2 of
22 bags orphaned in `intermine_state='UPGRADING'`. Flipped them back to
`NOT_CURRENT` in `alliancemine_userprofile` so user-driven access
re-triggers per-bag upgrade (no global init lock).

Pre-modification S3 backup of `alliancemine_userprofile` taken at
`s3://agr-db-backups/db-backups/alliancemine_userprofile/2026-05-01/alliancemine_userprofile.20260501T194544Z.dump`.

## Cutover commands

```bash
TG=arn:aws:elasticloadbalancing:us-east-1:100225593120:targetgroup/alliancemine-multitenant/9c6cdef38cbc7e6b

aws elbv2 register-targets --region us-east-1 \
  --target-group-arn $TG \
  --targets Id=172.31.59.87,Port=8082

aws elbv2 deregister-targets --region us-east-1 \
  --target-group-arn $TG \
  --targets Id=172.31.59.87,Port=8080
```

## Verification

```
$ curl -sS -H "Host: alliancemine.alliancegenome.org" \
    https://alliancemine-lb-309443304.us-east-1.elb.amazonaws.com/alliancemine/service/version
35
```

ALB target health: `172.31.59.87:8082` → `healthy` after ~30 s.
8080 entered `draining` (default 300 s).

## Rollback

```bash
aws elbv2 register-targets   --target-group-arn $TG --targets Id=172.31.59.87,Port=8080
aws elbv2 deregister-targets --target-group-arn $TG --targets Id=172.31.59.87,Port=8082
```

(8080 currently has no working webapp behind it — rollback would also
need a working 8.3.0 container restored. Most realistic recovery is to
fix forward in 9.0.0.)

## Known issues (post-cutover)

1. **`webapp.baseurl=http://localhost:8090` baked into WAR.** Absolute
   URLs in REST responses (e.g. links to `portal.do`) will be broken
   for clients that follow them. Needs patching to
   `https://alliancemine.alliancegenome.org`, then re-snapshot ECR.
2. **2 bags (`ALL_Yeast_Genes`, `ALL_Verified_Uncharacterized_Dubious_ORFs`)
   in NOT_CURRENT state for superuser.** Will re-upgrade lazily when
   accessed. Each is a 6-7k gene resolver against rc18 — expect ~30 s
   on first access.
3. **ALB rule priority 50/51 bot-block** is still tied to specific
   source IPs from the 2026-04-30 incident. Replace with WAF rule
   filtering by `QUERY_STRING` length (see `docs/WAF_REQUEST_FOR_COLLEAGUE.md`).
4. **Old 8.3.0 archive DB.** `alliancemine_8_3_0` should remain on RDS
   for ≥1 week as rollback insurance. Do not drop until 2026-05-08.
5. **`alliancemine_userprofile` was modified manually** (orphan-flip).
   Pre-modification dump in S3.

## Open follow-ups (planning needed)

See `docs/POST_9_0_0_PLANNING.md`.

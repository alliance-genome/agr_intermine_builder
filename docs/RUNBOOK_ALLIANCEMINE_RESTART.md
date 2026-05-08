# AllianceMine 9.0.0 Restart Runbook

Operational procedure for restarting the alliancemine-9.0.0 Tomcat container
on multitenant. Avoids the bag-upgrade deadlock that bites every restart.

## When to use

Any planned restart of `alliancemine-9.0.0` on multitenant
(`172.31.59.87:8082`):
- After in-place property patches (e.g. `webapp.baseurl`)
- After OS / Docker upgrades
- After WAR redeploys
- Recovery from crash

## Why this runbook exists

Every Tomcat restart re-runs `InitialiserPlugin.initSearch` →
`UpgradeBagList` for the superuser's bags. The bag upgrade thread holds
the `PrecomputedTableManager` HashMap lock while doing a JDBC query that
can hang on a half-closed TCP socket. **All Tomcat request threads queue
behind that lock.** Webapp is dead until the deadlock breaks.

Reproduced on:
- 2026-05-01 (initial 9.0.0 cutover)
- 2026-05-04 (`webapp.baseurl` patch restart)

Until Tier 2 JDBC keepalive fix lands
(`tcpKeepAlive=true&socketTimeout=300`), every restart needs a manual
`pg_terminate_backend` kick.

## Procedure

### 1. Pre-restart — capture state

```bash
ssh multitenant
docker exec alliancemine-9.0.0 grep webapp.baseurl \
  /usr/local/tomcat/webapps/alliancemine/WEB-INF/web.properties
# expect: https://alliancemine.alliancegenome.org
# if "localhost:8090" — patches were lost. Restore from ECR.
```

### 2. Snapshot to ECR (rollback insurance)

From your laptop:
```bash
ssh multitenant '/tmp/backup_runtimes.sh -c alliancemine-9.0.0'
# (or scp scripts/backup_multitenant_runtimes.sh first)
```

Confirms a usable rollback image before risking the restart.

### 3. Restart

```bash
ssh multitenant 'docker restart alliancemine-9.0.0'
```

### 4. Wait for Tomcat init, then KICK the deadlock

Tomcat reaches a hung state ~30-60s after restart, where:
- Container is `Up`
- main thread is in `Catalina.await()` (Tomcat itself ready)
- ALL Hikari conns to alliancemine_9_0_0_rc18 are `idle`
- ALB health check fails (UNHEALTHY)
- `localhost.<date>.log` stops appending

Symptom that says "kick now":

```bash
ssh AllianceMineDev "PGPASSWORD=\$RDS_PASSWORD \
  psql -h intermine-postgres.cmnnhlso7wdi.us-east-1.rds.amazonaws.com -U postgres -d postgres -c \
  \"SELECT state, count(*) FROM pg_stat_activity \
     WHERE datname='alliancemine_9_0_0_rc18' AND application_name='PostgreSQL JDBC Driver' \
     GROUP BY state;\""
# 20 idle, 0 active for >2 min = deadlocked
```

Kick:

```bash
ssh AllianceMineDev "PGPASSWORD=\$RDS_PASSWORD \
  psql -h intermine-postgres.cmnnhlso7wdi.us-east-1.rds.amazonaws.com -U postgres -d postgres -c \
  \"SELECT count(*) FROM (SELECT pg_terminate_backend(pid) FROM pg_stat_activity \
     WHERE datname='alliancemine_9_0_0_rc18' \
       AND application_name='PostgreSQL JDBC Driver') t;\""
# expect: 20
```

JVM throws SQLException, lock releases, Hikari rebuilds pool. Tomcat
finishes deployment within 30-60s.

### 5. Verify recovery

```bash
ssh multitenant 'aws elbv2 describe-target-health \
  --region us-east-1 \
  --target-group-arn arn:aws:elasticloadbalancing:us-east-1:100225593120:targetgroup/alliancemine-multitenant/9c6cdef38cbc7e6b \
  --query "TargetHealthDescriptions[*].TargetHealth.State" --output text'
# expect: healthy
```

Internal smoke (use raw TCP since hooks block curl/wget here):
```bash
ssh multitenant 'docker exec alliancemine-9.0.0 bash -c \
  "exec 3<>/dev/tcp/localhost/8080 && \
   echo -e \"GET /alliancemine/service/version HTTP/1.1\\r\\nHost: alliancemine.alliancegenome.org\\r\\nConnection: close\\r\\n\\r\\n\" >&3 && \
   head -c 200 <&3"'
# expect: HTTP/1.1 200
```

External:
```bash
curl -sS https://alliancemine.alliancegenome.org/alliancemine/service/version
# expect: integer body, e.g. 35
```

### 6. Watch for stale-session noise

For ~30 min post-restart, expect a small number of:
```
java.lang.IllegalStateException: getAttribute: Session already invalidated
```

Benign — clients with JSESSIONIDs from pre-restart. Self-clears as
cookies refresh. **Do not page on this.**

### 7. Re-snapshot to ECR

If the restart was for an in-place patch (e.g. `webapp.baseurl`),
snapshot the post-restart state so the patch is captured:

```bash
ssh multitenant '/tmp/backup_runtimes.sh -c alliancemine-9.0.0'
```

## Failure modes

| Symptom | Diagnosis | Action |
|---|---|---|
| Container exits immediately after restart | Bad config / OOM | `docker logs alliancemine-9.0.0` last lines |
| ALB still UNHEALTHY 5 min after kick | Webapp deployment failed | Check `catalina.<date>.log` for FATAL |
| `pg_terminate_backend` returns 0 | JDBC pool already empty / different DB name | Re-check pg_stat_activity datname |
| Many SEVERE errors post-kick (not stale-session) | Bag upgrade left bags in `UPGRADING` state | Flip orphan bags to `NOT_CURRENT` (see §Bag orphan recovery) |

## Bag orphan recovery

If `pg_terminate_backend` killed the bag upgrade mid-flight, some bags
are stuck in `intermine_state='UPGRADING'`:

```sql
-- Connect to alliancemine_userprofile
SELECT id, name, intermine_state, dateCreated
FROM savedbag
WHERE intermine_state = 'UPGRADING';

-- Flip to NOT_CURRENT (will lazy-upgrade on first user access)
UPDATE savedbag SET intermine_state = 'NOT_CURRENT'
WHERE intermine_state = 'UPGRADING';
```

**Always** take a userprofile DB dump before this UPDATE:
```bash
./scripts/backup_profile_dbs_local.sh -d alliancemine_userprofile
```

## Permanent fixes (queued)

1. **Tier 2 JDBC keepalive** — patch `intermine.properties`:
   ```
   db.production.datasource.url=jdbc:postgresql://...?\
     tcpKeepAlive=true&socketTimeout=300&connectTimeout=30
   ```
   Eliminates the half-closed TCP socket that causes the deadlock.

2. **Tier 1 property patcher script** — survive WAR redeploys without
   manual `webapp.baseurl` patching every time.

3. **Python/Go backend rewrite** — InterMine 1.x bag upgrade logic
   replaced by lazy per-bag upgrade behind advisory locks (see
   `docs/INTERMINE_PYTHON_BACKEND_MIGRATION.md` §10 / `docs/INTERMINE_GO_BACKEND_MIGRATION.md` §10).

## See also

- `docs/INCIDENT_2026_04_30_to_05_01.md` — first time we hit this
- `docs/PRODUCTION_CUTOVER_9_0_0.md` — the cutover that produced this
  config
- `docs/POST_9_0_0_PLANNING.md` Tier 2 — JDBC fix backlog
- `docs/RUNTIME_CONTAINER_BACKUP.md` — ECR snapshot mechanics
- `docs/MULTITENANT_BACKUP_RESTORE.md` — automated backup scripts

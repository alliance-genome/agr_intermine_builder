# Runbook: RDS upgrade + restart cycle — 2026-05-05 evening

## Goal

Scale RDS `intermine-postgres` `db.t3.large` → `db.t3.xlarge` (8 GB → 16 GB, 2 → 4 vCPU). Restart all mines after, kick deadlocks, bump param group.

## Pre-flight (5 min before window)

```bash
# RDS state + free memory baseline
aws rds describe-db-instances --region us-east-1 \
  --db-instance-identifier intermine-postgres \
  --query 'DBInstances[0].[DBInstanceStatus,DBInstanceClass]' --output text

# Snapshot all running mines first (rollback insurance)
ssh -i ~/.ssh/AGR-ssl3.pem ec2-user@172.31.59.87 \
  '/tmp/backup_runtimes.sh -a'

# Verify mousemine backup exists
aws s3 ls s3://agr-db-backups/db-backups/alliancemine/ | grep 8_3_0
```

## 1. Scale RDS (~5–10 min downtime)

```bash
aws rds modify-db-instance --region us-east-1 \
  --db-instance-identifier intermine-postgres \
  --db-instance-class db.t3.xlarge \
  --apply-immediately

# Watch status (loop until 'available')
until [ "$(aws rds describe-db-instances --region us-east-1 \
  --db-instance-identifier intermine-postgres \
  --query 'DBInstances[0].DBInstanceStatus' --output text)" = "available" ]; do
  date; sleep 30
done
```

## 2. Param group tweaks (apply, no reboot needed for these)

Current values are sized for 8 GB. Bump for 16 GB:

```bash
aws rds modify-db-parameter-group --region us-east-1 \
  --db-parameter-group-name intermine-postgres15 \
  --parameters \
    "ParameterName=shared_buffers,ParameterValue={DBInstanceClassMemory/8192},ApplyMethod=pending-reboot" \
    "ParameterName=effective_cache_size,ParameterValue={DBInstanceClassMemory/4096},ApplyMethod=pending-reboot" \
    "ParameterName=work_mem,ParameterValue=32768,ApplyMethod=immediate" \
    "ParameterName=maintenance_work_mem,ParameterValue=524288,ApplyMethod=immediate"

# shared_buffers + effective_cache_size need reboot — schedule at end
aws rds reboot-db-instance --region us-east-1 \
  --db-instance-identifier intermine-postgres
```

(Skip the reboot at the end if you want to defer; immediate `work_mem` already helps.)

## 3. Restart all mines (each may need pg_terminate_backend kick)

For each container — `alliancemine-9.0.0`, `wormmine`, `mousemine-1x`:

```bash
ssh -i ~/.ssh/AGR-ssl3.pem ec2-user@172.31.59.87 \
  'docker restart <container>'

# Wait 60s, check for deadlock pattern (all idle)
ssh AllianceMineDev "docker exec mousemine env PGPASSWORD=... psql -h ... \
  -d postgres -c \"SELECT state, count(*) FROM pg_stat_activity \
  WHERE datname='<dbname>' GROUP BY state;\""

# If all idle for >2 min → kick:
ssh AllianceMineDev "docker exec mousemine env PGPASSWORD=... psql -h ... -d postgres \
  -c \"SELECT count(pg_terminate_backend(pid)) FROM pg_stat_activity \
  WHERE datname='<dbname>' AND application_name='PostgreSQL JDBC Driver';\""
```

DB names:
- alliancemine-9.0.0 → `alliancemine_9_0_0_rc18`
- wormmine → `wormmine_final`
- mousemine-1x → `mousemine_db`

## 4. Verify each public URL

```bash
for U in \
  https://alliancemine.alliancegenome.org/alliancemine/service/version \
  https://wormmine.alliancegenome.org/wormmine/service/version \
  http://172.31.59.87:8084/mousemine/service/version; do
  echo -n "$U: "
  curl -sS -o /dev/null -w "%{http_code}\n" "$U" --max-time 30 || echo FAIL
done
```

Expect 200 from all. If any 5xx, check container logs.

## 5. Confirm logo fix on AllianceMine

After alliancemine-9.0.0 restart, hard-reload `https://alliancemine.alliancegenome.org/alliancemine/`. Logo should now render (we patched `branding.images.logo` earlier today; restart picks it up).

## 6. Re-snapshot mines that changed config

```bash
ssh -i ~/.ssh/AGR-ssl3.pem ec2-user@172.31.59.87 \
  '/tmp/backup_runtimes.sh -c alliancemine-9.0.0'
```

(Mousemine + wormmine unchanged tonight; skip.)

## 7. Watch RDS memory recover

```bash
aws cloudwatch get-metric-statistics --region us-east-1 \
  --namespace AWS/RDS --metric-name FreeableMemory \
  --dimensions Name=DBInstanceIdentifier,Value=intermine-postgres \
  --start-time $(date -u -d '15 minutes ago' +%FT%TZ) \
  --end-time $(date -u +%FT%TZ) \
  --period 60 --statistics Average \
  --query 'Datapoints[*].[Timestamp,Average]' --output text | sort
```

Expect freeable to settle at 8–10 GB (was 70–100 MB this afternoon on `t3.large`).

## Rollback (if anything goes sideways)

```bash
# Revert to t3.large
aws rds modify-db-instance --region us-east-1 \
  --db-instance-identifier intermine-postgres \
  --db-instance-class db.t3.large --apply-immediately

# Restore containers from ECR if config got corrupted
ssh ... './restore_multitenant_runtime.sh -c alliancemine-9.0.0 -t runtime-9.0.0'
```

## Post-mortem timer

If freeable memory drops below 1 GB within a week post-upgrade, plan
`db.t3.2xlarge` (32 GB) or `db.r6i.xlarge` (mem-optimized). Today's
fire wasn't only a memory problem — scrapers also drove it; with
multitenant now under WAF, expect headroom to last longer.

## See also

- `docs/RUNBOOK_ALLIANCEMINE_RESTART.md` — single-mine restart + kick
- `docs/MULTITENANT_BACKUP_RESTORE.md` — backup/restore mechanics
- `docs/RDS_PERFORMANCE_PLAN.md` — param-group tuning context

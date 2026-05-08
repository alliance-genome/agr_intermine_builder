# RDS performance plan — AllianceMine

## Symptom

`alliancemine.alliancegenome.org` returns HTTP 500 on `/service/templates`,
`/service/web-properties`, `/service/list/enrichment`, and similar
endpoints. CloudWatch alarms fire on `intermine-postgres` CPU >80%
sustained.

## Root cause

InterMine's webapp emits queries shaped like:

```sql
SELECT a4_.name, COUNT(*)
FROM (
  SELECT DISTINCT a1_.id, a4_.name, a4_.id
  FROM Gene AS a1_, Homologue AS a2_, Gene AS a3_, Organism AS a4_
  WHERE a1_.id IN ($1, $2, ..., $400+)   -- one literal per gene in the user's list
    AND a1_.id = a2_.geneid
    AND a2_.homologueid = a3_.id
    AND a3_.organismid = a4_.id
) GROUP BY a4_.name, a4_.id;
```

When the user's list has hundreds of gene IDs, the literal `IN (…)` list
defeats Postgres's planner, not its executor. With 50 IDs:

| Phase | Time |
|---|---:|
| Planning | 1175 ms |
| Execution | 245 ms |

Planning is **5x execution**. With 400+ IDs the planning cost grows
super-linearly — single-query timings around 24 s observed in
`pg_stat_statements`. With concurrent users, queries pile up, the
Hikari connection pool saturates, and the webapp serves 500s.

The InterMine indices are correct (`homologue__gene` on `(geneid, id)`,
`gene_pkey`, `organism_pkey`); the actual query plan is fine. The
problem is how the webapp builds the query — literal `IN (…)` instead
of `WHERE id = ANY($1::int[])` or a bag (temp) table.

## Plan

| # | Step | Cost | Status |
|---|---|---|---|
| 1 | Verify `Homologue.geneid` index exists | $0 | ✅ done — present, not the bottleneck |
| 1.5 | `ANALYZE homologue; ANALYZE gene; ANALYZE organism;` | $0 | open |
| 2 | EXPLAIN the heavy enrichment query | $0 | ✅ done — planner overhead, not data access |
| 2.5 | **Real fix: webapp emits `id = ANY($1::int[])` or uses bag table** | $0 webapp side, weeks effort upstream | open — InterMine code |
| 3 | Hourly cron `kill-queries --older-than 5m` | $0 | ✅ implemented (`scripts/db-kill-stuck.cron`) |
| 4 | Bump `work_mem` for the webapp DB user | $0 | open — helps DISTINCT/GROUP, won't fix planning |
| 5 | Scale `db.t3.large` → `db.r5.large` | +~$190/mo | open — eliminates burstable credit throttling, more RAM = catalog cached |
| 6 | Scale → `db.r5.xlarge` | +~$500/mo | hold — overkill until 2.5/4 done |

## Notes

- `db.t3.large` is a **burstable** instance. Sustained ≥80% CPU
  exhausts CPU credits; once depleted, RDS throttles to 40% baseline.
  When the alarm fires, the box is already credit-starved — graphs
  understate the real load.
- AllianceMine 8.3.0 is 56 GB. `db.t3.large` has 8 GB RAM → only ~14%
  of the DB cacheable. `db.r5.large` (16 GB RAM) lifts that to ~29% and
  costs roughly the same as the credit waste.
- `pg_stat_statements` is now installed in `alliancemine_8_3_0`. Top
  time-burners can be re-checked any time:
  ```sql
  SELECT calls, round(mean_exec_time::numeric, 0) AS mean_ms,
         round(total_exec_time::numeric/1000, 0) AS total_s,
         substring(query, 1, 100)
  FROM pg_stat_statements
  WHERE query NOT LIKE 'create index%' AND query NOT LIKE 'COPY %'
  ORDER BY total_exec_time DESC LIMIT 10;
  ```
- `log_min_duration_statement = 5s` is already set on the parameter
  group; slow queries land in CloudWatch Logs under
  `/aws/rds/instance/intermine-postgres/postgresql`.

## Manual mitigation

If a storm hits between cron runs, cancel by hand:

```bash
python3 -m src.cli.db_admin kill-queries alliancemine_8_3_0 --older-than 1m --yes
```

Add `--terminate` to kill the connection (forces Hikari to recycle):

```bash
python3 -m src.cli.db_admin kill-queries alliancemine_8_3_0 --older-than 1m --terminate --yes
```

## Related

- `scripts/db-kill-stuck.cron` — hourly cron, calls
  `db_admin kill-queries`
- `scripts/db_kill_stuck_cron.sh` — wrapper invoked by cron
- `src/cli/db_admin.py` — `kill-queries` subcommand

---

## 2026-04-30 incident — bot scraping `/service/list/enrichment`

### Symptoms
- RDS CPU sustained 80-87%, CloudWatch alarms firing.
- 23 active queries on `alliancemine_8_3_0` stuck 1-2 hours, all
  `SELECT DISTINCT ... COUNT(*) FROM Gene/Homologue/Organism`.
- MouseMine `project_build` create-index step ballooned from 10 min to
  90 min (RDS resource contention).
- Site users saw 500s on templates, web-properties, list endpoints.

### Investigation
1. Cancelled stuck queries via `db_admin kill-queries`. Pile reformed
   within minutes — source kept hammering.
2. Tomcat access log showed only ALB internal IPs (172.31.x). Real
   client identity hidden.
3. Enabled ALB access logs to `s3://alb-logs-alliancemine-20260430`
   (ELB delivery account `127311923021` write policy on
   `AWSLogs/100225593120/*`).
4. Patched Tomcat `AccessLogValve` pattern in container to log
   `%{X-Forwarded-For}i %h %l %u %t "%r" %s %b %D` and restarted the
   `alliancemine` container.
5. ALB log batch revealed clear bot signature:
   - `47.128.53.0/24` — 4 different IPs, 126 requests in 5 min
   - `45.159.9.91/32`, `198.13.197.80/32`, `148.135.244.102/32`,
     `103.175.19.10/32` — each at exactly 27 reqs in 5 min
   - All hitting `/alliancemine/service/list/enrichment` with 300+
     gene IDs in a literal `IN (...)` query string. Pattern: rotating
     egress IPs, even per-IP throttle — orchestrated scraper.

### Mitigation deployed
ALB listener rules (HTTPS listener `dcc809bd897b5247`):

| Priority | Source IPs | Path | Action |
|---|---|---|---|
| 50 | `47.128.53.0/24`, `45.159.9.91/32`, `198.13.197.80/32` | `/alliancemine/service/list/enrichment*` | fixed-response 429 |
| 51 | `148.135.244.102/32`, `103.175.19.10/32` | `/alliancemine/service/list/enrichment*` | fixed-response 429 |

Two rules because ALB caps a rule at 5 condition values; we have 5
IPs + 1 path = 6.

To remove later:
```
aws elbv2 delete-rule --rule-arn <arn>
```

### Open follow-ups
- WAF size-constraint rule on `QUERY_STRING` length for the
  enrichment endpoint (blocks any 300-ID list, not just known bots).
  Blocked today by missing `wafv2:*` IAM perms on `pnuin`. See
  `docs/WAF_REQUEST_FOR_COLLEAGUE.md`.
- The Tomcat valve patch is **ephemeral** — lost on container
  recreate. Bake into the `intermine-tomcat` image build.
- Wider `internalProxies` regex on `RemoteIpValve` so `%h` shows real
  client without needing `%{X-Forwarded-For}i`. AWS VPC range
  `172.16/12` is missing from default.

### Related artifacts
- `src/cli/db_admin.py` — `kill-queries` subcommand
- `scripts/db-kill-stuck.cron`, `scripts/db_kill_stuck_cron.sh` — hourly
  cron (NOT yet installed; uninstalled pending build-pipeline review)

---

## Build performance — MouseMine (2026-04-30)

### Symptom (per maintainer)
MouseMine build is "too slow" compared to other deployments.
Concrete data point: `CREATE INDEX reference__key_refid` took
**7,856,352 ms (2 h 11 m)** on a 1.2-million-row, 1.2 GB table.
Expected ~10 minutes locally.

### Where the time goes
1. **RDS instance class is burstable.** `db.t3.large` = 2 vCPU, 8 GB
   RAM. Sustained load (a build) drains CPU credits in ~30 min,
   then RDS throttles to 40% of one vCPU baseline. Effectively
   **0.8 vCPU**, not 2. Most of a build runs throttled.
2. **RAM too small for the working set.** mousemine_db is 99 GB.
   `shared_buffers` = 6.1 GB, `effective_cache_size` set to 31 GB
   (overcommitted). At any time only ~6-8% of the DB is cached.
   Every JOIN spills to disk, every COPY fights the page cache.
3. **Concurrent contention.** During the 2 h index build, the
   alliancemine bot scraper (see prior section) had 23 active
   queries pegging the same instance. RDS resources are shared
   across all 13 databases — alliancemine's storm slowed mousemine.
4. **The "many layers" — Docker, builder host, network — combined
   add <2 % overhead.** Network RTT builder→RDS is ~1 ms vs
   ~0.05 ms for localhost. For batch loads this is negligible.
   Layers are not the bottleneck.

### Memory params already tuned
RDS parameter group has been raised above defaults:
- `work_mem = 512 MB` (default 4 MB)
- `maintenance_work_mem = 1 GB` (default 64 MB)
- `shared_buffers = 6.1 GB` (75 % of RAM, max practical)
- `effective_cache_size = 31 GB` (overcommitted, suggests param
  group was tuned for an r5.xlarge that was later downsized)

No further memory tuning gains available without scaling the
instance.

### Plan
1. **During current MouseMine build**: do NOT modify the instance.
   Memory is already maxed for `db.t3.large`. Leave it alone.
2. **After this build completes**: scale up.
   - **First choice**: `db.r5.xlarge` (4 vCPU, 32 GB RAM, no
     credit throttle). Expected impact: 2-4× faster CREATE INDEX,
     30-50 % faster overall build, no more "credit-starved at hour
     2" cliff. Cost: ~$500/mo vs ~$120/mo today (+$380/mo).
   - **Compromise**: `db.r5.large` (2 vCPU, 16 GB RAM). 2× cache,
     no credit throttle, ~$310/mo (+$190/mo).
3. **Long-term consideration**: separate "build" and "serve"
   workloads. RDS read replica for the webapp + a dedicated
   instance for builds. Builder writes to an isolated DB, then
   we promote/swap. Eliminates the kind of cross-tenant
   contention seen 2026-04-30.

### How to measure build performance going forward
- `pg_stat_statements` is now enabled in `alliancemine_8_3_0`. Add
  the same to mousemine_db before the next build:
  ```
  CREATE EXTENSION IF NOT EXISTS pg_stat_statements;
  ```
- After a build, top time-burners visible via:
  ```sql
  SELECT calls, round(mean_exec_time::numeric/1000, 1) AS mean_s,
         round(total_exec_time::numeric/1000, 1) AS total_s,
         substring(query, 1, 80)
  FROM pg_stat_statements
  WHERE query NOT LIKE 'COPY %'
  ORDER BY total_exec_time DESC LIMIT 20;
  ```
- RDS slow log (`log_min_duration_statement = 5s`) lands at
  CloudWatch Logs `/aws/rds/instance/intermine-postgres/postgresql`.
  Search `pg_stat_statements_reset()` between builds for clean
  per-build numbers.

### Open scaling action — DO AFTER BUILD COMPLETES
- [ ] `aws rds modify-db-instance --db-instance-identifier
  intermine-postgres --db-instance-class db.r5.xlarge
  --apply-immediately` (10 min downtime)
- [ ] Re-evaluate `effective_cache_size` to match new RAM
- [ ] After 1-2 weeks at r5.xlarge, confirm headroom and decide
  whether to keep or downsize to r5.large

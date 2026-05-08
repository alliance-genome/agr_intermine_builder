# Post-9.0.0 Planning

Living doc. Things 9.0.0 cutover surfaced that need planning, not one-off
bash. Group by risk + cost.

## Tier 0 — fix this week (rough edges from cutover)

### `webapp.baseurl` patch
- Current value baked in WAR: `http://localhost:8090`
- Should be: `https://alliancemine.alliancegenome.org`
- Files affected (inside running container):
  - `webapps/alliancemine/WEB-INF/web.properties`
  - `webapps/alliancemine/WEB-INF/classes/intermine.properties`
- After patch, restart container, re-snapshot to ECR (`runtime-9.0.0`).
- Risk: medium — wrong baseurl breaks API clients that follow generated links.

### Old 8.3.0 cleanup (after ≥1 week)
- 2026-05-08 or later: drop `alliancemine_8_3_0` (or `alliancemine_8_3_0_archive`
  if renamed during a cleaner future promotion).
- Reclaims ~30 GB on RDS gp3.

### Re-upgrade or delete the 2 orphan bags
- `ALL_Yeast_Genes` (7336 genes), `ALL_Verified_Uncharacterized_Dubious_ORFs` (6617).
- Either log in as superuser and access them (lazy upgrade), or write a
  one-shot script that calls the bag upgrade API per bag.

## Tier 1 — automate before next major (8.3.0 → 9.0.0 burned a week)

### Promotion playbook → script
`docs/RELEASE_PROMOTION_PROTOCOL.md` is now the de-facto checklist. Bake
it into `db_admin promote-and-deploy <new-version>`:

1. Profile DB backup → S3
2. RDS snapshot
3. Drop old container (pause traffic)
4. Rename DBs (`old → old_archive`, `rc → production-name`)
5. Patch WAR properties (the risky step today — no patcher exists)
6. Solr core swap (rename or point new WAR at versioned cores)
7. Restart container
8. Smoke tests (`/service/version`, `/service/templates`, gene page render)
9. Update `IMAGE_TAG` in `.env`, update CLAUDE.md, log result

`--dry-run` mode that prints every step without doing anything.

### Property patcher
The single biggest risk in step 5. WAR properties baked at build time:
- `webapp.baseurl`
- `superuser.account`
- `db.userprofile-production.datasource.databaseName`
- `index.solrurl` + `autocomplete.solrurl`
- `keyword_search.properties` Solr URLs
- `objectstoresummary.config.properties` Solr URLs
- `/etc/hosts` line for `agr.stage.alliancemine.solr.server`

A `patch_runtime_war.py` that takes a config file and edits all of
these in the deployed exploded WAR + restarts Tomcat would replace
the bash sequence we just ran by hand.

### Tomcat image with patches baked in
Today: every fresh `intermine-tomcat:latest` container needs
RemoteIpValve + manager remote-deploy + 500 MB upload limit + the
`/etc/hosts` line applied manually.

Build a `intermine-tomcat:agr-runtime` image that has all four already
in place. Push to ECR. Run flags become just `-p` and `--add-host`
(or move that into the image too via `extra_hosts` in compose).

### Smoke test script
Codify the manual `curl` checks in `RELEASE_PROMOTION_PROTOCOL.md` step 6.
Fail loud on any non-200 or empty response. Output: pass/fail per check.

## Tier 2 — robustness against the bag-upgrade deadlock

### JDBC socket timeout
The deadlock was a half-closed TCP that the JVM never noticed. Add to
the JDBC URL:

```
?socketTimeout=30&tcpKeepAlive=true&loginTimeout=10
```

(socketTimeout is seconds in pgjdbc.) Means a stuck conn dies in 30 s
instead of forever. Lock releases. Init progresses.

This is a property change in `web.properties` / `intermine.properties`
or possibly Hikari's `dataSourceProperties`. Needs verification of
where the JDBC URL is assembled.

### Per-bag upgrade scheduling
Production superuser had 22 bags. Doing them serially during init
blocks the whole webapp. Two fixes upstream-worthy:

1. Move bag upgrade off the init thread — into a background scheduler
   that processes one bag at a time after Tomcat is already serving.
2. Or skip on-init upgrade entirely; upgrade lazily on first access.

Both require source patches to InterMine. Worth raising upstream; in
the meantime, document the workaround (flip orphans to NOT_CURRENT,
they re-trigger on access).

### Bag size cap warning
A 7336-gene bag where each row is `(LOWER(primaryIdentifier), LOWER(symbol), LOWER(name))`
is the same query shape that the bot scraper used to crash RDS. Even
without the bot, that query is ~5-30 s. Should we cap saved-bag size,
or paginate the upgrade query?

## Tier 3 — observability gaps the incident exposed

### Per-DB `pg_stat_activity` dashboard
We discovered the bag-upgrade hang by manually polling pg_stat_activity.
A Grafana panel grouped by `datname` showing `state` counts + oldest
`query_start - now()` per DB would catch this in seconds.

### Tomcat thread state alarm
The JVM had ~40 threads BLOCKED on a single monitor for 15 min before
we noticed. JMX → Prometheus → alarm on
`Tomcat threads BLOCKED > 10 for > 5 min` would page someone.

### ALB target health alarm (PROACTIVE)
The 8.3.0 target was UNHEALTHY for hours yesterday before we touched it.
CloudWatch alarm on `UnHealthyHostCount > 0 for 5 min` per target group
in `alliancemine-lb` should page.

## Tier 4 — incident hardening

### Container backup cron
`docs/RUNTIME_CONTAINER_BACKUP.md` lays out the procedure manually. Cron
it: nightly `docker commit` + `docker push` for `alliancemine`,
`wormmine`, etc. Tag dated, prune > 30 days.

### Profile DB backup is already cron'd
Daily 02:00 UTC via `scripts/db-backup.cron`. Verified working
2026-04-30 + 2026-05-01.

### Disk-full alarm on multitenant
EBS root volume just filled to 100%, killed Docker, killed every
container. CloudWatch agent → page at >85%.

### `docker system prune` lockdown
The prune disaster on 2026-04-30 deleted alliancemine + wormmine. Add a
shell wrapper / alias on multitenant that refuses `prune -a` without an
explicit `--really` flag. Or replace with a script that lists what would
be deleted and asks per-container.

## Tier 5 — bigger architectural questions (need your call before scoping)

### Multitenant single-host risk
Everything (alliancemine, wormmine, mousemine, bluegenes, Caddy CDN,
Solr) runs on `172.31.59.87`. Disk full, `docker prune`, OS upgrade,
or anything kernel-level takes the whole stack down. Worth splitting
the runtime hosts? Cost: another EC2 + ALB target. Benefit: blast
radius.

### Solr on the host vs in a container
Solr runs as a native process on multitenant, port 8983. No container.
Survived the prune disaster only because of that. But it means
upgrades, JVM tuning, and config drift live outside our Docker
hygiene. Consider Solr-in-container with a persistent volume?

### FlyMine / WormMine / MouseMine — same WAR-deployment dance?
Right now alliancemine has the runtime ECR snapshot pattern. Other
mines don't. Should they? Each ~700 MB. Total ECR storage + push
time worth it for fast recovery? (Probably yes.)

### Bluegenes
Not touched in 9.0.0 cutover, still pointed at the alliancemine TG
indirectly via path-pattern routing. Verify it works against 9.0.0
schema. May need its own cutover step in the playbook.

### CI for the build container
`docker/alliancemine/` has 6-stage build pipeline. Today triggered
manually. Self-hosted GitHub runner on AllianceMineDev (56 GB RAM
needed, which is why it's not on Actions cloud) → weekly FMS check
→ auto-build → auto-tag RC → manual promotion gate.

---

## Order of attack — recommendation

1. **Tier 0** — close out cutover loose ends this week (3-4 hours total).
2. **Tier 4** — disk + prune lockdown immediately, the cheap stuff.
3. **Tier 2** — JDBC socketTimeout next, single property change, dramatic robustness win.
4. **Tier 1** — promotion script + property patcher next sprint, biggest leverage.
5. **Tier 3** — observability when you have a quiet day.
6. **Tier 5** — book a planning session, scope each separately.

What's your priority?

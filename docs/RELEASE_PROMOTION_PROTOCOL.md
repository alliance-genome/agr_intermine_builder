---
title: "AllianceMine Release Promotion Protocol"
subtitle: "8.3.0 → 9.0.0"
author: "Alliance of Genome Resources"
date: "2026-05-01"
geometry: margin=2.5cm
fontsize: 11pt
mainfont: "Helvetica Neue"
monofont: "Menlo"
header-includes:
  - \usepackage{fvextra}
  - \DefineVerbatimEnvironment{Highlighting}{Verbatim}{breaklines,commandchars=\\\{\}}
  - \usepackage{xcolor}
  - \definecolor{sectioncolor}{HTML}{2C3E50}
---

# AllianceMine Release Promotion Protocol

This document describes the production rollover of AllianceMine from
**8.3.0 to 9.0.0**. The same procedure (parameterized) covers any
future major release.

The risky step is **Step 4 — property patches** in the deployed WAR.
Until that step is scripted, treat it as the highest-attention part of
the run.

---

## Pre-flight (Tuesday)

1. **Verify RC tested and approved.** Confirm `alliancemine_9_0_0_rc18`
   has been QA'd by the data team. No outstanding showstoppers.

2. **Confirm Solr cores exist for 9.0.0:**

```bash
curl -s "http://172.31.59.87:8983/solr/admin/cores?action=STATUS&core=alliancemine-search-9.0.0"
curl -s "http://172.31.59.87:8983/solr/admin/cores?action=STATUS&core=alliancemine-autocomplete-9.0.0"
```

3. **Verify WAR for 9.0.0** is on multitenant or in image registry. Confirm tag.

4. **Free RDS storage.** Ensure ≥100 GB free.

5. **Announce maintenance window.** Plan ~30 minutes downtime.

---

## Day-of (Wednesday) — sequential

### Step 1 — Backup before touching anything

```bash
# Profile DB (irreplaceable)
python3 -m src.cli.db_admin backup alliancemine_userprofile

# Current production (rollback insurance)
python3 -m src.cli.db_admin backup alliancemine_8_3_0

# RDS snapshot (instant safety net)
aws rds create-db-snapshot \
  --db-snapshot-identifier intermine-postgres-pre-9-0-0-promote-$(date +%Y%m%d) \
  --db-instance-identifier intermine-postgres
```

Wait for the snapshot status `available` before proceeding.

### Step 2 — Drop the alliancemine container (pause traffic)

```bash
ssh -i ~/.ssh/AGR-ssl3.pem ec2-user@172.31.59.87
docker stop alliancemine
```

Production goes 503 here. ALB shows the target down.

### Step 3 — Rename DBs

```bash
# Move 8.3 out of the way (kept for rollback, NOT deleted)
python3 -m src.cli.db_admin rename alliancemine_8_3_0 alliancemine_8_3_0_archive --force

# Promote RC -> production name
python3 -m src.cli.db_admin promote alliancemine_9_0_0_rc18
# Renames alliancemine_9_0_0_rc18 -> alliancemine_9_0_0
```

### Step 4 — Deploy 9.0.0 WAR + property fixes (RISKIEST)

The WAR has properties baked in at build time. Per `CLAUDE.md`, post-deploy patches are required:

| Patch | File | Value |
|---|---|---|
| `webapp.baseurl` | `WEB-INF/web.properties` | `https://alliancemine.alliancegenome.org` |
| `superuser.account` | `WEB-INF/web.properties` | the existing superuser email |
| `db.userprofile-production.datasource.databaseName` | `WEB-INF/intermine.properties` | `alliancemine_userprofile` |
| Solr URLs | `keyword_search.properties` + `objectstoresummary.config.properties` | the multitenant Solr endpoints |
| `/etc/hosts` map | inside container | `172.17.0.1 agr.stage.alliancemine.solr.server` |

**Until a patcher script exists, this step is manual and error-prone.**

### Step 5 — Switch Solr to 9.0.0 cores

Either rename in place (after archiving 8.3 cores):

```bash
curl "http://172.31.59.87:8983/solr/admin/cores?action=RENAME&core=alliancemine-search-9.0.0&other=alliancemine-search"
```

Or have the new WAR's Solr URLs already point at the `-9.0.0` cores.

### Step 6 — Start container, smoke test

```bash
docker start alliancemine
# wait for startup (~60s)
docker logs --since 5m alliancemine 2>&1 | grep -i "Server startup\|Catalina.start\|Exception"
```

Smoke checks:

- `GET /alliancemine/service/version` → 200
- `GET /alliancemine/service/templates?format=json` → 200, non-empty list
- `GET /alliancemine/service/list/enrichment?...` with a small known gene list → 200
- Browse a Gene page, confirm GO terms / homologues / publications render
- Bluegenes loads

### Step 7 — Update bookkeeping

- Update `IMAGE_TAG` in `docker/alliancemine/.env` to `9.0.0`.
- Update `MEMORY.md` and `CLAUDE.md` to reflect production is now 9.0.0.
- Note in `docs/RELEASE_PROCESS.md` if any step deviated from this protocol.

---

## Post-promotion

### Keep `alliancemine_8_3_0_archive` for ≥1 week

Rollback path:

```bash
docker stop alliancemine
python3 -m src.cli.db_admin rename alliancemine_9_0_0 alliancemine_9_0_0_failed --force
python3 -m src.cli.db_admin rename alliancemine_8_3_0_archive alliancemine_8_3_0 --force
# restore old WAR + property patches, restart container
```

### After one good week

```bash
python3 -m src.cli.db_admin delete alliancemine_8_3_0_archive --force
```

---

## Notes

- **The bot block** (ALB listener rules at priority 50, 51) is unaffected — the path pattern `/alliancemine/service/list/enrichment*` matches regardless of DB version.
- **ALB access logging** stays on. No change.
- `db_admin promote` already handles the rename atomically and writes an audit-log entry to `~/.alliancemine-db-admin.log`.

## Automation backlog

Items that should be scripted before the next major release:

1. **Property patcher** — a script that opens the deployed WAR, edits `web.properties`, `intermine.properties`, `keyword_search.properties`, `objectstoresummary.config.properties` to the right values, and writes the `/etc/hosts` line. This eliminates Step 4's manual risk.
2. **One-button promote** — wraps Steps 1-7 into a single `db_admin promote-and-deploy` workflow (with a `--dry-run` mode that prints what each step would do).
3. **Smoke test script** — codifies the manual `curl` checks in Step 6, fails loud on any non-200 or empty response.
4. **Rollback script** — the post-promotion rollback block, parameterized by version pair.

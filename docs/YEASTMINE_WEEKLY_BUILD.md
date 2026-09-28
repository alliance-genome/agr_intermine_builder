# YeastMine weekly build and deploy

Set up 2026-09-28. YeastMine rebuilds from fresh SGD data every **Friday 22:00 US Pacific** and
goes live automatically, but only if the new build passes its checks. A build that fails a check
never reaches production, and a deploy that fails its site checks rolls itself back.

Code: `docker/yeastmine/weekly/` (commit 44264df). Short version: `docker/yeastmine/weekly/README.md`.

| Decision | Choice |
|---|---|
| What runs | Full build, then automatic deploy if checks pass |
| When | Friday 22:00 America/Los_Angeles (Saturday 05:00 UTC in summer, 06:00 in winter) |
| Builds kept | Newest 4 rc databases; the live one is never dropped |
| First run | Friday 2026-10-02 |

---

## 1. Overview

```
 AllianceMineDev (build host)                 S3                          Multitenant (production)
 ─────────────────────────────                ──                          ────────────────────────
 Fri 22:00 PT  weekly_build.sh                                            every 30 min  deploy_agent.sh
   next rc, extract, project_build                                          ready.json newer than live?
   search + autocomplete -> Solr *-next  ──(HTTP to multitenant Solr)──▶      no  -> exit
   summary + WAR (mail fix baked)                                            yes -> verify WAR
   check_build.py vs live build                                                    SWAP Solr cores
   pass -> upload WAR + manifest ──────▶ builds/<db>/  ready.json ──────▶           swap WAR, restart
   retention (keep 4)                    live.json  ◀──────────────────────        verify site
                                          last-*-status.json                        fail -> roll back
```

The two hosts only communicate through S3. The build host cannot SSH to the multitenant host,
but it can reach the multitenant Solr over HTTP to fill the standby cores.

---

## 2. The build (build host, about 3 hours)

`~/yeastmine-build/weekly/bin/weekly_build.sh`, started by `yeastmine-weekly-build.timer`. It runs
in the build clone `~/yeastmine-build/agr_intermine_builder/docker/yeastmine` using the
`yeastmine-builder` image and its `.env`.

| Step | What it does | Fails the build if |
|---|---|---|
| Preflight | Checks the `MAIL_*` settings, the standby Solr cores, 20 GB free disk, and `live.json` in S3 | any is missing |
| Next rc | Finds the highest `yeastmine_R64_5_1_rc<N>` on RDS and pins `RC_NUMBER=N+1` for every container run | RDS unreachable |
| Data | `extract_data.py` (S3 sync + ontologies), then refreshes the Alliance orthology file and downloads go-basic, goslim_yeast and PSI-MI with a browser User-Agent | a download is empty or not OBO |
| Integrate | `project_build -b` (integration plus the image's post-processing) | non-zero exit or `BUILD FAILED` |
| Search indexes | `create-search-index` and `create-autocomplete-index`, each in its own JVM, pointed at `yeastmine-search-next` / `yeastmine-autocomplete-next` | a step reports FAILED, or did not target `-next` |
| WAR | `finalize_build`: object-store summary, WAR, SES mail fix baked in; saved as `data/wars/<db>.war` | no WAR produced |
| Checks | `check_build.py` against the live build (section 3) | any check fails |
| Publish | Uploads the WAR and `manifest.json` to `builds/<db>/`, then writes `ready.json` | upload fails |
| Retention | Drops rc databases (and their checkpoint DBs, local WARs, S3 builds) beyond the newest 4, never the live one | (warns only) |

The search indexes go into the **standby** cores, so the live site keeps serving its current
index throughout. The WAR is built in a fresh container, so it always names the live cores
(`yeastmine-search`, `yeastmine-autocomplete`), which is what production uses after the swap.

`--no-publish` runs everything except publishing, so a build can be tested without it going live.

## 3. The checks (`check_build.py`)

A build is published only if **all** of these pass. The thresholds are at the top of the script.

| Check | Rule |
|---|---|
| Total objects | Within ±10% of the live build |
| Key classes | Gene, Protein, Publication, GOAnnotation, Phenotype, Interaction, Complex, Allele, Chromosome, Organism, OntologyTerm each keep at least 90% of their live count |
| Every other class | No class with 1,000+ live objects loses more than half |
| Solr | Standby search and autocomplete indexes hold at least 90% of the live index |
| WAR contents | Has `web.xml` and `struts-config.xml` |
| WAR database | Points at the new rc database |
| WAR mail | `mail.host` and `mail.smtp.user` set; JavaMail 1.6.2 present (SES needs TLS 1.2) |
| WAR Solr | Search and autocomplete URLs name the live cores, not `-next` |

Tested on 2026-09-28 against real rc3 data. Identical counts pass. Halving the Complexes fails
("317 vs live 634"). The June WAR fails on mail and JavaMail.

## 4. The deploy (multitenant host, minutes)

`~/yeastmine-deploy/deploy_agent.sh`, started every 30 minutes by `yeastmine-deploy.timer`. It exits
at once unless `ready.json` names a build that is not the live one and has not failed before.

1. Downloads the WAR and checks its sha256 against the manifest and that it points at the new database.
2. Copies the current `mine-wars/yeastmine.war` to `~/yeastmine-deploy/rollback.war`.
3. Solr `SWAP` of `yeastmine-search` ↔ `yeastmine-search-next`, and the same for autocomplete.
   The swap is atomic; afterwards `-next` holds the previous index.
4. Writes the new WAR into `mine-wars/yeastmine.war` in place (same inode, because the container
   bind-mounts that file), removes the exploded webapp, and restarts `yeastmine`.
5. Checks the site, waiting up to 10 minutes for it to come up:
   - `service/version/release` answers;
   - `begin.do` returns 200;
   - keyword search for ACT1 returns hits;
   - public templates are listed;
   - a query for S. cerevisiae genes returns more than 5,000.
6. On success it writes `live.json`. On any failure it swaps the cores back, restores `rollback.war`,
   restarts, re-checks, and marks that build as failed so it is not retried.

The agent's site checks were run against production YeastMine on 2026-09-28 and pass, so they
won't reject a healthy site.

## 5. S3 layout

`s3://agr-db-backups/yeastmine/weekly/`

| Key | Written by | Contents |
|---|---|---|
| `builds/<db>/yeastmine.war` | build | the WAR |
| `builds/<db>/manifest.json` | build | db, rc, release, sha256, build time, full check results |
| `ready.json` | build | copy of the newest passing manifest; the deploy agent's trigger |
| `live.json` | deploy | the build in production, and the one before it |
| `last-build-status.json` | build | state (`RUNNING`, `FAILED`, `PUBLISHED`), rc, current step or failure reason |
| `last-deploy-status.json` | deploy | `DEPLOYING`, `DEPLOYED`, `FAILED`, `ROLLED_BACK`, `ROLLBACK_FAILED`, `SKIPPED` |

## 6. Setup

| Where | What | Status |
|---|---|---|
| Build host | `MAIL_*` SES settings in `~/yeastmine-build/agr_intermine_builder/docker/yeastmine/.env` (copied from production's config; the file is mode 600, never committed) | done 2026-09-28 |
| Build host | `bash install_build_timer.sh` (scripts to `~/yeastmine-build/weekly/bin`, timer enabled) | done 2026-09-28 |
| Multitenant | `bash install_deploy_agent.sh` (standby cores, `live.json` = current build, deploy timer) | **to do** (needs to be run by hand) |

Multitenant install, from a machine with the key:

```bash
rsync -a -e "ssh -i ~/.ssh/AGR-ssl3.pem" docker/yeastmine/weekly \
  ec2-user@172.31.59.87:/home/ec2-user/yeastmine-weekly-install/
ssh -i ~/.ssh/AGR-ssl3.pem ec2-user@172.31.59.87 \
  'cd ~/yeastmine-weekly-install/weekly && bash install_deploy_agent.sh'
```

The installer is idempotent. Until it has run, the Friday build stops at preflight because the
standby cores and `live.json` don't exist yet.

## 7. Operations

**Is it working?**

```bash
aws s3 cp s3://agr-db-backups/yeastmine/weekly/last-build-status.json -
aws s3 cp s3://agr-db-backups/yeastmine/weekly/last-deploy-status.json -
aws s3 cp s3://agr-db-backups/yeastmine/weekly/live.json -
systemctl list-timers yeastmine-weekly-build.timer   # build host
systemctl list-timers yeastmine-deploy.timer         # multitenant
```

Logs: `~/yeastmine-build/weekly/runs/<stamp>/` on the build host (`build.log`, `checks.json`,
`project_build.log`, one log per index step, `finalize.log`); `~/yeastmine-deploy/logs/` on the
multitenant host.

| Task | Command |
|---|---|
| Roll back to the previous build | `~/yeastmine-deploy/deploy_agent.sh --rollback` (multitenant) |
| Test a build without deploying | `~/yeastmine-build/weekly/bin/weekly_build.sh --no-publish` (build host) |
| Skip the next Friday | `sudo systemctl stop yeastmine-weekly-build.timer`; `start` it again afterwards |
| Pause deploys, keep building | `sudo systemctl stop yeastmine-deploy.timer` (multitenant) |
| Deploy a build that was marked failed | delete `~/yeastmine-deploy/failed-<db>` on the multitenant host; the next run picks it up |
| Update the scripts | edit in the repo, re-run the matching install script (both are idempotent) |

## 8. Troubleshooting

| Symptom | Likely cause / fix |
|---|---|
| Build `FAILED` at preflight: `MAIL_* not set` | `.env` lost its SES settings; re-add `MAIL_HOST`, `MAIL_SMTP_USER`, `MAIL_SERVER_PASSWORD` |
| Build `FAILED`: `standby Solr core … missing` | the multitenant installer hasn't run, or the cores were deleted; re-run `install_deploy_agent.sh` |
| Build `FAILED`: `cannot read …/live.json` | same, or S3 access from the build host is broken |
| Build `FAILED` at checks | read `checks.json` in the run directory. A genuine data drop (SGD or source outage) should stay unpublished. If the drop is expected, rerun with adjusted thresholds |
| Build `FAILED` at `project_build` | read `project_build.log` in the run directory; the data sources and SGD DB are the usual suspects |
| Deploy `ROLLED_BACK` | the new build did not pass the site checks and production is back on the previous one. Check `~/yeastmine-deploy/logs/` for the failing check |
| Deploy `ROLLBACK_FAILED` | **act now**: the site did not verify after rolling back. Check `docker logs yeastmine`; `rollback.war` holds the previous WAR |
| Search empty after a multitenant reboot | not this system: the Solr DNAT rule (`solr-dnat.service`), see the multitenant reboot notes |

## 9. Production changes on the first deploy (Saturday 2026-10-03)

1. **Search becomes current.** Production's Solr index dated from 2026-06-11 (rc1), so data added
   since June was not searchable. Every weekly deploy now ships a fresh index.
2. **`os.query.max-time` returns to 500000000.** Production had been hand-edited to 3600000 on
   2026-09-18. This is a planner-cost ceiling, not a timeout in milliseconds, and 3600000 is below
   InterMine's own default (10000000), which breaks enrichment widgets. 500000000 is the documented
   value (`docs/MOUSEMINE_ENRICHMENT_WIDGET_FIX_2026_05_15.md`).
3. **Mail settings are now built in** rather than hand-edited: same SES host and account, plus
   JavaMail 1.6.2 and the patched `MailUtils`.

## 10. Files

| File | Role |
|---|---|
| `docker/yeastmine/weekly/weekly_build.sh` | the build pipeline |
| `docker/yeastmine/weekly/check_build.py` | the publish gate |
| `docker/yeastmine/weekly/deploy_agent.sh` | the deploy, verify and rollback agent |
| `docker/yeastmine/weekly/install_build_timer.sh` | build host setup |
| `docker/yeastmine/weekly/install_deploy_agent.sh` | multitenant setup |
| `docker/yeastmine/weekly/systemd/*` | the two services and timers |
| `docker/yeastmine/docker-compose.yml` | passes `MAIL_*`; mounts the template, `finalize_build.sh` and the mail patch over the June image |
| `docker/yeastmine/scripts/finalize_build.sh` | bakes the mail fix, keeps the WAR on the data volume |
| `scripts/bake_mail_into_war.sh`, `patches/intermine/MailUtils.java` | the SES mail fix |

## 11. Known limits

- **The build image is from June 2026.** Newer YeastMine source needs an image rebuild
  (`scripts/build_and_push.sh`). The template, `finalize_build.sh` and the mail patch are mounted,
  so they don't need one.
- **The Alliance orthology file** comes from the latest AllianceMine build's FMS download, so it is
  only as fresh as that build.
- **No alerting yet.** Failures are visible only in the S3 status files and logs. A Slack or email
  hook on `FAILED`, `ROLLED_BACK` and `ROLLBACK_FAILED` is a natural next step.
- **Memory on the build host.** The build container's limit is 56 GB of the host's 62 GB. Avoid
  running other builds there on Friday nights.
- **The build host's clone** (`~/yeastmine-build/agr_intermine_builder`) is on branch `development`
  with the weekly files synced in. Its `extract_data.py` is newer than the copy on
  `unified-mine-builder`, so don't overwrite it when syncing.

# YeastMine weekly build

YeastMine rebuilds every **Friday 22:00 US Pacific** and goes live automatically if the new
build passes its checks. If a check fails, production keeps the current build.

## How it works

| Where | What | When |
|---|---|---|
| Build host (AllianceMineDev) | `weekly_build.sh`, from `yeastmine-weekly-build.timer` | Fri 22:00 America/Los_Angeles |
| Multitenant host | `deploy_agent.sh`, from `yeastmine-deploy.timer` | every 30 min; acts only when S3 has a new passing build |

The two hosts talk through S3 (`s3://agr-db-backups/yeastmine/weekly/`), because the build host
cannot SSH to the multitenant host.

**Build** (about 3 hours):
1. Picks the next rc number once (`yeastmine_R64_5_1_rc<N>`) and uses it for every step.
2. Extracts data, then refreshes the Alliance orthology file and the GO, GO-slim and PSI-MI ontologies.
3. Sets the release label shown in the site header: `R64-5-1 (built <Pacific date>, GO <GO release from go-basic.obo>)`.
4. Runs `project_build`: integration plus the post-processing in the image's `project.xml`.
4. Builds the keyword-search and autocomplete indexes into the **standby** Solr cores
   `yeastmine-search-next` / `yeastmine-autocomplete-next`. The live cores are not touched.
5. Builds the object-store summary and the WAR, with the SES mail fix baked in
   (`scripts/bake_mail_into_war.sh`).
6. Runs `check_build.py` against the live build:
   - total objects within ±10%;
   - key classes (Gene, Protein, Publication, GOAnnotation, Phenotype, Interaction, Complex, Allele …) at least 90% of live;
   - no class of 1,000+ objects loses more than half;
   - standby indexes at least 90% of live;
   - the WAR points at the new DB, has mail settings and JavaMail 1.6.2, and searches the live core names.
7. If every check passes, publishes the WAR and a manifest to S3 (`builds/<db>/`, `ready.json`).
8. Retention: keeps the newest **4** rc databases and never drops the live one. Older rc DBs,
   their local WARs and their S3 builds are removed.

**Deploy** (minutes, early Saturday):
1. Downloads the WAR and checks its sha256 and database name.
2. Keeps the current WAR as `rollback.war`.
3. Solr `SWAP`s each standby/live core pair and records which swaps completed.
   Each pair swaps atomically; the two pairs are separate operations. Old indexes stay in `-next`.
4. Replaces `mine-wars/yeastmine.war` in place, removes the exploded webapp and restarts `yeastmine`.
5. Checks the site: release, `begin.do`, search for ACT1, templates, and the yeast gene count.
6. On success: `live.json` records the new build. On failure: completed swaps are reversed,
   the previous WAR is restored, and that build is never retried. A failed reversal or
   restart reports `ROLLBACK_FAILED`, even if the site still responds to health checks.

Manual rollback saves the current WAR before attempting the switch. If that attempt
fails, it reverses completed swaps and restores the saved WAR; inspect the deployment
log whenever `ROLLBACK_FAILED` is reported.

## Status

- `s3://agr-db-backups/yeastmine/weekly/last-build-status.json` shows the last build (state, rc, step).
- `s3://agr-db-backups/yeastmine/weekly/last-deploy-status.json` shows the last deploy
  (`DEPLOYED`, `ROLLED_BACK`, `FAILED`, `ROLLBACK_FAILED`).
- `s3://agr-db-backups/yeastmine/weekly/live.json` names the build in production.
- Build logs: `~/yeastmine-build/weekly/runs/<stamp>/` on the build host (`build.log`, `checks.json`, step logs).
- Deploy logs: `~/yeastmine-deploy/logs/` on the multitenant host.

## Common tasks

```bash
# roll back to the previous build (multitenant host)
~/yeastmine-deploy/deploy_agent.sh --rollback

# build now without publishing (build host) - e.g. to test a change
~/yeastmine-build/weekly/bin/weekly_build.sh --no-publish

# skip this Friday
sudo systemctl stop yeastmine-weekly-build.timer      # start it again afterwards
```

## Setup (one time)

1. Build host: the yeastmine `.env` needs the SES settings (`MAIL_HOST`, `MAIL_SMTP_USER`,
   `MAIL_SERVER_PASSWORD`; port, auth and from have defaults). Without them the build refuses to run.
2. Build host: `bash install_build_timer.sh`
3. Multitenant host: `bash install_deploy_agent.sh`. It creates the standby cores, records the live
   build in `live.json`, and enables the deploy timer.

## Notes

- `os.query.max-time` in the WAR is 500000000, the documented enrichment-widget fix. The June
  production deploy had been hand-edited to 3600000, which is below InterMine's default and breaks
  enrichment widgets. The first weekly deploy restores the documented value.
- The build image is from June 2026. The properties template, `finalize_build.sh` and the mail
  patch are mounted from the host (see `docker-compose.yml`), so they change without an image rebuild.
- The Alliance orthology file comes from the latest AllianceMine build's FMS download, so it is only
  as fresh as that build.

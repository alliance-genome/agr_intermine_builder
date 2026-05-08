# Multitenant Tomcat Backup & Restore

Snapshot every running mine container on multitenant (172.31.59.87) to ECR + S3
with one command. Restore in seconds with another.

Companion to `RUNTIME_CONTAINER_BACKUP.md` (manual procedure for one container).
These scripts automate it across all mines and capture run flags so restores
are reproducible without remembering port maps.

## What gets stored

| Layer | Where | Captures |
|---|---|---|
| Filesystem (WAR, server.xml, /etc/hosts, manager configs) | `ECR agr_<mine>:runtime-<version>` + `:runtime-<version>-<stamp>` | Everything `docker commit` captures |
| Run flags (`-p`, `--add-host`, `-e`, memory, restart policy) | `s3://agr-db-backups/runtime-snapshots/<container>/<stamp>.inspect.json` | Full `docker inspect` output |

Tag scheme matches `RUNTIME_CONTAINER_BACKUP.md`: rolling tag (latest known
good) + dated tag (point-in-time). Sort lexicographically because stamps are
`YYYYMMDD-HHMM`.

## Backup

Run on multitenant. Discovers running containers by name pattern
(`alliancemine-*|wormmine-*|mousemine-*`).

```bash
# scp once to multitenant
scp scripts/backup_multitenant_runtimes.sh multitenant:~/

# dry-run first
./backup_multitenant_runtimes.sh -n

# real
./backup_multitenant_runtimes.sh
```

Flags:

| Flag | Purpose |
|---|---|
| `-n` | Dry-run, prints commands |
| `-c <name>` | Single container only |
| `-p '<glob>'` | Override pattern (e.g. `'mousemine-*'`) |

Env overrides: `ECR_REGISTRY`, `AWS_REGION`, `S3_BUCKET`, `S3_PREFIX`.

## Restore

```bash
# latest snapshot, auto-discover stamp from S3
./restore_multitenant_runtime.sh -c alliancemine-9.0.0

# specific point-in-time
./restore_multitenant_runtime.sh -c alliancemine-9.0.0 -s 20260501-1930

# dry-run: print exact docker run, don't pull, don't execute
./restore_multitenant_runtime.sh -c alliancemine-9.0.0 -n

# pin specific image tag
./restore_multitenant_runtime.sh -c alliancemine-9.0.0 -t runtime-9.0.0-20260501-1930
```

Refuses if a container with the same name already exists; clear it first:

```bash
docker rm -f alliancemine-9.0.0
```

Prompts `Execute? [y/N]` after printing the final `docker run` line. Audit
before agreeing.

## What restore replays from inspect JSON

| docker run flag | JSON path |
|---|---|
| `-p hostPort:containerPort` | `.HostConfig.PortBindings` |
| `--add-host` | `.HostConfig.ExtraHosts` |
| `-e KEY=value` | `.Config.Env` (skips PATH, HOME, HOSTNAME, JAVA_HOME, LANG, TERM) |
| `--memory` | `.HostConfig.Memory` |
| `--restart` | `.HostConfig.RestartPolicy.Name` |

Things NOT replayed (intentional — defaults from the image win):
- Working dir, user, hostname
- Bind mounts (multitenant containers don't use them; if added later, extend
  the script)
- Networks beyond default bridge

## Disaster recovery example

Container deleted by accident (e.g. `docker system prune` repeat of
2026-04-30 incident):

```bash
# Latest known-good is in ECR + S3 from the last backup run
./restore_multitenant_runtime.sh -c alliancemine-9.0.0 -n   # audit
./restore_multitenant_runtime.sh -c alliancemine-9.0.0      # restore
docker logs -f alliancemine-9.0.0
curl -sS -o /dev/null -w '%{http_code}\n' http://localhost:8082/alliancemine/service/version
```

Expected: 200 in <30s after Tomcat finishes starting.

## Cadence

Recommended:

- **Before any in-place change** to a deployed container (config patch, WAR
  redeploy) — back up first as rollback insurance.
- **After confirmed-good deploy** — overwrite rolling tag, keep new dated.
- **Nightly cron on multitenant** — see Tier 4 in `POST_9_0_0_PLANNING.md`.
- **Prune dated tags >90 days** — manual or scripted via `aws ecr
  batch-delete-image`. Keep at minimum the 2 most recent.

## Failure modes & recovery

| Symptom | Cause | Fix |
|---|---|---|
| `docker commit` fails | Disk full on multitenant | Free space, retry |
| `docker push` fails | ECR auth expired | Re-run script (it logs in fresh) |
| `aws s3 cp` fails | Missing/bad IAM role on multitenant | Check instance profile attached |
| Restore: container exits immediately | Port already bound | `lsof -i :<port>`, kill conflicting process |
| Restore: 502 on health check | Tomcat still starting | Wait 30s, retry |
| Restore: 404 on `/alliancemine/...` | WAR not in image (commit was of empty container) | Pick older dated tag |

## Related

- `RUNTIME_CONTAINER_BACKUP.md` — Manual procedure (one container) and the
  reasoning behind the snapshot scheme.
- `INCIDENT_2026_04_30_to_05_01.md` — The disaster these scripts exist to
  prevent recurrence of.
- `PRODUCTION_CUTOVER_9_0_0.md` — First use of the scheme in anger.
- `POST_9_0_0_PLANNING.md` Tier 4 — Cron'ing this nightly.

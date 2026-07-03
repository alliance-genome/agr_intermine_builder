# RDS Monitor + Mine Watchdog — Design

**Date:** 2026-07-02
**Status:** Approved (design), pending implementation plan

## Problem

Recurring production incidents this session, all detected late (by users, not us):

- **Stuck webapp queries** on RDS (MouseMine/YeastMine hung-query episodes) — connections pile up, queries never return.
- **Idle-in-transaction leaks** and **lock pileups** holding resources.
- **JVM heap exhaustion** in mine containers → `OutOfMemoryError` (alliancemine rc20, 2026-07-01) or **GC death-spiral** (rc20, 2026-06-24, 900%+ CPU) → 504s / "internal error" pages that persisted for hours/days unnoticed.
- **RDS storage-full** (2026-06-18) took every mine down.

There is no automated detection or remediation. We need a watchdog that (a) kills problematic RDS queries/connections and (b) detects unhealthy mines and restarts them — with strong safety so it never harms a legitimate build.

## Goals

- Kill runaway / idle-in-transaction / lock-blocked / non-prod RDS queries — **without ever touching build/integration traffic**.
- Detect mines that are down or serving errors and auto-restart them, with anti-flap and rate limits.
- Notify (Slack + email + log) on every action and on sustained/critical conditions.
- Ship safe: a dry-run mode that observes-only until trust is established, plus an instant kill-switch.

## Non-Goals

- Fixing the *root* memory causes (heap sizing, swap, query row-caps) — those are separate infra changes. This tool treats symptoms.
- Replacing CloudWatch / external APM. This is a focused, self-hosted watchdog.
- GC tuning. (Marginal; out of scope.)

## Placement & Runtime

Runs **on multitenant (172.31.59.87)** — where all mine containers live — as a **systemd timer firing every 90 s** (self-healing; simpler than a long-lived daemon). It restarts containers with **native local `docker restart`** (no SSH), probes mines on `localhost:PORT` (bypasses ALB), and reaches RDS directly.

- Python venv: `psycopg2` (RDS), `requests` (HTTP probes). Std-lib for the rest.
- Code lives in the repo: `src/cli/rds_monitor.py` (entrypoint, argparse — matches `rds_manager.py`) + `src/intermine_builder/monitor/` package.
- Deployed to multitenant via a checkout or copied package + a small install script.

```
rds_monitor cycle (every ~90s)
├─ rds_watch.py    → scan pg_stat_activity, apply kill rules
├─ mine_health.py  → probe each mine, decide restarts
├─ notify.py       → Slack + email + rotating log
├─ state.py        → cooldowns, restart counters, failure streaks (persisted to /var/lib/rds_monitor/state.json)
└─ config.py       → load /etc/rds_monitor.yaml
```

## Component 1 — `rds_watch`

Each cycle: `SELECT ... FROM pg_stat_activity`. Apply rules below. **Universal exclusions:** the monitor's own backend (`application_name='rds_monitor'` + `pid <> pg_backend_pid()`), and any connection whose `client_addr` is in `never_kill_src` (default `{172.31.60.197}` — the dev/build host, where `project_build`/postprocess run).

| Rule | Match | Action | Default |
|---|---|---|---|
| idle-in-transaction | `state='idle in transaction'` | `pg_terminate_backend(pid)` | age > 5 min |
| webapp runaway | `state='active'` AND `client_addr` in `webapp_src` (`{172.31.59.87}`) | terminate | age > 10 min |
| lock pileup | `wait_event_type='Lock'` | terminate the **waiter** | wait > 3 min |
| non-prod DB | `state='active'` AND `datname` NOT in `production_dbs` | terminate | age > 15 min |

`age` = `now() - query_start` (or `state_change` for idle-in-txn). All thresholds are config keys.

**Production allowlist (`production_dbs`)** — the *main footgun*, because live DBs carry rc/version suffixes. Explicit in config, defaulting to the current live set:
`alliancemine_9_0_0_rc20`, `wormmine_final`, `flymine_v0-2026-05-31_rc3`, `yeastmine_R64_5_1_rc1`, `mousemine_rc2`, and all `*_userprofile*`. **Operator must update this on every production cutover.** A `rds_monitor --show-prod-dbs` helper prints the current allowlist and the DBs that currently have webapp connections (to sanity-check drift).

Each kill logs: pid, datname, client_addr, state, age, matched rule, the (truncated) query, and dry-run/live.

## Component 2 — `mine_health`

Mines and local ports: `alliancemine:8086`, `flymine:8085`, `wormmine:8081`, `yeastmine:8087`, `mousemine:8084` (config map: mine → port → container name). Container names e.g. `alliancemine → alliancemine-9.0.0-rc20`.

Per mine, per cycle, three checks:
1. `GET localhost:PORT/<mine>/service/version` == 200 (fast, static).
2. A canned DB-backed query (`Gene.primaryIdentifier`, size=1) == 200 within a timeout (proves the DB path).
3. `GET .../begin.do` body does **not** contain `internal error` / `has been logged` (catches the 200-with-error-body case).

A mine is **unhealthy** if any check fails. **Restart only after `fail_streak_threshold` consecutive unhealthy cycles** (default 3 ≈ 4.5 min) to avoid flapping on transient blips.

Restart = `docker restart <container>`. Safety:
- **Cooldown:** no restart within `restart_cooldown` (default 30 min) of the previous one for that container.
- **Rate cap:** max `max_restarts_per_hour` (default 2) per container. On exceed → stop restarting that mine and fire **CRITICAL** (needs a human).
- mousemine's Lucene index is bind-mounted → restart is safe (no re-extract).
- After a restart, re-probe next cycle; if still down after the cap, escalate.

Phase-2 (noted, not in v1): alliancemine post-restart bag-upgrade `pg_terminate_backend` kick (per `RUNBOOK_ALLIANCEMINE_RESTART.md`).

## Component 3 — `notify`

Three sinks, all fed by one `notify(level, event, details)` call:
- **Slack** — incoming-webhook URL from config.
- **Email** — SES (preferred, IAM on the box) or SMTP; recipients in config.
- **Log** — rotating file `/var/log/rds_monitor.log`.

Levels: `INFO` (killed a query), `WARN` (restarted a mine), `CRITICAL` (restart cap hit / mine still down after restart / **RDS free storage below `storage_warn_gb`**). Throttle: one alert per distinct event; suppress duplicates within a window (`alert_dedup_window`, default 15 min) so a persistent issue doesn't spam.

**Bonus check:** each cycle also reads RDS free storage (CloudWatch `FreeStorageSpace` or `pg_database_size` sum vs. allocated) and alerts CRITICAL under `storage_warn_gb` (default 100) — the 2026-06-18 storage-full class.

## Safety Guardrails (global)

- **`dry_run: true` by default.** In dry-run the tool logs + alerts (prefixed `[DRY-RUN]`) what it *would* kill/restart but takes no destructive action. Run for several days, review, then set `dry_run: false`. This is the single most important safety feature.
- **Kill-switch:** presence of `/etc/rds_monitor.disabled` → the cycle logs "disabled" and exits without any action.
- Every destructive action logs its full reason before executing.
- State (cooldowns, counters, streaks) persists in `/var/lib/rds_monitor/state.json` so a systemd-timer invocation is stateless-per-run but remembers across runs.

## Config (`/etc/rds_monitor.yaml`)

```yaml
dry_run: true
rds:
  host: intermine-postgres.cmnnhlso7wdi.us-east-1.rds.amazonaws.com
  # password from RDS_PASSWORD env / .env, never in this file
  storage_warn_gb: 100
thresholds:
  idle_in_txn_min: 5
  webapp_active_min: 10
  lock_wait_min: 3
  nonprod_active_min: 15
sources:
  webapp_src: ["172.31.59.87"]
  never_kill_src: ["172.31.60.197"]
production_dbs:
  - alliancemine_9_0_0_rc20
  - wormmine_final
  - flymine_v0-2026-05-31_rc3
  - yeastmine_R64_5_1_rc1
  - mousemine_rc2
  # + all *_userprofile* matched by suffix rule
mines:
  alliancemine: { port: 8086, container: alliancemine-9.0.0-rc20 }
  flymine:      { port: 8085, container: flymine }
  wormmine:     { port: 8081, container: wormmine }
  yeastmine:    { port: 8087, container: yeastmine }
  mousemine:    { port: 8084, container: mousemine-1x }
restart:
  fail_streak_threshold: 3
  restart_cooldown_min: 30
  max_restarts_per_hour: 2
notify:
  slack_webhook_url: "https://hooks.slack.com/services/..."
  email: { enabled: true, method: ses, to: ["ops@..."] }
  alert_dedup_window_min: 15
```

Secrets (RDS password, Slack URL if sensitive) come from env / the existing `.env` pattern, not committed.

## Error Handling

- RDS unreachable → log + CRITICAL alert (this itself is the storage-full/outage signal); no kills attempted.
- A `docker restart` failure → CRITICAL alert with the docker error; do not retry-loop.
- Malformed config → refuse to run (fail closed), alert.
- The monitor must never crash the cycle on a single-mine or single-query error — isolate per-item with try/except and continue.

## Testing

- Unit: rule matching against synthetic `pg_stat_activity` rows (age/state/client_addr/datname permutations), incl. the production-allowlist and never-kill-src exclusions. Restart decision logic (streak/cooldown/cap) against a fake clock + state. Notifier fan-out with mocked sinks.
- Dry-run integration: point at the real RDS in `dry_run: true`, assert it *identifies* the right targets and takes no action.
- Kill-switch + config-fail-closed behavior.

## Rollout

1. Land code + tests.
2. Deploy to multitenant, `dry_run: true`, systemd timer.
3. Observe logs/alerts several days; tune thresholds + confirm `production_dbs` correctness.
4. Flip `dry_run: false` for the query-kill half first (lower risk); watch.
5. Enable auto-restart half once query-kill is trusted.

## Open Follow-ups (out of scope here)

- The *cure* for the OOM/GC class: bump mine `-Xmx`, add host swap, add query row-caps (`os.query.max-time` already backported). Track separately.
- Phase-2: alliancemine bag-upgrade `pg_terminate` kick post-restart.

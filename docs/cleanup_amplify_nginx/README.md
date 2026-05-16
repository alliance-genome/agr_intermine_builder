# Amplify + nginx cleanup — decommissioned AllianceMine hosts

Date: 2026-05-14
Status: PR draft on `cleanup/decommissioned-alliancemine-hosts` (agr_ui)
Priority: Medium (silent IaC time bomb on next `cdk deploy`)

Discovered during the 9.0.0 release cascade. Box-side nginx hotfix already
applied to keep production webserver running. This doc tracks the remaining
IaC cleanup: agr_ui Amplify rules (CDK + console drift) and the lingering
nginx config block in `agr_nginx_env`.

## Hosts that no longer resolve

| Host | Backing | Status |
|---|---|---|
| `production-alliancemine.alliancegenome.org` | Elastic Beanstalk env (torn down) | dead — CNAME exists, target unreachable |
| `stage-alliancemine.alliancegenome.org` | Elastic Beanstalk env (torn down) | dead — same pattern |

`alliancemine.alliancegenome.org` is **alive** — it points at the multi-tenant
ALB `alliancemine-lb` and serves both the AllianceMine webapp (currently rc20)
on `/alliancemine/*` and the BlueGenes multi-tenant frontend at
`/bluegenes/alliancemine`. All real production traffic flows through this host
(per ALB listener rule priority 250, host-header `alliancemine.alliancegenome.org`).

## What currently routes where

| URL | HTTP | Path |
|---|---|---|
| `https://www.alliancegenome.org/alliancemine/` | **502** | Amplify proxy → dead `production-alliancemine.alliancegenome.org` |
| `https://www.alliancegenome.org/bluegenes/` | 200 | Amplify proxy → live `alliancemine.alliancegenome.org/bluegenes/alliancemine` |
| `https://www.alliancegenome.org/bluegenes/alliancemine` | 200 | Amplify proxy → live `alliancemine.alliancegenome.org/bluegenes/alliancemine` |
| `https://test.alliancegenome.org/bluegenes/alliancemine` | 200 | Amplify proxy → live (test console hand-edited) |
| `https://test.alliancegenome.org/alliancemine/` | 502 | Amplify proxy → dead host |
| `https://stage.alliancegenome.org/bluegenes/alliancemine` | **502** | Amplify proxy → dead host (also CDK target) |
| `https://stage.alliancegenome.org/alliancemine/` | 502 | Amplify proxy → dead host |

The `/alliancemine/` 502 on production has been live for months but went
unnoticed — nothing routes users to that bare URL. BlueGenes
(`/bluegenes/alliancemine`) is the documented entry. Per Chris during the 9.0.0
release: BlueGenes is the user-facing layer now; the bare path is vestigial.

Stage and Test will have **no AllianceMine/BlueGenes UI consumer** going
forward. Both can be deleted entirely.

## CDK vs Amplify console drift

| App | CDK `/bluegenes/*` target | Console `/bluegenes/*` target |
|---|---|---|
| prod `d2gpi6pscvhc6j` | `production-alliancemine.alliancegenome.org:444` (dead) | `alliancemine.alliancegenome.org` (live) — **hand-edited** |
| test `d39tao9vl33upy` | same dead | same live — **hand-edited** |
| stage `d1mrdtdifcvuyq` | `stage-alliancemine.alliancegenome.org:444` (dead) | matches CDK (dead) — no edit |

Prod + test consoles were hotfixed away from CDK months ago. Stage console
matches CDK and is therefore broken. **Next `cdk deploy` of agr_ui regresses
prod + test BlueGenes to dead hosts** unless CDK is backported first. This is
the highest-risk piece of this cleanup.

## Changes shipping in this PR (agr_ui `cleanup/decommissioned-alliancemine-hosts`)

### `cdk/amplify-production-stack.ts`

- Delete 3 `/alliancemine` rules (all pointed at dead host).
- Keep `/bluegenes` rules. `/bluegenes/` + `/bluegenes/<*>` were already
  updated to `alliancemine.alliancegenome.org` (no `:444`) on commit
  `2aa9b653` from the existing `feature/bluegenes-multitenant-production`
  branch — cherry-picked here so the fix actually lands in `main`.

### `cdk/amplify-test-stack.ts`

- Delete 3 `/alliancemine` rules.
- Delete 3 `/bluegenes` rules.
- No test UI consumes either path.

### `cdk/amplify-stage-stack.ts`

- Delete 3 `/alliancemine` rules.
- Delete 3 `/bluegenes` rules.
- No stage UI consumes either path.

Each removed block is replaced by a single comment pointing at this doc, so
future readers can see why those routes vanished.

## Amplify console cleanup (manual or via CDK deploy)

Once the CDK PR is merged + deployed, the Amplify customRules should match.
If the team prefers not to run a full `cdk deploy` first, the equivalent
console cleanup is:

**prod (`d2gpi6pscvhc6j`)** — delete:
- `/alliancemine` (302/301)
- `/alliancemine/`
- `/alliancemine/<*>`

**test (`d39tao9vl33upy`)** — delete:
- `/alliancemine`
- `/alliancemine/`
- `/alliancemine/<*>`
- `/bluegenes`
- `/bluegenes/`
- `/bluegenes/<*>`

**stage (`d1mrdtdifcvuyq`)** — delete:
- `/alliancemine`
- `/alliancemine/`
- `/alliancemine/<*>`
- `/bluegenes`
- `/bluegenes/`
- `/bluegenes/<*>`

Recommended order: backport CDK to match the working prod console (this PR),
deploy stage + test from CDK first (low-risk, both already 502), then either
deploy prod CDK or accept the existing console drift and merge for future.

## nginx (`agr_nginx_env` PR #17)

The release-box hotfix during 9.0.0 commented out both `/alliancemine` and
`/bluegenes` location blocks so nginx could start (it was hard-failing on
unresolvable `production-alliancemine.alliancegenome.org` upstream at
config-load time).

Recommended for PR #17:

1. Keep the resolver + variable lazy-resolution change — the resilience fix is
   the real value (a dead upstream should never again block nginx startup).
2. **Drop the `/alliancemine` location block entirely** instead of repointing.
   The Amplify layer is the single entry point, and even there it's being
   removed. The release-box doesn't need to proxy `/alliancemine` to anything.
3. Decide on `/bluegenes` block in nginx: if the release box is downstream of
   Amplify (Amplify → www.alliancegenome.org → nginx → BlueGenes), this block
   may need updating to `alliancemine.alliancegenome.org`. If Amplify routes
   `/bluegenes/*` directly to the multi-tenant ALB without traversing this
   nginx, drop it entirely. Confirm with Olin which mode is in use.

## DNS / Route 53 follow-up

Once Amplify + nginx no longer reference the dead hosts, delete the CNAME
records too:
- `production-alliancemine.alliancegenome.org` → EB env (gone)
- `stage-alliancemine.alliancegenome.org` → EB env (gone)

This removes the misleading "resolves to a CNAME" behavior that masked the
EB decommission for so long.

## Verification commands

```bash
# Pre-PR-merge state (run any time to spot the dead hosts)
curl -sS -L -o /dev/null -w "%{http_code} %{url_effective}\n" \
  https://www.alliancegenome.org/alliancemine/
# expect 502

# Live route (rc20 backend)
curl -sS https://www.alliancegenome.org/bluegenes/alliancemine
# expect 200 + BlueGenes HTML

# Direct backend (confirms rc20 ALB)
curl -sS https://alliancemine.alliancegenome.org/alliancemine/service/version
# expect: 35

# Amplify rule snapshots
aws amplify get-app --app-id d2gpi6pscvhc6j --query \
  'app.customRules[?contains(source,`alliancemine`)||contains(source,`bluegenes`)]'
aws amplify get-app --app-id d39tao9vl33upy --query \
  'app.customRules[?contains(source,`alliancemine`)||contains(source,`bluegenes`)]'
aws amplify get-app --app-id d1mrdtdifcvuyq --query \
  'app.customRules[?contains(source,`alliancemine`)||contains(source,`bluegenes`)]'
```

## Cross-references

- agr_ui PR `cleanup/decommissioned-alliancemine-hosts` (this work)
- agr_ui existing branch `feature/bluegenes-multitenant-production` (commit
  `2aa9b653` — prod `/bluegenes` fix, never merged; cherry-picked here)
- agr_ui PR #1660 — multi-tenant BlueGenes deploy referenced in incident ticket
- agr_nginx_env PR #17 — proper nginx resolver fix (Olin's review pending)
- `docs/PRODUCTION_CUTOVER_RC20.md` — 9.0.0-rc20 ALB swap (2026-05-13)
- `docs/PRODUCTION_CUTOVER_9_0_0.md` — preceding 9.0.0 cutover (2026-05-01)
- `docs/INCIDENT_2026_04_30_to_05_01.md` — disk-full + accidental prune timeline
  where the EB decommission window started biting

## Owner

PR drafted 2026-05-14 by Paulo Nuin during rc20 post-cutover hygiene. CDK
backport awaiting Olin (nginx) + agr_ui maintainer review.

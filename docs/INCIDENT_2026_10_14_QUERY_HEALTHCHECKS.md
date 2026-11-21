# Incident 2026-10-14: query health checks blocked queries on 4 mines

## Summary

From 22:58 to 01:33 UTC (2 h 35 min), every query on AllianceMine, YeastMine, FlyMine and WormMine
failed with `"error":"Service failed. Please contact support."` (HTTP 500). Report pages and
`/service/version` kept working, so the existing Route53 `/service/version` checks stayed green.
BlueGenes result tables, template previews (e.g. YeastMine `Gene_UTRs`) and REST queries all failed.
MouseMine was not affected.

The trigger was the Route53 query health checks created at 22:56 UTC by
`scripts/create_mine_query_healthchecks.sh` (PR #23). Disabling 4 of the 5 checks cleared it 5 minutes later.

## Mechanism

1. Each InterMine 5.x query (`/service/query/results`) validates the PathQuery XML against the
   webapp's own schema. The validator downloads it over HTTP from
   `${webapp.baseurl}/${webapp.path}/webservice/query.xsd`, i.e.
   `https://<mine>.alliancegenome.org/<mine>/webservice/query.xsd`.
   `webapp.baseurl` must stay the public host because generated client code uses it
   (see `project_webapp_baseurl_bug` notes, fixed 2026-10-08).
2. That download leaves the multitenant host (172.31.59.87) through its single egress IP, goes
   through CloudFront `E225Q02QD2JV8Z` and WAF `alliance-mines-a`, with a Java user agent.
3. Route53 runs each check from about 16 checkers every 30 s, about 30 queries per minute per mine.
   Four mines gave about 125 Java xsd requests per minute from the one IP.
4. WAF rule 21 `RateLimitInterMineLibrariesByIp` blocks Java, curl, python and other library user
   agents above 500 requests per 5 minutes per IP. The xsd requests crossed that limit within minutes.
5. With the xsd blocked, schema validation throws and the webapp returns the generic
   "Service failed" error for every query from every user.
6. Blocked requests keep counting toward the rate, so the block held as long as the checks ran.

MouseMine was unaffected because its webapp fetches the xsd from a private connector on
`localhost:8081` (added 2026-10-05 for the query.xsd deadlock), so its fetches never reach the WAF.

## Timeline (UTC)

| Time | Event |
|---|---|
| 22:41 | CloudFront CORS change for `/service/model*` (OPTIONS) deployed; unrelated, ruled out |
| 22:56 | 5 Route53 query checks + `HealthCheck-<mine>-query` alarms created |
| 22:58 | WAF rule 21 starts blocking: ~1,900 requests per 15 min from then on |
| 23:04-23:05 | `HealthCheck-{alliancemine,yeastmine,flymine,wormmine}-query` go to ALARM |
| 01:25 | User reports YeastMine `Gene --> UTRs` preview failing in BlueGenes |
| 01:26 | Reproduced: `query/results` fails on all 4 mines (GET and POST, any query); MouseMine OK; `template/results` intermittently OK |
| 01:28 | `AWS/WAFV2 BlockedRequests` for rule `RateLimitInterMineLibrariesByIp` shows the block since 22:58 |
| 01:30 | 4 query checks disabled (`update-health-check --disabled`) |
| 01:33 | Queries succeed again on all 4 mines |

## Why it took 2.5 hours to notice

- The new query alarms fired at 23:04, but they had also fired spuriously at creation
  (missing data treated as breaching), so the second firing looked like the same noise.
- The `/service/version` checks do not exercise queries.

## Fix applied

- Route53 query checks for alliancemine, yeastmine, flymine and wormmine are disabled
  (IDs cfa63d88, 027476db, 4225c2bf, f4fa5695). The mousemine check (6c8578ad) stays enabled.
- `scripts/create_mine_query_healthchecks.sh` now creates checks for mousemine only, until one of
  the follow-ups below is done.

## Follow-ups

1. Ask infra (WAF owner) to exclude `/<mine>/webservice/query.xsd` from rule 21's scope, or to exempt
   the multitenant egress IP for that path. Then re-enable the 4 checks.
2. Alternative: recreate the checks with `Regions` limited to 3, about 9 queries per minute per mine.
3. Longer term: serve the xsd locally on each 5.x mine (as MouseMine does) without changing the
   public `webapp.baseurl` used for generated code.
4. When "Service failed" appears on all 4 multitenant 5.x mines at once, check
   `AWS/WAFV2 BlockedRequests` for `RateLimitInterMineLibrariesByIp` first.

## Lesson

Any monitor that sends queries to the 4 multitenant 5.x mines also generates one request per query
from the host IP through the WAF. Size new query traffic against WAF rule 21's 500 per 5 min per IP.

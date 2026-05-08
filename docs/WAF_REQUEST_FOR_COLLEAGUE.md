# WAF blurb (paste into Slack/email)

---

Hi — can we put AWS WAF on the **alliancemine-lb** ALB?

A scraper hammered `/alliancemine/service/list/enrichment` with 300+ gene IDs in the query string. Postgres burns 5-30s in the planner per request, RDS hit 87% CPU, site 500'd. I added two ALB listener rules to block the current bot IPs, but ALB rules can't filter on query-string length, so the next IP rotation bypasses it. WAF can.

**One rule needed:** BLOCK requests to `/alliancemine/service/list/enrichment*` where `QUERY_STRING` > 4 KB or body > 8 KB. ~$10/month.

Either grant `pnuin` `wafv2:*` on regional `us-east-1`, or set it up yourself.

Thanks!

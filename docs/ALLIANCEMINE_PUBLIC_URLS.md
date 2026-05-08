# AllianceMine Public URLs and CloudFront Routing

Operational note on the two public hostnames AllianceMine is reachable
on, and the asymmetry between them.

## What works

| URL | Status | Path |
|---|---|---|
| `https://alliancemine.alliancegenome.org/alliancemine/` | ✅ 200 | direct ALB → multitenant `:8082` → `alliancemine-9.0.0` container |
| `https://alliancemine.alliancegenome.org/alliancemine/service/version` | ✅ 200, body=`35` | API smoke test |

## What is broken (2026-05-05)

| URL | Status | Where it fails |
|---|---|---|
| `https://www.alliancegenome.org/alliancemine/` | ❌ 502 Bad Gateway | CloudFront in front of `www.alliancegenome.org` |
| `https://www.alliancegenome.org/alliancemine/service/version` | ❌ 502 | same |

Response headers identifying the failure layer:

```
HTTP/1.1 502 Bad Gateway
Content-Length: 0
X-Cache: Error from cloudfront
Via: 1.1 <id>.cloudfront.net (CloudFront)
X-Amz-Cf-Pop: IAD61-P7
```

CloudFront returns `502` — origin or behavior for `/alliancemine/*`
under the `www.alliancegenome.org` distribution is misconfigured or
absent.

## Cause

The two hostnames hit different paths:

```
alliancemine.alliancegenome.org   → Route53 ALIAS → ALB → target group → 172.31.59.87:8082
www.alliancegenome.org/alliancemine/   → CloudFront → (broken origin/behavior)
```

The InterMine cluster, container, ALB target group, and ALB listener are
all healthy:

```
ALB target health: 172.31.59.87:8082 → healthy
container         alliancemine-9.0.0 → Up
service/version   200, body=35
internal probe    HTTP/1.1 200 (begin.do)
```

The break is exclusively at the CloudFront layer for the `www.` host.

## What we don't own

The `www.alliancegenome.org` CloudFront distribution is owned by the
Alliance frontend / SRE team, not the InterMine cluster. We can't fix it
from the multitenant side.

## Workaround for users

Direct users to:

> https://alliancemine.alliancegenome.org/alliancemine/

This is the canonical InterMine entry point and is what `webapp.baseurl`
in `web.properties` is set to. BlueGenes production also points at this
hostname.

## What to ask the frontend team

If `www.alliancegenome.org/alliancemine/` is required, the CloudFront
distribution serving `www.alliancegenome.org` needs:

1. A new **origin** pointing at one of:
   - `alliancemine.alliancegenome.org` (simplest — chains through the
     working ALB)
   - the ALB DNS name directly, with `Host` header rewritten to
     `alliancemine.alliancegenome.org`
2. A new **behavior** for path pattern `/alliancemine/*` routing to that
   origin.
3. Caching disabled or short TTL — InterMine pages are session-bound.

## How to re-verify

From any host that can reach the public DNS:

```bash
# direct subdomain — should be 200
echo -e "GET /alliancemine/service/version HTTP/1.1\r\nHost: alliancemine.alliancegenome.org\r\nConnection: close\r\n\r\n" \
  | openssl s_client -connect alliancemine.alliancegenome.org:443 \
                     -servername alliancemine.alliancegenome.org -quiet 2>/dev/null \
  | head -3

# www path — should be 502 until CloudFront is fixed
echo -e "GET /alliancemine/service/version HTTP/1.1\r\nHost: www.alliancegenome.org\r\nConnection: close\r\n\r\n" \
  | openssl s_client -connect www.alliancegenome.org:443 \
                     -servername www.alliancegenome.org -quiet 2>/dev/null \
  | head -3
```

Backend health (proves the issue is *not* on our side):

```bash
ssh -i ~/.ssh/AGR-ssl3.pem ec2-user@172.31.59.87 \
  'aws elbv2 describe-target-health --region us-east-1 \
     --target-group-arn arn:aws:elasticloadbalancing:us-east-1:100225593120:targetgroup/alliancemine-multitenant/9c6cdef38cbc7e6b \
     --query "TargetHealthDescriptions[*].[Target.Id,Target.Port,TargetHealth.State]" --output text'
```

Expect: `172.31.59.87  8082  healthy`.

## See also

- `docs/PRODUCTION_CUTOVER_9_0_0.md` — ALB target swap that put 9.0.0 live
- `docs/RUNBOOK_ALLIANCEMINE_RESTART.md` — restart procedure with deadlock kick
- `docs/INFRASTRUCTURE_REFERENCE.md` — ALB ARN, hostnames, target group

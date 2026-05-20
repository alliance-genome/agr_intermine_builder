# MouseMine public URL release — `mousemine.alliancegenome.org`

Date: 2026-05-20
Container: `mousemine-1x` on multitenant (`172.31.59.87:8084`)
Public URL: `https://mousemine.alliancegenome.org/mousemine`
Pattern: mirrors `docs/WORMMINE_MULTITENANT_SETUP.md` (wormmine release).

## What landed

A new public HTTPS endpoint for MouseMine, fronted by the existing
`alliancemine-lb` ALB. Same architecture as wormmine: ALB terminates TLS,
forwards HTTP to the container on port 8084, CDN routes via shared Caddy on
port 8888. No new EC2 / no new ECS / no new ACM cert (the wildcard
`*.alliancegenome.org` already covers).

## AWS resources created

| Resource | ARN / ID |
|---|---|
| ALB target group `mousemine` | `arn:aws:elasticloadbalancing:us-east-1:100225593120:targetgroup/mousemine/2cdeae06bfbefd67` |
| Target | `172.31.59.87:8084` (registered, healthy) |
| ALB listener rule priority 440 | host=`mousemine.alliancegenome.org` AND path=`/cdn/*` → reuse TG `wormmine-cdn` (same Caddy) |
| ALB listener rule priority 450 | host=`mousemine.alliancegenome.org` → TG `mousemine` |
| Route 53 record (public Z3IZ3D6V94JEC2) | CNAME `mousemine.alliancegenome.org` → `alliancemine-lb-309443304.us-east-1.elb.amazonaws.com` |
| Route 53 record (private Z007692222A6W93AZVSPD) | CNAME same — **required for container-side DNS, see traps below** |

## Container properties patched (runtime sed, not source backport yet)

Inside `mousemine-1x` container, in both `WEB-INF/web.properties` and
`WEB-INF/classes/intermine.properties`:

```properties
project.sitePrefix=https://mousemine.alliancegenome.org/mousemine
webapp.deploy.url=https://mousemine.alliancegenome.org
webapp.baseurl=https://mousemine.alliancegenome.org
webapp.hostname=mousemine.alliancegenome.org
head.cdn.location=https://mousemine.alliancegenome.org/cdn
webapp.path=mousemine    # unchanged
```

`global.web.properties` had `head.cdn.location` also updated.

**Important deviation from `docs/WORMMINE_MULTITENANT_SETUP.md`:** wormmine
sets `webapp.baseurl=https://wormmine.alliancegenome.org/wormmine` (path
included). We set mousemine `webapp.baseurl=https://mousemine.alliancegenome.org`
(host-only). Why — see Trap 3.

After patching: `docker restart mousemine-1x`.

## Traps hit during this release

### Trap 1 — Private Route 53 zone needed for container-side DNS

The AWS account has two hosted zones for `alliancegenome.org`:

- `Z3IZ3D6V94JEC2` — external/public (comment: "External DNS")
- `Z007692222A6W93AZVSPD` — internal/private, VPC-associated with `vpc-55522232` (comment: "Internal DNS")

Inside the VPC, AWS resolves names through the **private** zone first; only
records present in the private zone are visible to EC2 + container DNS lookups.
Records added only to the public zone are invisible to anything inside the VPC.

Adding `mousemine.alliancegenome.org` to the public zone made the URL work
from external clients (laptop, public users), but the `mousemine-1x` container
on multitenant couldn't resolve its own public hostname — Java
`UnknownHostException: mousemine.alliancegenome.org` thrown from
`XMLValidator.validate` → every `/service/query/results` call returned 500.

**Fix:** add the same CNAME to the private zone too. Verify with
`getent hosts mousemine.alliancegenome.org` on multitenant (uses libnss →
VPC DNS) — should resolve to the 5 ALB IPs.

This is implicit in the wormmine release (both zones already had the record
when the wormmine docs were written), but never called out. Future mine
releases must write to **both** zones in the same step.

### Trap 2 — Java `InetAddress` DNS cache

`java.net.InetAddress.getAllByName` caches DNS lookups inside the JVM. The
negative-cache TTL is 10s by default (`networkaddress.cache.negative.ttl`),
but Java versions differ — some cache "host not found" for the JVM lifetime
unless the property is set. OpenJDK 8 in this container caches
negative results long enough that restart was the only reliable way to clear
them after Trap 1 was fixed.

**Fix:** `docker restart mousemine-1x` after VPC DNS resolves. Verify
inside the container:

```bash
docker exec mousemine-1x bash -c "getent hosts mousemine.alliancegenome.org"
# expect 5 ALB IPs
```

Permanent fix would be setting `-Dsun.net.inetaddr.ttl=30 -Dsun.net.inetaddr.negative.ttl=10`
in Tomcat's `CATALINA_OPTS`. Not done here; restart sufficed.

### Trap 3 — `webapp.baseurl` "host-only" vs "with-path" trade-off

The wormmine doc convention sets `webapp.baseurl=https://wormmine.alliancegenome.org/wormmine`
(path included). On mousemine this produced two visible failures:

1. **Doubled path in popup links.** `bagDetails.do` JSP emits
   `var webappUrl = "${webapp.baseurl}/${webapp.path}/";` →
   `https://mousemine.alliancegenome.org/mousemine/mousemine/` — every
   "Matches" popup link in enrichment widgets pointed at a doubled-path URL
   that returns 302 to the single-path version (works for static asset GETs
   but breaks JS that expects 200 with body).

2. **Doubled path in XSD URL → query/results 500.** `XMLValidator.validate`
   in InterMine 1.x builds the schema URL as
   `${webapp.baseurl}/webservice/query.xsd` but **also** through some code
   path that concatenates path twice, producing
   `https://mousemine.alliancegenome.org/mousemine/mousemine/webservice/query.xsd`.
   That URL returns HTTP 302 (redirect to single-path) but `URL.openStream()`
   in the JVM does not follow redirects for the schema source, so XML
   validation fails on every query → 500.

**Fix used here:** set `webapp.baseurl=https://mousemine.alliancegenome.org`
(host-only). With this:

- `webappUrl` JS = `https://mousemine.alliancegenome.org/mousemine/` (single path)
- XSD URL = `https://mousemine.alliancegenome.org/mousemine/webservice/query.xsd` (single path, 200)
- `project.sitePrefix=https://mousemine.alliancegenome.org/mousemine` (still
  contains path for code paths that read sitePrefix instead of baseurl)

**Note:** wormmine prod has the same `webappUrl` doubled-path bug — confirmed
by `curl https://wormmine.alliancegenome.org/wormmine/bagDetails.do?bagName=AllGenes | grep webappUrl`
returns `/wormmine/wormmine/`. Nobody noticed because wormmine "Matches"
popups in enrichment widgets are not exercised by external users. The
underlying framework JSP bug exists in both mines; mousemine just exposes it
because its enrichment widgets ARE exercised (yesterday's rc20-era widget
fix story).

Whether to backport this host-only baseurl to wormmine is a separate call.
Doing so could fix wormmine's silent popup bug but might break Struts `<base>`
tag behavior in places that rely on baseurl including the mine path. Leave
that for a follow-on session that can browser-test wormmine in addition to
mousemine.

## Verification (post-release)

```bash
ALB_IP=$(dig +short alliancemine-lb-309443304.us-east-1.elb.amazonaws.com @8.8.8.8 | head -1)
R="--resolve mousemine.alliancegenome.org:443:$ALB_IP --max-time 30"
H="https://mousemine.alliancegenome.org/mousemine"

# Smoke
curl -sS $R $H/service/version          # → 25
curl -sS -o /dev/null -w "%{http_code}\n" $R $H/begin.do  # → 200

# Query/results (XSD validation path)
Q='<query model="genomic" view="Gene.primaryIdentifier Gene.symbol"><constraint path="Gene.symbol" op="=" value="Brca1"/></query>'
curl -sS $R "$H/service/query/results?query=$(python3 -c 'import sys,urllib.parse;print(urllib.parse.quote(sys.argv[1]))' "$Q")&format=tab&size=3"
# → 3 rows with Brca1 ids

# Enrichment widgets (3 we fixed in docs/MOUSEMINE_ENRICHMENT_WIDGET_FIX_2026_05_15.md)
for w in mp_enrichment_for_feature emapa_enrichment_for_feature disease_enrichment_for_feature; do
  curl -sS $R "$H/service/list/enrichment?widget=$w&list=Mouse+DNA+Repair+Genes&maxp=1.0&correction=Holm-Bonferroni&format=json" | python3 -c "import json,sys; d=json.load(sys.stdin); print(d.get('wasSuccessful'), len(d.get('results') or []))"
done
# → True 197 / True 30 / True 3

# Doubled-path check
curl -sS $R "$H/bagDetails.do?bagName=Mouse+DNA+Repair+Genes" | grep 'var webappUrl'
# → var webappUrl = "https://mousemine.alliancegenome.org/mousemine/";
# (single-path; NOT /mousemine/mousemine/)

# CDN
curl -sS -o /dev/null -w "%{http_code}\n" $R "$H/../cdn/js/jquery/2.0.3/jquery.min.js"
# → 200
```

All eight checks pass as of release.

## Persistence

The 6 patched properties live in the unpacked WAR
(`/usr/local/tomcat/webapps/mousemine/WEB-INF/{web,classes/intermine,global.web}.properties`).
They survive container restart but **do not survive**:

- Image rebuild from `docker/mousemine/` (template `webapp.baseurl`
  defaults are unchanged in this repo)
- `ant remove-webapp release-webapp` from the build container on
  AllianceMineDev (would re-bake whatever `~/.intermine/mousemine.properties`
  in that container has — currently `webapp.baseurl=http://172.31.59.87:8084/mousemine`
  per the maintainer's earlier edit)
- A `docker compose down` + `up` cycle that recreates the container from
  the image

**Source-backport TODO** (deferred per maintainer request not to
auto-modify build-container config without browser-validating the public
URL end-to-end):

1. `docker/mousemine/properties/mousemine.properties.template` — keep
   `webapp.baseurl=${WEBAPP_BASEURL}` but document the host-only requirement
   in `.env.example`. Currently the comment says generic; needs explicit
   "do not include `/mousemine` suffix — see `MOUSEMINE_PUBLIC_URL_RELEASE_2026_05_20.md`".
2. AllianceMineDev `mousemine` build container `/root/.intermine/mousemine.properties`
   — drop `/mousemine` from `webapp.baseurl`, sync the other 5 URL props to
   the production values so `ant default release-webapp` from that container
   ships them.

Until those land, any redeploy from AllianceMineDev will reintroduce the
doubled-path + 500-on-query bugs and require this same sed + restart loop.

## Cross-references

- `docs/WORMMINE_MULTITENANT_SETUP.md` — pattern this release copies (TG /
  rule / R53 / Caddy / RemoteIpValve)
- `docs/MOUSEMINE_ENRICHMENT_WIDGET_FIX_2026_05_15.md` — yesterday's
  `os.query.max-time` bump that made enrichment widgets work at all
- `docs/PRODUCTION_CUTOVER_RC20.md` — alliancemine rc20 cutover (similar
  ALB-swap pattern, single ALB-multitenant TG with target-port change)
- `docs/cleanup_amplify_nginx/README.md` — concurrent Amplify/nginx
  cleanup; mousemine has no analog rules in agr_ui Amplify (was a deferred
  decision in that doc)

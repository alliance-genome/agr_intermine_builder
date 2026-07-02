# MouseMine CDN Fix — 2026-07-01

MouseMine's Templates page (and the query-builder / results UI) rendered blank/non-functional — "templates page not loading, queries don't return results" — while the site itself was up. Root cause: the front-end **CDN was pointed at a raw internal HTTP address**, which browsers block on the public HTTPS site. This doc records the diagnosis and the fix, because it will recur if the container is recreated from the baked image.

## Symptom

- `https://mousemine.alliancegenome.org/mousemine/` loads (HTTP 200), pages return full HTML.
- But the **Templates page is inert** and **queries submitted from the UI never return**.
- `curl` probes all looked healthy (200 on `begin.do`, `templates.do`, `/service/query`, `/service/templates`) — because the **HTML is fine; it's the client-side JavaScript that fails.**
- Browser console (the smoking gun):
  ```
  ReferenceError: Can't find variable: jQuery   (jquery.syntax.js, notifications.js, shim.js, templates.do:435 …)
  Error: ƒ missing jQuery!                       (intermine.js)
  ```

## Root cause

InterMine loads all front-end libraries (jQuery, underscore, backbone, imjs, font-awesome…) through the `head.cdn.location` property. MouseMine had it set to the **raw internal Caddy mirror**:

```
# /usr/local/tomcat/webapps/mousemine/WEB-INF/global.web.properties  (line 63)
head.cdn.location = http://172.31.59.87:8888
```

So the served page tried to load:
```
http://172.31.59.87:8888/js/jquery/2.0.3/jquery.min.js
```
which fails for every real browser on the public HTTPS site, for **two** reasons:

1. **Mixed content** — the page is `https://…` but the script is `http://…`; browsers **block** insecure resources on a secure page.
2. **Non-routable** — `172.31.59.87` is a private VPC IP; a user's browser can't reach it from the internet regardless.

jQuery never loads → every InterMine JS bundle throws `Can't find variable: jQuery` → Templates page, query builder, and results UI are all dead. Only mousemine had this; the other mines point `head.cdn.location` at a **public HTTPS** URL (`https://cdn.intermine.org`, `https://intermine-cdn.alliancegenome.org`, etc.).

This is the `head.cdn.location` / `cdn.intermine.org` trap noted in `CLAUDE.md` and `feedback_intermine_solr_traps`.

## The fix

The Caddy CDN mirror on the host (`172.31.59.87:8888`) is healthy, **and the ALB already routes `mousemine.alliancegenome.org/cdn/*` to it** — verified:
```
curl https://mousemine.alliancegenome.org/cdn/js/jquery/2.0.3/jquery.min.js   → 200
```
So the fix is a one-line change to a **public, same-origin, HTTPS** path:

```
head.cdn.location = http://172.31.59.87:8888
                  ↓
head.cdn.location = https://mousemine.alliancegenome.org/cdn
```

Applied at runtime + restart:
```bash
docker exec mousemine-1x sh -c '
  cp   /usr/local/tomcat/webapps/mousemine/WEB-INF/global.web.properties{,.bak.cdn}
  sed -i "s|head.cdn.location = http://172.31.59.87:8888|head.cdn.location = https://mousemine.alliancegenome.org/cdn|" \
       /usr/local/tomcat/webapps/mousemine/WEB-INF/global.web.properties'
docker restart mousemine-1x
```

`head.cdn.location` is read at webapp startup, so a restart is required. **No Lucene re-extract cost** — mousemine-1x bind-mounts its keyword-search index (`/home/ec2-user/mousemine-data/keyword_search_index`), so the index persists across restarts.

### Verification
```
served templates.do → src="https://mousemine.alliancegenome.org/cdn/js/jquery/2.0.3/jquery.min.js"
that URL              → HTTP 200
```
Hard-refresh (Cmd+Shift+R) to clear the browser's cached broken JS; Templates + queries then work.

## ⚠️ This is a runtime edit — permanent fix still needed

- mousemine-1x runs the **baked image** `100225593120.dkr.ecr.us-east-1.amazonaws.com/agr_mousemine:runtime-1x`; the WAR/config is inside the image.
- The `sed` edit lives in the container's writable layer: it **survives `docker restart`** but **reverts on `docker rm` + recreate** (or an image re-pull).
- **Permanent fix:** bake `head.cdn.location = https://mousemine.alliancegenome.org/cdn` into the source `global.web.properties` and rebuild/re-push the `agr_mousemine:runtime-1x` image (or patch the baked WAR). Until then, if mousemine's Templates page goes blank after a container recreate, re-apply the `sed` above.

## Why curl didn't catch it (note for future triage)

A 200 on `templates.do` / `/service/*` only proves the **server** works. A JS-driven "page not loading" is a **client-side** failure — always check the **browser console** (or diff the served `<script src=…>` URLs against what actually loads). The tell here was `Can't find variable: jQuery`.

## Related

- `CLAUDE.md` — `head.cdn.location` / Solr-URL runtime-patch traps
- `feedback_intermine_solr_traps` memory — the `/cdn/*` ALB rule + Caddy mirror pattern
- `INCIDENT_MULTITENANT_REBOOT_2026_06_23.md` — the ENI-hairpin DNAT (same "container can't reach the host's private IP" family)
- `MOUSEMINE_RC3_BUILD_2026_06_16.md` — rc3 build (still not cut over; rc2 in production)

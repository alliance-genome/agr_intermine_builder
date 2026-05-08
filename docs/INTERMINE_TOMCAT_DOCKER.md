# InterMine Tomcat Docker Image — Current + Future

Reference doc for the Tomcat container that runs deployed InterMine WARs
(alliancemine, mousemine, wormmine, flymine). Captures what the current
image is, what patches every container needs, how alliancemine 9.0.0 got
patched by hand on 2026-05-01, and the path to a baked-in
`intermine-tomcat:agr-runtime` image.

## 1. Current state

| Asset | What it is | Where |
|---|---|---|
| `intermine-tomcat:latest` | Upstream Tomcat 9.0.112 + JDK 11 image (vanilla) | Pulled to multitenant `172.31.59.87` |
| `legacy/tomcat/` | Old Tomcat 8.5.3 + JDK 8 Dockerfile | repo only — **too old for InterMine 9** (needs Java 11) |
| `legacy/tomcat/configs/web_context.xml` | Manager `RemoteAddrValve` commented out | Reusable patch source |
| `docker/intermine-tomcat/` | Empty placeholder dir | Future home of `agr-runtime` image |
| `agr_alliancemine:runtime-9.0.0` (ECR) | Snapshot of the running 9.0.0 container — Tomcat + WAR + all 4 patches applied at runtime | ECR |

So today the **only patched image** is the runtime ECR snapshot, which
mixes Tomcat patches + a specific deployed WAR. Useful for disaster
recovery of one specific mine, useless as a base for future deploys.

## 2. The four patches every fresh Tomcat container needs

InterMine assumes a Tomcat that:
1. Trusts ALB / proxy IP forwarding
2. Allows remote-deploy via the manager webapp
3. Accepts uploads up to ~500 MB (WARs are ~130 MB and cargo redeploy
   sends the full file)
4. Has a `manager-script` user that matches what the WAR's
   `webapp.manager` / `webapp.password` properties expect

None of these are in stock Tomcat.

### Patch 1 — `server.xml`: RemoteIpValve

**Why:** ALB sits in front of Tomcat. Without this valve, the webapp
sees the ALB's internal IP, not the real client. Breaks logging, breaks
`webapp.baseurl` URL generation in REST responses.

**Where:** `$CATALINA_HOME/conf/server.xml`

**What to add (inside `<Host name="localhost">`):**

```xml
<Valve className="org.apache.catalina.valves.RemoteIpValve"
       internalProxies="10\.\d+\.\d+\.\d+|172\.(1[6-9]|2[0-9]|3[0-1])\.\d+\.\d+|192\.168\.\d+\.\d+|127\.\d+\.\d+\.\d+"
       protocolHeader="x-forwarded-proto"
       remoteIpHeader="x-forwarded-for" />
```

`internalProxies` regex matches RFC1918 + loopback. ALB IPs come from
the VPC CIDR which is already covered by `10.x` / `172.16-31.x`.

### Patch 2 — Manager `context.xml`: remove RemoteAddrValve

**Why:** Default Tomcat manager rejects any connection not from
localhost. The build pipeline pushes WARs from `AllianceMineDev`
(172.31.60.197) → multitenant Tomcat (172.31.59.87) via
`cargoRedeployRemote`. Remote source = blocked without this patch.

**Where:** `$CATALINA_HOME/webapps/manager/META-INF/context.xml`

**What to change:**

```xml
<Context antiResourceLocking="false" privileged="true">
  <!-- COMMENTED OUT, was:
  <Valve className="org.apache.catalina.valves.RemoteAddrValve"
         allow="127\.\d+\.\d+\.\d+|::1|0:0:0:0:0:0:0:1" />
  -->
  <Manager sessionAttributeValueClassNameFilter="..."/>
</Context>
```

`legacy/tomcat/configs/web_context.xml` already has this patch — copy
verbatim.

### Patch 3 — Manager `web.xml`: upload limit 500 MB

**Why:** Default `max-file-size` is 50 MB. AllianceMine 9.0.0 WAR is
~132 MB, mousemine WAR likewise. Cargo redeploy fails with HTTP 413
unless raised.

**Where:** `$CATALINA_HOME/webapps/manager/WEB-INF/web.xml`

**What to change** — find the `<servlet>` for `HTMLManager` (or `Manager`),
edit / add `<multipart-config>`:

```xml
<multipart-config>
  <max-file-size>524288000</max-file-size>
  <max-request-size>524288000</max-request-size>
</multipart-config>
```

500 MB = 524288000 bytes. Same for both fields.

### Patch 4 — `tomcat-users.xml`: manager-script user

**Why:** Cargo redeploy uses HTTP Basic auth against the manager-script
role. Stock Tomcat ships zero users. InterMine `webapp.manager` and
`webapp.password` properties default to `manager` / `manager` — those
must exist in `tomcat-users.xml`.

**Where:** `$CATALINA_HOME/conf/tomcat-users.xml`

**What to add:**

```xml
<role rolename="manager-script"/>
<role rolename="manager-gui"/>
<role rolename="manager-status"/>
<user username="manager" password="manager"
      roles="manager-script,manager-gui,manager-status"/>
```

**Production note:** Real deploys should override the password via env
var injection at container startup, not bake `manager`/`manager` into
the image. Image lives in ECR; anyone with pull access reads the file.
See §5 for the templating pattern.

## 3. How alliancemine 9.0.0 got these patches (2026-05-01, by hand)

For the historical record, since this is exactly what we want to
eliminate:

```bash
# 1. Start vanilla intermine-tomcat:latest
docker run -d --name alliancemine-9.0.0 \
  -p 8082:8080 \
  --add-host agr.stage.alliancemine.solr.server:172.17.0.1 \
  -e JAVA_OPTS="-Dorg.apache.el.parser.SKIP_IDENTIFIER_CHECK=true -Xmx4g -Xms2g" \
  intermine-tomcat:latest

# 2. Apply patch 1 — server.xml RemoteIpValve
docker exec -i alliancemine-9.0.0 \
  sed -i 's|<Host name="localhost"|...RemoteIpValve here...&|' /usr/local/tomcat/conf/server.xml

# 3. Apply patch 2 — manager context.xml
docker cp manager-context.xml \
  alliancemine-9.0.0:/usr/local/tomcat/webapps/manager/META-INF/context.xml

# 4. Apply patch 3 — manager web.xml upload limit
docker exec -i alliancemine-9.0.0 \
  sed -i 's|<max-file-size>52428800|<max-file-size>524288000|' \
  /usr/local/tomcat/webapps/manager/WEB-INF/web.xml

# 5. Apply patch 4 — tomcat-users.xml
docker cp tomcat-users.xml \
  alliancemine-9.0.0:/usr/local/tomcat/conf/tomcat-users.xml

# 6. Restart so all four patches take effect
docker restart alliancemine-9.0.0
```

Six steps per container. Done by hand. Easy to skip one (e.g. forget
patch 1 → ALB redirects break silently → debug session for hours).

The whole point of building `intermine-tomcat:agr-runtime` is to make
steps 2-5 disappear.

## 4. Runtime knobs — NOT baked, supplied at `docker run` time

These are container-instance-specific. Bake them into the image and
you can't reuse it across mines / environments.

### `--add-host` for Solr aliases

InterMine WARs hardcode Solr URLs via `webapp.deploy.url`-style
properties. If those URLs use a hostname (not IP), the container's
`/etc/hosts` needs a mapping to the Solr host (the Docker host gateway
on multitenant = `172.17.0.1`).

| Mine | Hostname in WAR | Resolves to |
|---|---|---|
| alliancemine | `agr.stage.alliancemine.solr.server` | `172.17.0.1` (Docker host gateway, where Solr 8983 listens) |
| mousemine | uses `localhost:8983` (needs runtime prop patch to `172.17.0.1:8983` — Solr is on the host, not in the container) | — |
| wormmine | varies — check `web.properties` | — |

For mines that hardcode `localhost:8983` like mousemine, the cleanest
fix is to **patch the deployed WAR's `web.properties`** post-deploy
(replace `localhost` with `172.17.0.1`). Adding a `--add-host` doesn't
help when the hostname is `localhost` — that's already mapped to the
container itself.

### `JAVA_OPTS`

```
-Dorg.apache.el.parser.SKIP_IDENTIFIER_CHECK=true -Xmx4g -Xms2g
```

`SKIP_IDENTIFIER_CHECK` works around an EL parser regression that breaks
some InterMine JSP fragments (since at least InterMine 1.x → 9.0.0).
Heap sizing tunable per mine: alliancemine 4G, mousemine probably 4-6G,
wormmine 4G. Set via `-e JAVA_OPTS=...`.

### Port mapping

| Mine | Host port |
|---|---|
| alliancemine | 8082 |
| mousemine | 8084 (proposed) |
| wormmine | 8083 |
| flymine | 8085 |

Convention: even-numbered ports starting at 8082, increment per mine.
ALB rule routes by hostname → target group → port.

### WAR

Deployed AFTER container starts, via `cargoRedeployRemote` from the
build container. Not baked. WAR ships from `AllianceMineDev` to
`http://multitenant:<port>/manager/text/deploy?path=/<mine>`.

## 5. The future: `intermine-tomcat:agr-runtime`

Goal: a Dockerfile that produces an image where steps 2-5 of §3 are
already done. `docker run` becomes:

```bash
docker run -d --name <mine>-<version> \
  -p <port>:8080 \
  --add-host <solr-alias>:172.17.0.1 \
  -e JAVA_OPTS="..." \
  -e MANAGER_PASSWORD=<from-secrets-manager> \
  intermine-tomcat:agr-runtime
```

No `docker exec sed`, no `docker cp`. WAR deployed via cargo as before.

### Proposed structure

```
docker/intermine-tomcat/
├── Dockerfile
├── README.md                          # links here, build instructions
├── conf/
│   ├── server.xml                     # full file with RemoteIpValve baked
│   └── tomcat-users.template.xml      # password from env at runtime
├── manager/
│   ├── context.xml                    # RemoteAddrValve removed
│   └── web.xml                        # 500 MB upload limit
└── entrypoint.sh                      # envsubst tomcat-users.xml then exec catalina
```

### Dockerfile sketch

```dockerfile
FROM tomcat:9.0-jdk11-temurin

# Patch 1: server.xml with RemoteIpValve
COPY conf/server.xml /usr/local/tomcat/conf/server.xml

# Patch 2: manager context (remove RemoteAddrValve)
COPY manager/context.xml /usr/local/tomcat/webapps/manager/META-INF/context.xml

# Patch 3: manager web.xml (500 MB upload limit)
COPY manager/web.xml /usr/local/tomcat/webapps/manager/WEB-INF/web.xml

# Patch 4: tomcat-users template (password injected at runtime)
COPY conf/tomcat-users.template.xml /usr/local/tomcat/conf/tomcat-users.template.xml

# Templating entrypoint
COPY entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

ENV MANAGER_USER=manager
ENV MANAGER_PASSWORD=manager

EXPOSE 8080
ENTRYPOINT ["/entrypoint.sh"]
CMD ["catalina.sh", "run"]
```

### `entrypoint.sh` sketch

```bash
#!/bin/bash
set -e

# Render tomcat-users.xml from template, password from env
envsubst < /usr/local/tomcat/conf/tomcat-users.template.xml \
  > /usr/local/tomcat/conf/tomcat-users.xml

# Hand off to Tomcat
exec "$@"
```

### Build + push

```bash
docker build -t intermine-tomcat:agr-runtime docker/intermine-tomcat/
docker tag intermine-tomcat:agr-runtime \
  100225593120.dkr.ecr.us-east-1.amazonaws.com/agr_intermine_tomcat:agr-runtime
docker push 100225593120.dkr.ecr.us-east-1.amazonaws.com/agr_intermine_tomcat:agr-runtime
```

ECR repo `agr_intermine_tomcat` would be new — separate from per-mine
`agr_alliancemine` etc.

### Rollout

1. Build + push image
2. **Test on mousemine first** (port 8084, no production traffic) —
   deploy WAR, verify all 4 patches active, smoke test
3. Snapshot the running mousemine container to ECR (per
   `MULTITENANT_BACKUP_RESTORE.md`)
4. Apply same image to wormmine + flymine new deploys
5. **Last:** retrofit alliancemine 9.0.0. Stop, replace base image, redeploy
   WAR. Use ECR snapshot of current state as rollback insurance.

## 6. Open issues to decide before building

These shape the final Dockerfile:

1. **Manager password — bake or template?** Template via envsubst is
   safer. Build arg simpler. Pick one.
2. **`internalProxies` regex — bake or env?** Different VPCs, different
   CIDRs. If we ever run in a non-AGR VPC, baked regex would need
   rebuild. Env var is cleaner.
3. **JAVA_OPTS default in image?** Some baseline (`SKIP_IDENTIFIER_CHECK`)
   could be baked, heap left to runtime. Or skip entirely.
4. **`webapp.deploy.url` patcher script?** Some WARs hardcode a deploy
   URL that's wrong post-deploy (e.g. `http://localhost:8080`). A
   sidecar entrypoint step that runs a regex over the deployed WAR
   files could fix `webapp.baseurl`, `webapp.deploy.url`,
   `superuser.account`, Solr URLs all at once. This is the "property
   patcher" from POST_9_0_0_PLANNING.md Tier 1. Could live here, or in
   a separate post-deploy script. Decide scope.
5. **Multistage build?** Probably no — base `tomcat:9.0-jdk11-temurin`
   is already optimized. Just COPY patches over it.
6. **Health endpoint?** Add `<status-code>200</status-code>` page or
   rely on `/manager/text/serverinfo` for ALB health checks. Today ALB
   uses `/{mine}/service/version` which only works after WAR is
   deployed. Pre-WAR, container looks UNHEALTHY which is fine but
   confuses oncall.

## 7. References

- `docs/RUNTIME_CONTAINER_BACKUP.md` — Why we snapshot the running
  container (captures current FS including hand-applied patches)
- `docs/MULTITENANT_BACKUP_RESTORE.md` — Backup/restore scripts for the
  whole multitenant container set
- `docs/PRODUCTION_CUTOVER_9_0_0.md` — First place these 4 patches were
  applied, exact commands
- `docs/POST_9_0_0_PLANNING.md` Tier 1 — Where the property patcher +
  baked-image work is queued
- `docs/INCIDENT_2026_04_30_to_05_01.md` — What happens when no
  reproducible image exists
- Upstream InterMine Tomcat install:
  https://intermine.readthedocs.io/en/latest/system-requirements/software/tomcat/

## 8. InterMine 1.x — different patches, different Tomcat

§2-7 cover **InterMine 9.x** (alliancemine 9.0.0). InterMine 1.x mines
(mousemine, wormmine, flymine) need a **different** patch set on a
**different** Tomcat version.

### 8.1 Version compat

| Component | InterMine 9.x | InterMine 1.x |
|---|---|---|
| Tomcat | 9.0.112 | **8.5** (per InterMine 1.x docs) |
| Java | JDK 11 | JDK 11 (works) — InterMine 1.x docs say Java 8 but Java 11 runs fine |
| Build | Gradle | **Ant 1.10.x** |
| Servlet API | 4.0 | 3.1 |
| Reuse `intermine-tomcat:latest` (Tomcat 9)? | ✓ yes | ❌ no — Tomcat 9 stricter, breaks 1.x JSPs |

So we need **two** patched images:

- `intermine-tomcat:agr-runtime` (Tomcat 9, JDK 11) → alliancemine 9.x
- `intermine-tomcat:agr-1x-runtime` (Tomcat 8.5, JDK 11) → mousemine, wormmine, flymine

### 8.2 The four patches for InterMine 1.x (per upstream docs)

Source: https://intermine.readthedocs.io/en/1.x/system-requirements/software/tomcat/

#### Patch 1 (1.x) — `tomcat-users.xml`: same as 9.x

```xml
<tomcat-users>
   <role rolename="manager-gui"/>
   <role rolename="manager-script"/>
   <user username="manager" password="manager" roles="manager-gui,manager-script"/>
</tomcat-users>
```

Same as 9.x (§2 patch 4). The username/password matches the
`webapp.manager` / `webapp.password` properties baked into the WAR.

#### Patch 2 (1.x) — `context.xml`: session + cookie attributes

**Why:** without these, sessions break across path changes (e.g.
`/mousemine` → `/mousemine/portal.do`) — user gets new session each
click, list builder forgets selections, login redirects fail.

**Where:** `$CATALINA_HOME/conf/context.xml`

```xml
<Context sessionCookiePath="/"
         useHttpOnly="false"
         clearReferencesStopTimerThreads="true">
  <!-- ... -->
</Context>
```

| Attribute | Why |
|---|---|
| `sessionCookiePath="/"` | Cookie scope = whole host, not just `/mousemine`. Stops session loss on path change. |
| `useHttpOnly="false"` | Allow JS access to JSESSIONID. Required by InterMine's old IM-tables AJAX. |
| `clearReferencesStopTimerThreads="true"` | Hikari ScheduledExecutor refs cleared on undeploy. Prevents OOM after redeploys. |

This is **different** from 9.x context.xml which is the **manager**
context.xml (RemoteAddrValve removed). 1.x patches the **global**
context.xml. Both files exist:

| Path | 9.x | 1.x |
|---|---|---|
| `$CATALINA_HOME/conf/context.xml` (global) | unchanged | session/cookie attrs |
| `$CATALINA_HOME/webapps/manager/META-INF/context.xml` | RemoteAddrValve removed | likely also needs RemoteAddrValve removed for cargo redeploy |

**Mousemine implication:** if cargo redeploy is used (likely yes, same
build pipeline pattern), the manager's context.xml needs the same fix
as 9.x (patch §2.2). So 1.x = 9.x manager patches + 1.x global context.

#### Patch 3 (1.x) — `server.xml`: UTF-8 on Connectors

**Why:** without `URIEncoding="UTF-8"`, gene names with accents /
non-ASCII (e.g. fly genes from FlyBase that include Greek letters)
break URL routing. Permalinks fail.

**Where:** `$CATALINA_HOME/conf/server.xml` — every `<Connector>`

```xml
<Connector port="8080"
           protocol="HTTP/1.1"
           connectionTimeout="20000"
           redirectPort="8443"
           URIEncoding="UTF-8" />
```

**Diff from 9.x:** Tomcat 9 defaults `URIEncoding` to UTF-8, no patch
needed. Tomcat 8.5 defaults to ISO-8859-1, must override.

**RemoteIpValve (9.x patch §2.1) for 1.x:** also useful if 1.x mines
sit behind ALB. mousemine prod would. Add it the same way:

```xml
<Valve className="org.apache.catalina.valves.RemoteIpValve"
       internalProxies="10\.\d+\.\d+\.\d+|172\.(1[6-9]|2[0-9]|3[0-1])\.\d+\.\d+|192\.168\.\d+\.\d+|127\.\d+\.\d+\.\d+"
       protocolHeader="x-forwarded-proto"
       remoteIpHeader="x-forwarded-for" />
```

#### Patch 4 (1.x) — `catalina.properties`: SKIP_IDENTIFIER_CHECK

**Why:** Tomcat 7+ enforces EL parser keyword rules. InterMine JSPs use
Java keywords as variable names (`new`, `class`). Strict EL rejects
them.

**Where:** `$CATALINA_HOME/conf/catalina.properties` (preferred) or
`bin/setenv.sh`

Add line to `catalina.properties`:
```
org.apache.el.parser.SKIP_IDENTIFIER_CHECK=true
```

Or via env at runtime (cleaner for Docker):
```bash
docker run -e JAVA_OPTS="-Dorg.apache.el.parser.SKIP_IDENTIFIER_CHECK=true" ...
```

**Same flag as 9.x.** Just configured at the system-property level
instead of JVM-arg level. Both work.

#### Bonus: manager web.xml upload limit (also 1.x)

Same as 9.x patch §2.3. Mousemine WAR is ~150 MB, default Tomcat 8.5
upload limit is 50 MB — must raise to 500 MB. Path differs slightly
in Tomcat 8.5 vs 9 but content identical:

```xml
<multipart-config>
  <max-file-size>524288000</max-file-size>
  <max-request-size>524288000</max-request-size>
</multipart-config>
```

#### Bonus: heap sizing in `setenv.sh`

Per InterMine 1.x docs:
```
TOMCAT_OPTS="-Xmx256m -Xms128m"
```

256 MB is way too small for InterMine production. AGR mines should run
4-6 GB heap. Override via:
```bash
docker run -e JAVA_OPTS="-Xmx4g -Xms2g -Dorg.apache.el.parser.SKIP_IDENTIFIER_CHECK=true" ...
```

### 8.3 Patch comparison table

| Patch | InterMine 9.x | InterMine 1.x |
|---|---|---|
| Manager `tomcat-users.xml` (manager/manager) | ✓ same | ✓ same |
| Manager `context.xml` (RemoteAddrValve removed) | ✓ | ✓ (assumed — needed for cargo redeploy) |
| Manager `web.xml` (500 MB upload) | ✓ | ✓ |
| `server.xml` RemoteIpValve | ✓ for ALB | ✓ same if behind ALB |
| `server.xml` Connector `URIEncoding="UTF-8"` | not needed (default) | ✓ needed |
| `conf/context.xml` `sessionCookiePath` etc. | not needed | ✓ needed |
| `SKIP_IDENTIFIER_CHECK` | via JAVA_OPTS at runtime | via JAVA_OPTS at runtime (or catalina.properties) |
| Heap sizing | 4G+ via JAVA_OPTS | 4G+ via JAVA_OPTS |

**Net:** 1.x has **2 extra patches** (UTF-8 connector, global context.xml
session attrs) and the **same 4 manager patches** as 9.x.

### 8.4 Proposed `intermine-tomcat:agr-1x-runtime` structure

```
docker/intermine-tomcat-1x/
├── Dockerfile                         # FROM tomcat:8.5-jdk11-temurin
├── README.md
├── conf/
│   ├── server.xml                     # RemoteIpValve + Connector UTF-8
│   ├── context.xml                    # session/cookie attrs
│   ├── tomcat-users.template.xml      # manager creds
│   └── catalina.properties            # SKIP_IDENTIFIER_CHECK
├── manager/
│   ├── context.xml                    # RemoteAddrValve removed
│   └── web.xml                        # 500 MB upload limit
└── entrypoint.sh                      # envsubst tomcat-users.xml
```

Identical structure to `agr-runtime` but Tomcat 8.5 base + 2 extra
patches.

Build:
```bash
docker build -t intermine-tomcat:agr-1x-runtime docker/intermine-tomcat-1x/
docker tag intermine-tomcat:agr-1x-runtime \
  100225593120.dkr.ecr.us-east-1.amazonaws.com/agr_intermine_tomcat:agr-1x-runtime
docker push 100225593120.dkr.ecr.us-east-1.amazonaws.com/agr_intermine_tomcat:agr-1x-runtime
```

### 8.5 Mousemine-specific runtime concerns

| Item | Value | How handled |
|---|---|---|
| Solr URL in WAR | `localhost:8983/solr/mousemine-search` | Patch deployed WAR's `web.properties` post-deploy: `localhost` → `172.17.0.1` |
| `webapp.baseurl` baked | `http://localhost:8080` | Patch post-deploy → real URL |
| `superuser.account` | `superuser@mail_account` | Patch post-deploy |
| DB | `mousemine_db` on RDS (already populated) | env var or property patch |
| Profile DB | `mousemine_userprofile` on RDS | Same |
| Solr cores required | `mousemine-search`, `mousemine-autocomplete` | **Must create on multitenant Solr 8983 before deploy** |
| Port | 8084 | `-p 8084:8080` |
| ALB | None for now (test deploy) | Direct hit `http://172.31.59.87:8084/mousemine/...` |

### 8.6 Mousemine Solr cores — preflight

Before deploying mousemine WAR, ensure:

```bash
curl -sS http://172.31.59.87:8983/solr/mousemine-search/admin/ping
curl -sS http://172.31.59.87:8983/solr/mousemine-autocomplete/admin/ping
```

If 404, create with `scripts/create_solr_cores.py` adapted for
mousemine (today it's alliancemine-targeted), or via Solr CLI:

```bash
solr create_core -c mousemine-search
solr create_core -c mousemine-autocomplete
```

Then `create-search-index` postprocess step must be re-run to populate
them. Or expect empty Solr until first reindex.

## 9. Status as of 2026-05-04

- alliancemine 9.0.0: running on `intermine-tomcat:latest` (Tomcat 9 +
  JDK 11) + 4 hand patches. ECR snapshot exists.
- mousemine: InterMine 1.x. Postprocess just completed (transfer-sequences
  + indexes + summarise-objectstore). WAR not yet built. Test deployment
  on port 8084 planned on **`intermine-tomcat:agr-1x-runtime`** (Tomcat
  8.5 + JDK 11) — different base image from alliancemine because 1.x
  needs different patches (UTF-8 connector, global context.xml session
  attrs).
- wormmine, flymine: also InterMine 1.x — would benefit from same
  `agr-1x-runtime` image once built for mousemine.

## 10. Build order recommendation

1. **Build `agr-1x-runtime` first** (covers 3 of 4 mines: mousemine,
   wormmine, flymine).
2. Test on mousemine port 8084.
3. Snapshot mousemine running container to ECR.
4. **Then build `agr-runtime`** (alliancemine 9.x only — last because
   prod traffic at risk).
5. Retrofit alliancemine 9.0.0 to use `agr-runtime`. Use ECR snapshot
   from May 1 as rollback insurance.

This order means the riskier 9.x retrofit benefits from lessons learned
on the 1.x build.

# intermine-tomcat:agr-5x-runtime

Tomcat 9.0.122 + JDK 11 (Temurin) with the InterMine 5.x patches baked in. Built for the
MouseMine 5.1 port (`mousemine_im5_port`); usable for any InterMine 5.x WAR.

Sibling of `docker/intermine-tomcat-1x/` (Tomcat 8.5, InterMine 1.x mines). Background and the
reasoning behind each patch: `docs/INTERMINE_TOMCAT_DOCKER.md`.

## What is patched

Every patched file is the stock Tomcat 9.0.122 file with small edits marked `AGR PATCH`.

| File | Patch | Why |
|---|---|---|
| `conf/context.xml` | `sessionCookiePath="/"`, `useHttpOnly="false"`, `clearReferencesStopTimerThreads="true"` | InterMine 5 Tomcat requirements: one session across `/<mine>/*`, im-tables AJAX reads JSESSIONID, no timer-thread leak on redeploy |
| `conf/server.xml` | `URIEncoding="UTF-8"` on 8080 | Already the Tomcat 9 default; explicit so it survives a base change |
| `conf/server.xml` | `maxParameterCount="10000"` on 8080 | 9.0.122 ships 1000; InterMine list/result-table forms can post more and Tomcat drops the excess silently. 10000 = what the 1.x mines run with |
| `conf/server.xml` | `RemoteIpValve` (RFC1918 + loopback proxies) | Real client IP and scheme behind the ALB; correct URLs in REST responses |
| `conf/server.xml` | `requestAttributesEnabled="true"` on `AccessLogValve` | Access log records the forwarded client IP, not the ALB |
| `conf/catalina.properties` | `org.apache.el.parser.SKIP_IDENTIFIER_CHECK=true` | InterMine JSPs use Java keywords as EL identifiers |
| `webapps/manager` | copied in from `webapps.dist` | Tomcat docker images ship no webapps |
| `manager/META-INF/context.xml` | `RemoteCIDRValve` commented out | Lets the build host cargo-deploy WARs. Tomcat 9 uses RemoteCIDRValve where 8.5 used RemoteAddrValve |
| `manager/WEB-INF/web.xml` | upload limit 50 MB → 500 MB | WARs are 130–150 MB |
| `conf/tomcat-users.xml` | rendered at start from `MANAGER_USER` / `MANAGER_PASSWORD` | manager-script user for cargo; never baked into the image |

## Build

```bash
docker build -t intermine-tomcat:agr-5x-runtime docker/intermine-tomcat-5x/
```

## Run

```bash
docker run -d --name mousemine-5x -p 8088:8080 \
  -e MANAGER_PASSWORD="$(openssl rand -hex 16)" \
  -e JAVA_OPTS="-Xmx6g -Xms2g" \
  intermine-tomcat:agr-5x-runtime
```

Runtime, per mine (not baked): host port, heap (`JAVA_OPTS`), manager password, `--add-host`
for any Solr hostname the WAR uses. The WAR is deployed afterwards (cargo, or a read-only bind
mount at `/usr/local/tomcat/webapps/<mine>.war` as FlyMine does).

## Not handled here

- WAR-baked properties (`webapp.baseurl`, `superuser.account`, Solr URLs in
  `keyword_search.properties` / `objectstoresummary.config.properties`) — set at WAR build time.
- Mail: the SES fix is baked into the WAR (`scripts/bake_mail_into_war.sh`), not the image.

# intermine-tomcat:agr-1x-runtime

Tomcat 8.5 + JDK 11 with all InterMine 1.x patches baked in.

Used for: **mousemine, wormmine, flymine** (any AGR mine on InterMine 1.x).

For InterMine 9.x (alliancemine), use `intermine-tomcat:agr-runtime`
(separate image, Tomcat 9.0.112 base — see `../intermine-tomcat/`).

## What's baked

| Patch | File | Why |
|---|---|---|
| Manager users (`manager-script` role) | `conf/tomcat-users.xml` (rendered at runtime from template) | Cargo redeploy auth |
| Manager `RemoteAddrValve` removed | `webapps/manager/META-INF/context.xml` | Allow remote WAR push |
| Manager 500 MB upload limit | `webapps/manager/WEB-INF/web.xml` | InterMine WARs are ~150 MB |
| `URIEncoding="UTF-8"` on Connector | `conf/server.xml` (full-file COPY) | Tomcat 8.5 default ISO-8859-1 breaks gene names with accents |
| `RemoteIpValve` | `conf/server.xml` (full-file COPY) | ALB / proxy IP forwarding |
| Session cookie attrs | `conf/context.xml` | Stop session loss on path change, allow JS access to JSESSIONID, prevent thread leak on undeploy |
| `SKIP_IDENTIFIER_CHECK` | `conf/catalina.properties` | InterMine JSPs use `class`, `new` as variable names |

Full reasoning + InterMine docs reference: `docs/INTERMINE_TOMCAT_DOCKER.md` §8.

## Build

```bash
docker build -t intermine-tomcat:agr-1x-runtime .

# Push to ECR (first-time: aws ecr create-repository --repository-name agr_intermine_tomcat)
aws ecr get-login-password --region us-east-1 \
  | docker login --username AWS --password-stdin 100225593120.dkr.ecr.us-east-1.amazonaws.com

docker tag intermine-tomcat:agr-1x-runtime \
  100225593120.dkr.ecr.us-east-1.amazonaws.com/agr_intermine_tomcat:agr-1x-runtime

docker push 100225593120.dkr.ecr.us-east-1.amazonaws.com/agr_intermine_tomcat:agr-1x-runtime
```

## Run (mousemine on port 8084)

```bash
docker run -d --name mousemine-1x \
  -p 8084:8080 \
  -e MANAGER_USER=manager \
  -e MANAGER_PASSWORD="$(openssl rand -hex 16)" \
  -e JAVA_OPTS="-Dorg.apache.el.parser.SKIP_IDENTIFIER_CHECK=true -Xmx4g -Xms2g" \
  intermine-tomcat:agr-1x-runtime
```

Save the rendered `MANAGER_PASSWORD` somewhere safe — needed for the
WAR's `webapp.password` property when deploying the WAR.

## Verify patches after start

```bash
# Manager reachable + creds work
curl -sS -u manager:<password> http://localhost:8084/manager/text/list

# Connector UTF-8
docker exec mousemine-1x grep URIEncoding /usr/local/tomcat/conf/server.xml

# RemoteIpValve present
docker exec mousemine-1x grep RemoteIpValve /usr/local/tomcat/conf/server.xml

# Session cookie attrs
docker exec mousemine-1x grep sessionCookiePath /usr/local/tomcat/conf/context.xml

# SKIP_IDENTIFIER_CHECK
docker exec mousemine-1x grep SKIP_IDENTIFIER_CHECK /usr/local/tomcat/conf/catalina.properties

# Manager upload limit (500 MB)
docker exec mousemine-1x grep max-file-size /usr/local/tomcat/webapps/manager/WEB-INF/web.xml
```

All five should return non-empty matches. `URIEncoding` and `RemoteIpValve`
should specifically show the patched values, not stock.

## Deploy mousemine WAR

After container is running and verified:

```bash
# From mousemine build container or AllianceMineDev
cd /intermine/mousemine/webapp
ant default                                          # builds mousemine.war

# Push WAR via cargoRedeployRemote (uses ant)
ant -Dtarget.host=multitenant -Dtarget.port=8084 cargo-redeploy
```

Or manually with curl:

```bash
curl -sS -u manager:<password> --upload-file mousemine.war \
  "http://multitenant:8084/manager/text/deploy?path=/mousemine&update=true"
```

Watch logs:

```bash
docker logs -f mousemine-1x
```

## Post-deploy property patches

The deployed WAR has `web.properties` baked at build time. Mousemine has:

```
webapp.baseurl=http://localhost:8080
webapp.deploy.url=http://localhost:8080
index.solrurl=http://localhost:8983/solr/mousemine-search
autocomplete.solrurl=http://localhost:8983/solr/mousemine-autocomplete
```

`localhost` from the container's POV = the container itself, NOT the
host running Solr. Patch post-deploy:

```bash
WAR_PATH=/usr/local/tomcat/webapps/mousemine
docker exec mousemine-1x bash -c "
  sed -i 's|localhost:8080|172.31.59.87:8084|g' \
    $WAR_PATH/WEB-INF/web.properties
  sed -i 's|localhost:8983|172.17.0.1:8983|g' \
    $WAR_PATH/WEB-INF/web.properties
"
docker restart mousemine-1x
```

`172.17.0.1` = Docker host gateway (where Solr 8983 listens on multitenant).

## Smoke test

```bash
curl -sS http://multitenant:8084/mousemine/service/version
# expect: a small integer like "35"

curl -sS http://multitenant:8084/mousemine/service/release
# expect: release version string

curl -sS "http://multitenant:8084/mousemine/service/templates" | head -c 500
# expect: JSON array of templates
```

## Snapshot to ECR

After confirmed-good deploy, snapshot per
`docs/MULTITENANT_BACKUP_RESTORE.md`:

```bash
./scripts/backup_multitenant_runtimes.sh -c mousemine-1x
```

## See also

- `docs/INTERMINE_TOMCAT_DOCKER.md` — Full background, what each patch
  does, comparison with 9.x
- `docs/MULTITENANT_BACKUP_RESTORE.md` — Snapshot/restore the running
  container
- `docs/POST_9_0_0_PLANNING.md` Tier 1 — This image resolves the
  "every container needs hand patches" pain

# InterMine Multi-Tenant Deployment

This document describes the setup of InterMine instances (WormMine, AllianceMine) on the multi-tenant EC2 instance.

## Architecture Overview

```
                    ┌──────────────────────────────────────┐
                    │        Internet / Users              │
                    └──────────────────┬───────────────────┘
                                       │
                    ┌──────────────────┴───────────────────┐
                    │                                      │
                    ▼                                      ▼
┌──────────────────────────────────┐   ┌──────────────────────────────────┐
│ wormmine.alliancegenome.org      │   │ Direct IP Access (HTTP)          │
│ (Route 53 CNAME → ALB)           │   │ 44.206.248.213                   │
│ HTTPS via ALB                    │   │                                  │
└──────────────────┬───────────────┘   └──────────────────┬───────────────┘
                   │                                      │
                   ▼                                      │
┌──────────────────────────────────┐                      │
│   alliancemine-lb (ALB)          │                      │
│   HTTPS :443 (TLS termination)   │                      │
│                                  │                      │
│   Rule 390: /cdn/* → :8888       │                      │
│   Rule 400: /* → :8081           │                      │
└──────────────────┬───────────────┘                      │
                   │                                      │
                   └──────────────────┬───────────────────┘
                                      ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                    Multi-Tenant EC2 Instance                                 │
│                    Private: 172.31.59.87  |  Public: 44.206.248.213         │
│                                                                              │
│  ┌────────────────┐  ┌────────────────┐  ┌────────────────────────────────┐ │
│  │   Solr         │  │   Caddy        │  │  Tomcat Containers             │ │
│  │   :8983        │  │   :8888 (CDN)  │  │                                │ │
│  │                │  │                │  │  ┌─────────────────────────┐   │ │
│  │ Cores:         │  │  /data/cdn     │  │  │ alliancemine :8080      │   │ │
│  │ - alliancemine-│  │                │  │  │ AllianceMine 8.3.0 WAR  │   │ │
│  │   search       │  │  Systemd       │  │  └─────────────────────────┘   │ │
│  │ - alliancemine-│  │  enabled       │  │                                │ │
│  │   autocomplete │  │                │  │  ┌─────────────────────────┐   │ │
│  │ - wormmine-    │  │                │  │  │ wormmine :8081          │   │ │
│  │   search       │  │                │  │  │ WormMine WAR            │   │ │
│  │ - wormmine-    │  │                │  │  │ + RemoteIpValve         │   │ │
│  │   autocomplete │  │                │  │  └─────────────────────────┘   │ │
│  └────────────────┘  └────────────────┘  └────────────────────────────────┘ │
│                                                                              │
│  ┌──────────────────────────────────────────────────────────────────────┐   │
│  │   BlueGenes Container :5000                                          │   │
│  │   Default Mine: AllianceMine (http://172.31.59.87:8080/alliancemine) │   │
│  │   Additional: WormMine (http://44.206.248.213:8081/wormmine)         │   │
│  └──────────────────────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────────────────────┘
                                      │
                                      ▼
                    ┌─────────────────────────────────────┐
                    │   AWS RDS PostgreSQL 15             │
                    │   intermine-postgres.cmnnhlso7wdi.  │
                    │   us-east-1.rds.amazonaws.com       │
                    │                                     │
                    │   AllianceMine:                     │
                    │   - alliancemine_8_3_0              │
                    │   - alliancemine_userprofile        │
                    │   - alliancemine_items              │
                    │                                     │
                    │   WormMine:                         │
                    │   - wormmine_final                  │
                    │   - wormmine_userprofile            │
                    │   - wormmine_items                  │
                    └─────────────────────────────────────┘
```

## Components

### 1. EC2 Instance
- **Instance ID**: i-0e7fbfd5a4440063e
- **Name**: InterMine-MultiTenant
- **Type**: c7i.4xlarge
- **Private IP**: 172.31.59.87
- **Public IP**: 44.206.248.213
- **OS**: Amazon Linux 2023

### 2. Solr (Native Installation)
- **Version**: 8.11.2
- **Port**: 8983
- **Cores**:
  - `alliancemine-search` - AllianceMine search index (1.1 GB)
  - `alliancemine-autocomplete` - AllianceMine autocomplete index (19 MB)
  - `wormmine-search` - WormMine search index (768 MB)
  - `wormmine-autocomplete` - WormMine autocomplete index (21 MB)

### 3. Tomcat Containers (Docker)

#### AllianceMine
- **Container Name**: alliancemine
- **Image**: intermine-tomcat:latest
- **Port**: 8080 (mapped to container 8080)
- **Version**: 8.3.0
- **Databases**: `alliancemine_8_3_0`, `alliancemine_userprofile`
- **Access**: http://44.206.248.213:8080/alliancemine

#### WormMine
- **Container Name**: wormmine
- **Image**: intermine-tomcat:latest
- **Port**: 8081 (mapped to container 8080)
- **Manager Credentials**: Stored in `/data/mines/wormmine_credentials.txt`

#### RemoteIpValve Configuration

Since the ALB terminates TLS and forwards requests as HTTP, Tomcat needs the `RemoteIpValve` to properly recognize HTTPS requests via the `X-Forwarded-Proto` header. This is critical for the Struts `<html:base/>` tag to generate correct HTTPS URLs.

In `/usr/local/tomcat/conf/server.xml`, add before the `<Host>` element:
```xml
<Valve className="org.apache.catalina.valves.RemoteIpValve"
       remoteIpHeader="X-Forwarded-For"
       protocolHeader="X-Forwarded-Proto" />
```

**Note**: This change is made inside the container and will be lost if the container is recreated. For permanent changes, modify the Dockerfile or use a bind mount for server.xml.

### 4. CDN (Caddy)
- **Version**: 2.8.4
- **Port**: 8888
- **Document Root**: /data/cdn (cloned from https://github.com/intermine/CDN)
- **Purpose**: Serves static JS/CSS resources for InterMine webapp

### 5. Database (RDS)
- **Host**: intermine-postgres.cmnnhlso7wdi.us-east-1.rds.amazonaws.com
- **Port**: 5432
- **Databases**:
  - `wormmine_final` - Production data
  - `wormmine_userprofile` - User profiles
  - `wormmine_items` - Common target items

## Configuration Files

### wormmine.properties (Key Settings)
Located in container at `/opt/intermine/.intermine/wormmine.properties`:

```properties
# Database
db.production.datasource.serverName=intermine-postgres.cmnnhlso7wdi.us-east-1.rds.amazonaws.com
db.production.datasource.databaseName=wormmine_final

# Webapp - HTTPS URL for public access
webapp.baseurl=https://wormmine.alliancegenome.org/wormmine
webapp.deploy.url=https://wormmine.alliancegenome.org
webapp.path=wormmine
webapp.port=8081
webapp.hostname=172.31.59.87

# Solr
index.solrurl=http://172.31.59.87:8983/solr/wormmine-search
autocomplete.solrurl=http://172.31.59.87:8983/solr/wormmine-autocomplete

# CDN - served via ALB with /cdn/* path routing
head.cdn.location=https://wormmine.alliancegenome.org/cdn

# Deployment
webapp.manager=manager
webapp.password=<see credentials file>
```

### global.web.properties (CDN Setting)
Located at `/opt/intermine/wormmine/webapp/src/main/webapp/WEB-INF/global.web.properties`:

```properties
# Note: This file is bundled in the WAR but the wormmine.properties setting takes precedence
head.cdn.location = http://localhost:8888
```

### keyword_search.properties
Located at `/opt/intermine/wormmine/dbmodel/resources/keyword_search.properties`:

```properties
index.solrurl = http://172.31.59.87:8983/solr/wormmine-search
```

### objectstoresummary.config.properties
Located at `/opt/intermine/wormmine/dbmodel/resources/objectstoresummary.config.properties`:

```properties
autocomplete.solrurl = http://172.31.59.87:8983/solr/wormmine-autocomplete
```

## Build Container (AllianceMineDev)

The WormMine build environment runs on AllianceMineDev (172.31.60.197):

- **Container ID**: 9e6d706430da
- **Image**: wormmine-unified:stage
- **Purpose**: Compile WormMine, build indexes, deploy WAR

### Gradle Commands (from build container)

```bash
# Access build container
docker exec -it 9e6d706430da bash

# Navigate to WormMine
cd /opt/intermine/wormmine

# Build and deploy webapp
./gradlew cargoRedeployRemote

# Create Solr search index
./gradlew postprocess -Pprocess=create-search-index

# Create Solr autocomplete index
./gradlew postprocess -Pprocess=create-autocomplete-index
```

## Deployment Steps

### 1. Add a New Mine to Multi-Tenant

SSH to the multi-tenant instance:
```bash
ssh -i ~/.ssh/AGR-ssl3.pem ec2-user@172.31.59.87
```

Use the add-mine script:
```bash
sudo add-mine <mine_name> <port>
# Example: sudo add-mine wormmine 8081
```

This creates:
- Solr cores (`<mine>-search` and `<mine>-autocomplete`)
- Tomcat container on specified port
- Logs directory at `/data/mines/logs/<mine>/`
- Credentials file at `/data/mines/<mine>_credentials.txt`

### 2. Deploy WAR from Build Container

From AllianceMineDev:
```bash
docker exec 9e6d706430da bash -c "cd /opt/intermine/wormmine && ./gradlew cargoRedeployRemote"
```

### 3. Create Solr Indexes

From AllianceMineDev (after database is built):
```bash
# Search index
docker exec 9e6d706430da bash -c "cd /opt/intermine/wormmine && ./gradlew postprocess -Pprocess=create-search-index"

# Autocomplete index
docker exec 9e6d706430da bash -c "cd /opt/intermine/wormmine && ./gradlew postprocess -Pprocess=create-autocomplete-index"
```

## Access URLs

### Public HTTP Access (via Public IP)
| Service | Port | URL |
|---------|------|-----|
| AllianceMine | 8080 | http://44.206.248.213:8080/alliancemine/ |
| WormMine | 8081 | http://44.206.248.213:8081/wormmine/ |
| BlueGenes | 5000 | http://44.206.248.213:5000/bluegenes/ |
| CDN | 8888 | http://44.206.248.213:8888/ |

### Via VPN (Internal)
- **AllianceMine Webapp**: http://172.31.59.87:8080/alliancemine
- **WormMine Webapp**: http://172.31.59.87:8081/wormmine
- **Solr Admin**: http://172.31.59.87:8983/solr
- **CDN**: http://172.31.59.87:8888
- **Tomcat Manager (WormMine)**: http://172.31.59.87:8081/manager/html

### API Endpoints (WormMine)
- **Search**: http://172.31.59.87:8081/wormmine/service/search?q=<term>
- **Query**: http://172.31.59.87:8081/wormmine/service/query/results
- **Model**: http://172.31.59.87:8081/wormmine/service/model
- **Version**: http://172.31.59.87:8081/wormmine/service/version

### API Endpoints (AllianceMine)
- **Search**: http://172.31.59.87:8080/alliancemine/service/search?q=<term>
- **Query**: http://172.31.59.87:8080/alliancemine/service/query/results
- **Model**: http://172.31.59.87:8080/alliancemine/service/model
- **Version**: http://172.31.59.87:8080/alliancemine/service/version

## Troubleshooting

### Check Tomcat Logs
```bash
ssh -i ~/.ssh/AGR-ssl3.pem ec2-user@172.31.59.87
docker logs wormmine --tail 100
sudo cat /data/mines/logs/wormmine/catalina.2025-12-04.log
```

### Check Solr Status
```bash
curl http://172.31.59.87:8983/solr/admin/cores?action=STATUS
```

### Check CDN
```bash
curl -I http://172.31.59.87:8888/
```

### Restart Services
```bash
# Restart Tomcat containers
docker restart alliancemine
docker restart wormmine

# Restart Caddy (managed by systemd)
sudo systemctl restart caddy

# Restart Solr
sudo systemctl restart solr
```

### Mixed Content / HTTPS Issues

If CSS/JS/images aren't loading on the HTTPS URL:

1. **Check the `<base>` tag** - should be HTTPS:
   ```bash
   curl -sL "https://wormmine.alliancegenome.org/wormmine" | grep '<base'
   # Should show: <base href="https://wormmine.alliancegenome.org/wormmine/...
   ```

2. **If base tag shows HTTP**, verify RemoteIpValve is configured:
   ```bash
   ssh -i ~/.ssh/AGR-ssl3.pem ec2-user@172.31.59.87 -o ProxyJump=blast \
     "docker exec wormmine grep RemoteIpValve /usr/local/tomcat/conf/server.xml"
   ```

3. **Add RemoteIpValve if missing** (inside container):
   ```bash
   docker exec wormmine sed -i 's|<Host name="localhost"|<Valve className="org.apache.catalina.valves.RemoteIpValve" remoteIpHeader="X-Forwarded-For" protocolHeader="X-Forwarded-Proto" />\n        <Host name="localhost"|' /usr/local/tomcat/conf/server.xml
   docker restart wormmine
   ```

4. **Check CDN URLs** - should use `https://wormmine.alliancegenome.org/cdn/`:
   ```bash
   curl -sL "https://wormmine.alliancegenome.org/wormmine" | grep -oE 'src="[^"]*cdn[^"]*"' | head -3
   ```

5. **Verify CDN routing**:
   ```bash
   curl -sI "https://wormmine.alliancegenome.org/cdn/js/jquery/2.0.3/jquery.min.js" | head -3
   # Should return HTTP/2 200
   ```

## Important Notes

1. **webapp.baseurl**: For HTTPS access via ALB, set to `https://wormmine.alliancegenome.org/wormmine`. The RemoteIpValve in Tomcat handles the HTTP→HTTPS translation.

2. **CDN Location**: Set to `https://wormmine.alliancegenome.org/cdn` for production. The ALB routes `/cdn/*` requests to Caddy on port 8888 with path stripping.

3. **RemoteIpValve**: Required in Tomcat server.xml when behind ALB. Without it, the `<html:base/>` Struts tag generates HTTP URLs causing mixed content issues.

4. **Solr URLs in Properties**: Multiple files need updating:
   - `wormmine.properties`
   - `keyword_search.properties`
   - `objectstoresummary.config.properties`

5. **Security Groups**: Port 8081 is accessible for the ALB health checks. Port 8888 is accessible for CDN routing.

## Files Modified

In WormMine source (`/opt/intermine/wormmine/`):
- `webapp/src/main/webapp/WEB-INF/global.web.properties` - CDN location
- `webapp/src/main/webapp/footer.jsp` - Footer with local image URLs
- `dbmodel/resources/keyword_search.properties` - Solr search URL
- `dbmodel/resources/objectstoresummary.config.properties` - Solr autocomplete URL

In InterMine config (`/opt/intermine/.intermine/`):
- `wormmine.properties` - All mine configuration

## User Profile Database

The userprofile database was restored from `profile_dump_Dec25.sql`:

```bash
# Terminate existing connections
PGPASSWORD='<password>' psql -h intermine-postgres.cmnnhlso7wdi.us-east-1.rds.amazonaws.com -U postgres \
  -c "SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname = 'wormmine_userprofile' AND pid <> pg_backend_pid();"

# Drop and recreate
PGPASSWORD='<password>' psql -h intermine-postgres.cmnnhlso7wdi.us-east-1.rds.amazonaws.com -U postgres \
  -c "DROP DATABASE IF EXISTS wormmine_userprofile;"
PGPASSWORD='<password>' psql -h intermine-postgres.cmnnhlso7wdi.us-east-1.rds.amazonaws.com -U postgres \
  -c "CREATE DATABASE wormmine_userprofile;"

# Restore dump
PGPASSWORD='<password>' psql -h intermine-postgres.cmnnhlso7wdi.us-east-1.rds.amazonaws.com -U postgres \
  -d wormmine_userprofile < profile_dump_Dec25.sql
```

### Superuser Configuration
In `wormmine.properties`:
```properties
superuser.account=staff@wormbase.org
superuser.password=<contact admin for password>
```

## Footer Images (CDN)

The WormBase footer images are hosted locally on the CDN since wormbase.org blocks direct access (Cloudflare).

### Image Location
```
/data/cdn/img/wormbase/
├── agr_founding_member_badge.png
├── caltech_logo.png
├── embl_ebi_logo_white.svg
├── global-core-biodata-resources.svg
└── oicr_logo_white.png
```

### Footer Image URLs
In `footer.jsp`, images are referenced using the HTTPS CDN URL:
```
https://wormmine.alliancegenome.org/cdn/img/wormbase/<image_file>
```

**Important**: Footer images must use HTTPS URLs to avoid mixed content blocking. The images are served via the ALB `/cdn/*` routing rule to Caddy on port 8888.

### Updating Footer Images
1. Download images manually (wormbase.org uses Cloudflare protection)
2. Upload to multi-tenant CDN:
   ```bash
   scp -i ~/.ssh/AGR-ssl3.pem <images> ec2-user@172.31.59.87:/data/cdn/img/wormbase/
   ```
3. Redeploy if footer.jsp was modified:
   ```bash
   ssh -i ~/.ssh/AGR-ssl3.pem ec2-user@AllianceMineDev \
     "docker exec wormmine bash -c 'cd /opt/intermine/wormmine && ./gradlew cargoRedeployRemote'"
   ```

## Public Access

### Production HTTPS URL

**WormMine is accessible via HTTPS at:**
```
https://wormmine.alliancegenome.org/wormmine
```

This URL is routed through the Alliance load balancer (`alliancemine-lb`) with a valid SSL certificate.

### AWS Infrastructure for wormmine.alliancegenome.org

The HTTPS access is configured using the same pattern as BlueGenes and AllianceMine:

```
wormmine.alliancegenome.org (Route 53 CNAME)
    → alliancemine-lb (ALB, port 443 HTTPS)
        → Rule 400: Host = "wormmine.alliancegenome.org" → wormmine target group
            → 172.31.59.87:8081 (Multi-tenant EC2)
```

**Components Created:**

1. **Target Group**: `wormmine`
   - ARN: `arn:aws:elasticloadbalancing:us-east-1:100225593120:targetgroup/wormmine/d1847ce03cf42970`
   - Target: 172.31.59.87:8081
   - Health Check: `/wormmine/service/version`

2. **Target Group**: `wormmine-cdn`
   - ARN: `arn:aws:elasticloadbalancing:us-east-1:100225593120:targetgroup/wormmine-cdn/...`
   - Target: 172.31.59.87:8888
   - Health Check: `/`
   - Purpose: Routes CDN requests (`/cdn/*`) to Caddy server

3. **ALB Listener Rules**:
   - Rule 390 (Priority): Path pattern `/cdn/*` AND Host = `wormmine.alliancegenome.org` → `wormmine-cdn` target group
   - Rule 400 (Priority): Host header = `wormmine.alliancegenome.org` → `wormmine` target group

4. **Route 53 CNAME**:
   - `wormmine.alliancegenome.org` → `alliancemine-lb-309443304.us-east-1.elb.amazonaws.com`

**Complete ALB Rules on alliancemine-lb:**
```
├── Rule 100: Host = "alliancemine-cdn-proxy.alliancegenome.org" → alliancemine-cdn
├── Rule 200: Host = "alliancemine-proxy.alliancegenome.org" → alliancemine
├── Rule 300: Host = "bluegenes-proxy.alliancegenome.org" → bluegenes
├── Rule 390: Path = "/cdn/*" AND Host = "wormmine.alliancegenome.org" → wormmine-cdn
├── Rule 400: Host = "wormmine.alliancegenome.org" → wormmine
└── Default: Return 404
```

### Other Access Methods

WormMine is also accessible via:
- **Internal (VPN)**: http://172.31.59.87:8081/wormmine
- **Public HTTP**: http://44.206.248.213:8081/wormmine (port 8081 opened in security group)

### Security Group Changes

The following ports were added to security group `sg-0415cab61ab6b45c5` for public HTTP access:

| Port | Service | Purpose |
|------|---------|---------|
| 8080 | AllianceMine | Public HTTP access to AllianceMine webapp |
| 8081 | WormMine | Public HTTP access to WormMine webapp |
| 5000 | BlueGenes | Public HTTP access to BlueGenes UI |

```bash
# AllianceMine (port 8080)
aws ec2 authorize-security-group-ingress --group-id sg-0415cab61ab6b45c5 --protocol tcp --port 8080 --cidr 0.0.0.0/0

# WormMine (port 8081)
aws ec2 authorize-security-group-ingress --group-id sg-0415cab61ab6b45c5 --protocol tcp --port 8081 --cidr 0.0.0.0/0

# BlueGenes (port 5000)
aws ec2 authorize-security-group-ingress --group-id sg-0415cab61ab6b45c5 --protocol tcp --port 5000 --cidr 0.0.0.0/0
```

### Caddy CDN Configuration

Caddy serves static CDN files. HTTPS termination is handled by the ALB, so Caddy only needs to serve HTTP on port 8888.

**/etc/caddy/Caddyfile**:
```
# CDN server - handles both /cdn/* and root paths
:8888 {
    # Strip /cdn prefix if present (for ALB routing)
    handle_path /cdn/* {
        root * /data/cdn
        file_server
        header Access-Control-Allow-Origin *
    }

    # Also serve from root for backward compatibility
    handle {
        root * /data/cdn
        file_server
        header Access-Control-Allow-Origin *
    }
}
```

**Note**: The ALB routes `https://wormmine.alliancegenome.org/cdn/*` requests to Caddy on port 8888. The `handle_path /cdn/*` directive strips the `/cdn` prefix so files are served from `/data/cdn/` root.

### BlueGenes Integration

With the new HTTPS URL, BlueGenes can now access WormMine without mixed content issues.

**Update BlueGenes Configuration** (in `agr_bluegenes/config/defaults/config.edn`):
```clojure
{:root "https://wormmine.alliancegenome.org/wormmine"
 :name "WormMine"
 :namespace "wormmine"}
```

After updating, rebuild and redeploy BlueGenes (see BlueGenes Deployment section).

## BlueGenes Deployment

BlueGenes can be deployed either on the multi-tenant instance (for WormMine) or on AllianceMine (production).

### ECR Image Tags

- `latest` - Production BlueGenes for AllianceMine
- `wormmine` - WormMine-specific BlueGenes for multi-tenant deployment

### Multi-Tenant Deployment (WormMine)

BlueGenes runs on the multi-tenant instance alongside WormMine:

- **Container Name**: bluegenes
- **Port**: 5000
- **Image**: `100225593120.dkr.ecr.us-east-1.amazonaws.com/agr_bluegenes:wormmine`
- **Access URL**: http://44.206.248.213:5000/bluegenes/wormmine

**WormMine Config** (in `config/defaults/config.edn`):
```clojure
{:root "http://44.206.248.213:8081/wormmine"
 :name "WormMine"
 :namespace "wormmine"}
```

**Security Group**: Port 5000 opened in `sg-0415cab61ab6b45c5`

### Build and Deploy Process

```bash
# 1. Update config in agr_bluegenes/config/defaults/config.edn
# (This is the config that gets bundled into the JAR)

# 2. Build JAR
cd /path/to/agr_bluegenes
rm -rf target
lein uberjar

# 3. Build Docker image with tag
docker build -t agr_bluegenes:wormmine .

# 4. Tag and push to ECR
aws ecr get-login-password --region us-east-1 | docker login --username AWS --password-stdin 100225593120.dkr.ecr.us-east-1.amazonaws.com
docker tag agr_bluegenes:wormmine 100225593120.dkr.ecr.us-east-1.amazonaws.com/agr_bluegenes:wormmine
docker push 100225593120.dkr.ecr.us-east-1.amazonaws.com/agr_bluegenes:wormmine

# 5. Deploy on Multi-Tenant
ssh -i ~/.ssh/AGR-ssl3.pem ec2-user@172.31.59.87 -o ProxyJump=blast
aws ecr get-login-password --region us-east-1 | sudo docker login --username AWS --password-stdin 100225593120.dkr.ecr.us-east-1.amazonaws.com
sudo docker pull 100225593120.dkr.ecr.us-east-1.amazonaws.com/agr_bluegenes:wormmine
sudo docker stop bluegenes && sudo docker rm bluegenes
sudo docker run -d --name bluegenes -p 5000:5000 100225593120.dkr.ecr.us-east-1.amazonaws.com/agr_bluegenes:wormmine
```

### Production Deployment (AllianceMine)

For production at `https://www.alliancegenome.org/bluegenes`:

```bash
# Use :latest tag instead of :wormmine
docker tag agr_bluegenes:latest 100225593120.dkr.ecr.us-east-1.amazonaws.com/agr_bluegenes:latest
docker push 100225593120.dkr.ecr.us-east-1.amazonaws.com/agr_bluegenes:latest

# Deploy on AllianceMine
ssh AllianceMine
sudo docker pull 100225593120.dkr.ecr.us-east-1.amazonaws.com/agr_bluegenes:latest
sudo docker stop bluegenes && sudo docker rm bluegenes
sudo docker run -d --name bluegenes -p 5000:5000 100225593120.dkr.ecr.us-east-1.amazonaws.com/agr_bluegenes:latest
```

### Important: Config Location

BlueGenes config is read from `config/defaults/config.edn` which gets bundled into the JAR as `config.edn`. The `config/prod/config.edn` is copied to the Docker image but may not be used at runtime depending on the classpath order.

**Always update `config/defaults/config.edn`** when changing mine configurations.

### Running Services on Multi-Tenant

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                    Multi-Tenant EC2 Instance                                 │
│                      (172.31.59.87 / 44.206.248.213)                        │
│                                                                              │
│  ┌────────────────┐  ┌────────────────┐  ┌────────────────────────────────┐ │
│  │   Solr         │  │   Caddy        │  │  Tomcat Containers             │ │
│  │   :8983        │  │   :8888 (CDN)  │  │                                │ │
│  │                │  │                │  │  ┌─────────────────────────┐   │ │
│  │ Cores:         │  │  /data/cdn     │  │  │ alliancemine :8080      │   │ │
│  │ - alliancemine-│  │                │  │  │ AllianceMine 8.3.0 WAR  │   │ │
│  │   search       │  │  Systemd       │  │  └─────────────────────────┘   │ │
│  │ - alliancemine-│  │  enabled       │  │                                │ │
│  │   autocomplete │  │                │  │  ┌─────────────────────────┐   │ │
│  │ - wormmine-    │  │                │  │  │ wormmine :8081          │   │ │
│  │   search       │  │                │  │  │ WormMine WAR            │   │ │
│  │ - wormmine-    │  │                │  │  │ + RemoteIpValve         │   │ │
│  │   autocomplete │  │                │  │  └─────────────────────────┘   │ │
│  └────────────────┘  └────────────────┘  └────────────────────────────────┘ │
│                                                                              │
│  ┌──────────────────────────────────────────────────────────────────────┐   │
│  │   BlueGenes Container :5000                                          │   │
│  │   Default Mine: AllianceMine (http://172.31.59.87:8080/alliancemine) │   │
│  │   Additional: WormMine (http://44.206.248.213:8081/wormmine)         │   │
│  └──────────────────────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────────────────────┘
```

### Caddy Systemd Service

Caddy is managed by systemd to ensure it starts automatically on boot:

**/etc/systemd/system/caddy.service**:
```ini
[Unit]
Description=Caddy CDN Server
After=network.target

[Service]
ExecStart=/usr/local/bin/caddy run --config /etc/caddy/Caddyfile
ExecReload=/usr/local/bin/caddy reload --config /etc/caddy/Caddyfile
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
```

**Commands:**
```bash
# Enable on boot
sudo systemctl enable caddy

# Start/stop/restart
sudo systemctl start caddy
sudo systemctl stop caddy
sudo systemctl restart caddy

# Check status
sudo systemctl status caddy
```

# WormMine Multi-Tenant Deployment

This document describes the setup of WormMine on the InterMine multi-tenant EC2 instance.

## Architecture Overview

```
┌─────────────────────────────────────────────────────────────────┐
│                    Multi-Tenant EC2 Instance                     │
│                      (172.31.59.87)                              │
│                                                                  │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────────────┐   │
│  │   Solr       │  │   Caddy      │  │  Tomcat Container    │   │
│  │   :8983      │  │   :8888      │  │  (wormmine) :8081    │   │
│  │              │  │   (CDN)      │  │                      │   │
│  │ - wormmine-  │  │              │  │  WormMine WAR        │   │
│  │   search     │  │  /data/cdn   │  │                      │   │
│  │ - wormmine-  │  │              │  │                      │   │
│  │   autocomplete│ │              │  │                      │   │
│  └──────────────┘  └──────────────┘  └──────────────────────┘   │
│                                                                  │
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼
                    ┌──────────────────┐
                    │   AWS RDS        │
                    │   PostgreSQL     │
                    │                  │
                    │ - wormmine_final │
                    │ - wormmine_      │
                    │   userprofile    │
                    └──────────────────┘
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
  - `wormmine-search` - Main search index (6,367,684 documents)
  - `wormmine-autocomplete` - Autocomplete index (61,344 documents)

### 3. Tomcat Container (Docker)
- **Container Name**: wormmine
- **Image**: intermine-tomcat:latest
- **Port**: 8081 (mapped to container 8080)
- **Manager Credentials**: Stored in `/data/mines/wormmine_credentials.txt`

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

# Webapp
webapp.baseurl=http://172.31.59.87:8081/wormmine
webapp.path=wormmine
webapp.port=8081
webapp.hostname=172.31.59.87

# Solr
index.solrurl=http://172.31.59.87:8983/solr/wormmine-search
autocomplete.solrurl=http://172.31.59.87:8983/solr/wormmine-autocomplete

# Deployment
webapp.deploy.url=http://172.31.59.87:8081
webapp.manager=manager
webapp.password=<see credentials file>
```

### global.web.properties (CDN Setting)
Located at `/opt/intermine/wormmine/webapp/src/main/webapp/WEB-INF/global.web.properties`:

```properties
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

### Via VPN (Internal)
- **WormMine Webapp**: http://172.31.59.87:8081/wormmine
- **Solr Admin**: http://172.31.59.87:8983/solr
- **CDN**: http://172.31.59.87:8888
- **Tomcat Manager**: http://172.31.59.87:8081/manager/html

### API Endpoints
- **Search**: http://172.31.59.87:8081/wormmine/service/search?q=<term>
- **Query**: http://172.31.59.87:8081/wormmine/service/query/results
- **Model**: http://172.31.59.87:8081/wormmine/service/model
- **Version**: http://172.31.59.87:8081/wormmine/service/version

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
# Restart Tomcat container
docker restart wormmine

# Restart Caddy
sudo /usr/local/bin/caddy stop
sudo /usr/local/bin/caddy start --config /etc/caddy/Caddyfile

# Restart Solr
sudo systemctl restart solr
```

## Important Notes

1. **webapp.baseurl**: Must be set to the actual accessible URL (internal IP), not the public-facing URL. Otherwise, XML validation fails.

2. **CDN Location**: Set to `http://localhost:8888` since Caddy runs on the same instance as WormMine.

3. **Solr URLs in Properties**: Multiple files need updating:
   - `wormmine.properties`
   - `keyword_search.properties`
   - `objectstoresummary.config.properties`

4. **Security Groups**: Port 8081 is not publicly accessible. Use VPN or SSH tunnel for access.

## Files Modified

In WormMine source (`/opt/intermine/wormmine/`):
- `webapp/src/main/webapp/WEB-INF/global.web.properties` - CDN location
- `dbmodel/resources/keyword_search.properties` - Solr search URL
- `dbmodel/resources/objectstoresummary.config.properties` - Solr autocomplete URL

In InterMine config (`/opt/intermine/.intermine/`):
- `wormmine.properties` - All mine configuration

# InterMine Deployment Strategy

## Architecture Overview

### Hybrid Deployment Model
- **Docker containers**: Tomcat instances (one per mine)
- **Native installation**: Single Solr instance with multiple cores
- **AWS RDS**: PostgreSQL databases

### Component Layout

```
EC2 Instance
├── Native Solr 8.4.1 (port 8983)
│   ├── alliancemine-search
│   ├── alliancemine-autocomplete
│   ├── wormmine-search
│   ├── wormmine-autocomplete
│   └── [future-mine cores...]
│
├── Docker Containers (Tomcat)
│   ├── alliancemine-tomcat (host port 8080)
│   ├── wormmine-tomcat (host port 8081)
│   └── [future-mine containers on 8082, 8083...]
│
└── RDS PostgreSQL (external)
    ├── alliancemine_final
    ├── alliancemine_items
    ├── alliancemine_userprofile
    ├── wormmine_final
    ├── wormmine_items
    └── wormmine_userprofile
```

## Why This Approach?

### Docker for Tomcat
- **Isolation**: Each mine in its own container
- **Easy scaling**: Spin up new mines on new ports
- **Version control**: Container images track mine versions
- **Rollback**: Easy to revert to previous container version
- **Resource limits**: Can set memory/CPU per mine

### Native Solr
- **Shared resource**: More efficient than multiple Solr instances
- **Easier management**: Single backup/monitoring point
- **Proven stability**: Native installation more stable for long-running search
- **Core isolation**: Each mine has separate cores, still isolated
- **Simpler updates**: One Solr upgrade affects all mines

### RDS PostgreSQL
- **AWS managed**: Backups, HA, monitoring handled by AWS
- **Shared across mines**: Cost effective
- **Easy scaling**: Upgrade instance type as needed

---

## Deployment Workflow

### 1. Build Phase (Local/CI)

```bash
# Build AllianceMine
cd docker/alliancemine-unified
docker-compose build

# Build WormMine
cd docker/wormmine-unified
docker-compose build

# Push to ECR
docker tag alliancemine-unified:latest 100225593120.dkr.ecr.us-east-1.amazonaws.com/agr_alliancemine:latest
docker push 100225593120.dkr.ecr.us-east-1.amazonaws.com/agr_alliancemine:latest

docker tag wormmine-unified:latest 100225593120.dkr.ecr.us-east-1.amazonaws.com/agr_wormmine:latest
docker push 100225593120.dkr.ecr.us-east-1.amazonaws.com/agr_wormmine:latest
```

### 2. Data Processing Phase (Inside Container)

```bash
# Run container in manual mode
docker run -it --rm \
  -e RDS_HOST=... \
  -e RDS_PASSWORD=... \
  -v /data:/root/data \
  wormmine-unified:latest bash

# Inside container - run build
cd /opt/intermine/wormmine
./gradlew buildDB --stacktrace

# Run post-processing
./gradlew postProcess --stacktrace
```

### 3. Deployment Phase (EC2 Server)

```bash
# Pull latest image from ECR
aws ecr get-login-password --region us-east-1 | docker login --username AWS --password-stdin 100225593120.dkr.ecr.us-east-1.amazonaws.com
docker pull 100225593120.dkr.ecr.us-east-1.amazonaws.com/agr_wormmine:latest

# Stop old container
docker stop wormmine-tomcat
docker rm wormmine-tomcat

# Start new container
docker run -d \
  --name wormmine-tomcat \
  -p 8081:8080 \
  -e RDS_HOST=intermine-postgres.cmnnhlso7wdi.us-east-1.rds.amazonaws.com \
  -e RDS_PASSWORD=${RDS_PASSWORD} \
  -e SOLR_URL=http://host.docker.internal:8983/solr/wormmine-search \
  100225593120.dkr.ecr.us-east-1.amazonaws.com/agr_wormmine:latest tomcat
```

---

## Automation Ideas

### Option 1: GitHub Actions CI/CD

```yaml
name: Build and Deploy WormMine

on:
  push:
    branches: [im-298]
  workflow_dispatch:
    inputs:
      release:
        description: 'WormBase Release (e.g., WS298)'
        required: true

jobs:
  build:
    runs-on: ubuntu-latest
    steps:
      - name: Build Docker image
        run: docker-compose build

      - name: Push to ECR
        run: |
          aws ecr get-login-password | docker login ...
          docker push ...

      - name: Run data build
        run: |
          docker run ... ./gradlew buildDB

      - name: Trigger deployment
        run: |
          # Webhook to EC2 or AWS CodeDeploy
```

### Option 2: AWS CodePipeline

```
Source (GitHub) → Build (CodeBuild) → Deploy (CodeDeploy/ECS)
```

**CodeBuild**: Build Docker image, run InterMine build
**CodeDeploy**: Deploy to EC2, restart containers

### Option 3: Manual with Helper Scripts

Create deployment scripts for manual releases:

```bash
# scripts/build_release.sh WS298
#!/bin/bash
RELEASE=$1

# 1. Download data files
./scripts/download_wormbase_data.sh $RELEASE

# 2. Build Docker image
docker-compose build --build-arg WORMBASE_RELEASE=$RELEASE

# 3. Run InterMine build in container
docker run ... ./gradlew buildDB postProcess

# 4. Push to ECR
./scripts/push_to_ecr.sh wormmine $RELEASE
```

```bash
# scripts/deploy_to_production.sh wormmine WS298
#!/bin/bash
MINE=$1
RELEASE=$2

ssh ec2-user@production-server << EOF
  # Pull latest
  docker pull ecr.../agr_${MINE}:${RELEASE}

  # Stop old
  docker stop ${MINE}-tomcat
  docker rm ${MINE}-tomcat

  # Start new
  docker run -d --name ${MINE}-tomcat -p 808X:8080 ... ecr.../agr_${MINE}:${RELEASE} tomcat
EOF
```

### Option 4: Scheduled Releases (Cron + Scripts)

```bash
# On build server: /etc/cron.d/wormmine-releases
# Every 3 months on the 15th
0 2 15 */3 * /opt/intermine/scripts/auto_release.sh wormmine
```

**Auto-release script**:
1. Check WormBase for new release
2. Download data
3. Build Docker image
4. Run InterMine build
5. Run tests
6. If tests pass, deploy to staging
7. Send notification for manual production deploy

---

## Release Checklist

### Pre-Release
- [ ] Check WormBase release notes for schema changes
- [ ] Review bio-sources for compatibility
- [ ] Update project.xml if needed
- [ ] Test build locally with sample data

### Build Phase
- [ ] Download all data files from WormBase FTP
- [ ] Build Docker image with new release tag
- [ ] Run deploy.sh to process all data
- [ ] Run buildDB
- [ ] Run postProcess (including create-search-index)

### Testing Phase
- [ ] Verify database record counts
- [ ] Test web interface on staging
- [ ] Test search functionality
- [ ] Test API endpoints
- [ ] Check Solr cores are populated

### Deployment Phase
- [ ] Push image to ECR
- [ ] Deploy to staging EC2
- [ ] Run smoke tests
- [ ] Deploy to production EC2
- [ ] Update DNS if needed
- [ ] Monitor logs for errors

### Post-Release
- [ ] Backup databases
- [ ] Document any issues
- [ ] Update release notes
- [ ] Clean up old Docker images

---

## Solr Core Management

### Create cores for new mine

```bash
# On EC2 server
/opt/solr/bin/solr create -c newmine-search
/opt/solr/bin/solr create -c newmine-autocomplete
```

### Backup Solr cores

```bash
# Snapshot
curl "http://localhost:8983/solr/wormmine-search/replication?command=backup&location=/backup/solr&name=wormmine-ws298"

# Or full data directory backup
tar -czf solr-backup-$(date +%Y%m%d).tar.gz /var/solr/data
```

### Monitoring Solr

```bash
# Check status
curl http://localhost:8983/solr/admin/cores?action=STATUS

# Check specific core
curl http://localhost:8983/solr/wormmine-search/admin/ping

# Monitor memory
curl http://localhost:8983/solr/admin/info/system
```

---

## Database Management

### Create new mine databases

```bash
psql -h $RDS_HOST -U postgres -d postgres
CREATE DATABASE newmine_final;
CREATE DATABASE newmine_items;
CREATE DATABASE newmine_userprofile;
```

### Backup strategy

```bash
# Automated via RDS snapshots (daily)
# Manual backup before major release
pg_dump -h $RDS_HOST -U postgres -Fc newmine_final > newmine_final_ws298.dump
```

---

## Monitoring and Logging

### Container logs
```bash
docker logs -f wormmine-tomcat
```

### Tomcat logs
```bash
docker exec wormmine-tomcat tail -f /opt/tomcat/logs/catalina.out
```

### Application logs
```bash
docker exec wormmine-tomcat tail -f /opt/intermine/logs/intermine.log
```

### Metrics to monitor
- Container CPU/Memory usage
- Tomcat thread count
- Database connection pool
- Solr query response times
- API response times

---

## Disaster Recovery

### Full system restore

1. **RDS**: Restore from automated snapshot
2. **Solr**: Restore from backup tar.gz
3. **Containers**: Pull previous version from ECR and redeploy

### Rollback procedure

```bash
# Tag current production
docker tag agr_wormmine:latest agr_wormmine:ws298-backup

# Revert to previous
docker pull agr_wormmine:ws297
docker stop wormmine-tomcat
docker rm wormmine-tomcat
docker run -d --name wormmine-tomcat ... agr_wormmine:ws297 tomcat
```

---

## Adding a New Mine

### 1. Create Dockerfile
```bash
cp -r docker/wormmine-unified docker/newmine-unified
# Update Dockerfile with new mine repositories
```

### 2. Create Solr cores
```bash
/opt/solr/bin/solr create -c newmine-search
/opt/solr/bin/solr create -c newmine-autocomplete
```

### 3. Create databases
```bash
psql -h $RDS_HOST -U postgres
CREATE DATABASE newmine_final;
CREATE DATABASE newmine_items;
CREATE DATABASE newmine_userprofile;
```

### 4. Build and deploy
```bash
cd docker/newmine-unified
docker-compose build
docker push ... agr_newmine:latest

# Deploy on next available port (8082, 8083, etc.)
docker run -d --name newmine-tomcat -p 8082:8080 ... agr_newmine:latest tomcat
```

---

## Cost Optimization

- **RDS**: Use Reserved Instances for production
- **ECR**: Lifecycle policy to delete old images after 30 days
- **EC2**: Right-size instance based on all mines' combined needs
- **Solr**: Single instance serves all mines (cost-effective)
- **Containers**: Lightweight, share host resources efficiently

---

## Security Considerations

- **RDS**: Security group restricts access to EC2 instance only
- **Containers**: Run as non-root user (intermine)
- **Secrets**: Use AWS Secrets Manager for RDS_PASSWORD
- **Updates**: Keep Tomcat, Solr, and OS packages updated
- **Backups**: Automated RDS snapshots, manual Solr backups

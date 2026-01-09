# Multi-Tenant InterMine Deployment Guide

This guide covers deploying multiple InterMine instances on a single EC2 instance with shared infrastructure.

## Architecture

**EC2 Instance**: c7i.4xlarge (16 vCPUs, 32GB RAM)

**Services**:
- **Nginx**: Reverse proxy for all services
- **BlueGenes**: Single instance serving all mines
- **Solr**: Single instance with multiple cores (one per mine)
- **Tomcat**: Multiple containers (one per mine)
- **PostgreSQL**: Amazon RDS (shared)

**Memory Allocation**:
- 6-10 Tomcat containers × 2-2.5GB = 12-25GB
- Solr: 2-3GB
- BlueGenes: 1GB
- Nginx: ~256MB
- System: 3-4GB

## Prerequisites

1. AWS CLI configured with appropriate credentials
2. SSH key pair created in AWS
3. Security group with required ports:
   - 22 (SSH)
   - 80 (HTTP)
   - 443 (HTTPS)
   - 8080-8090 (Tomcat - optional for direct access)
   - 8983 (Solr - optional for admin access)
4. RDS PostgreSQL instance running
5. Docker images built and pushed to ECR

## Step 1: Configure Launch Script

Edit `launch_multitenant_ec2.sh` and update the following variables:

```bash
AMI_ID="ami-0c55b159cbfafe1f0"  # Amazon Linux 2023 for us-east-1
KEY_NAME="your-key-pair"        # Your SSH key pair name
SECURITY_GROUP="sg-xxxxxxxxx"   # Security group ID
SUBNET_ID="subnet-xxxxxxxxx"    # Subnet ID (preferably public)
```

To find the latest Amazon Linux 2023 AMI:

```bash
aws ec2 describe-images \
  --owners amazon \
  --filters "Name=name,Values=al2023-ami-2023*-x86_64" \
  --query 'sort_by(Images, &CreationDate)[-1].ImageId' \
  --output text
```

## Step 2: Launch EC2 Instance

```bash
cd scripts/
chmod +x launch_multitenant_ec2.sh
./launch_multitenant_ec2.sh
```

This script will:
- Launch a c7i.4xlarge instance
- Attach a 200GB data volume
- Install Docker, Docker Compose, AWS CLI
- Configure automatic ECR login
- Set up monitoring scripts
- Tag all resources appropriately

**Output**: Instance ID, public IP, SSH command

## Step 3: Wait for Initialization

The user-data script takes 2-3 minutes to complete. Monitor progress:

```bash
ssh -i ~/.ssh/YOUR_KEY.pem ec2-user@PUBLIC_IP 'tail -f /var/log/cloud-init-output.log'
```

Wait for: `EC2 initialization complete`

## Step 4: Deploy InterMine Stack

SSH to the instance:

```bash
ssh -i ~/.ssh/YOUR_KEY.pem ec2-user@PUBLIC_IP
```

Clone the repository:

```bash
git clone https://github.com/alliance-genome/agr_intermine_builder.git
cd agr_intermine_builder
```

Copy deployment files:

```bash
cp scripts/docker-compose.multitenant.yml docker-compose.yml
cp scripts/nginx.conf .
```

Create environment file:

```bash
cat > .env <<EOF
RDS_HOST=intermine-postgres.cmnnhlso7wdi.us-east-1.rds.amazonaws.com
RDS_PORT=5432
RDS_USER=postgres
RDS_PASSWORD=your-password-here
EOF
```

## Step 5: Configure SSL Certificates

For production, use Let's Encrypt:

```bash
# Install certbot
sudo yum install -y certbot python3-certbot-nginx

# Generate certificates
sudo certbot certonly --standalone \
  -d yourdomain.com \
  -d www.yourdomain.com \
  --non-interactive \
  --agree-tos \
  -m your-email@example.com

# Copy certificates for nginx
sudo mkdir -p ssl
sudo cp /etc/letsencrypt/live/yourdomain.com/fullchain.pem ssl/cert.pem
sudo cp /etc/letsencrypt/live/yourdomain.com/privkey.pem ssl/key.pem
sudo chown -R ec2-user:ec2-user ssl/
```

For development, use self-signed certificates:

```bash
mkdir -p ssl
openssl req -x509 -nodes -days 365 -newkey rsa:2048 \
  -keyout ssl/key.pem \
  -out ssl/cert.pem \
  -subj "/CN=localhost"
```

## Step 6: Configure BlueGenes

Create BlueGenes configuration:

```bash
mkdir -p bluegenes-config
cat > bluegenes-config.edn <<EOF
{:mines
 {:alliancemine
  {:name "AllianceMine"
   :service {:root "https://yourdomain.com/alliancemine"}}

  :wormmine
  {:name "WormMine"
   :service {:root "https://yourdomain.com/wormmine"}}

  :flymine
  {:name "FlyMine"
   :service {:root "https://yourdomain.com/flymine"}}

  :zebrafishmine
  {:name "ZebrafishMine"
   :service {:root "https://yourdomain.com/zebrafishmine"}}

  :mousemine
  {:name "MouseMine"
   :service {:root "https://yourdomain.com/mousemine"}}

  :ratmine
  {:name "RatMine"
   :service {:root "https://yourdomain.com/ratmine"}}}

 :default-mine :alliancemine
 :bluegenes-deploy-path "/"
 :server-port 5000}
EOF
```

## Step 7: Configure Solr Cores

The Solr container will create cores automatically when mines first connect. To pre-create cores:

```bash
# Start only Solr first
docker-compose up -d solr

# Wait for Solr to be ready
sleep 30

# Create cores for each mine
for mine in alliancemine wormmine flymine zebrafishmine mousemine ratmine; do
  docker exec intermine-solr solr create_core -c $mine
done
```

## Step 8: Pull Docker Images from ECR

```bash
# Login to ECR
aws ecr get-login-password --region us-east-1 | \
  docker login --username AWS --password-stdin \
  100225593120.dkr.ecr.us-east-1.amazonaws.com

# Pull all mine images
docker pull 100225593120.dkr.ecr.us-east-1.amazonaws.com/agr_alliancemine:latest
docker pull 100225593120.dkr.ecr.us-east-1.amazonaws.com/agr_wormmine:latest
docker pull 100225593120.dkr.ecr.us-east-1.amazonaws.com/agr_flymine:latest
docker pull 100225593120.dkr.ecr.us-east-1.amazonaws.com/agr_zebrafishmine:latest
docker pull 100225593120.dkr.ecr.us-east-1.amazonaws.com/agr_mousemine:latest
docker pull 100225593120.dkr.ecr.us-east-1.amazonaws.com/agr_ratmine:latest
```

## Step 9: Set Up CDN (Content Delivery Network)

The multi-tenant instance includes an integrated CDN for serving static assets.

```bash
# Create standard CDN directory structure
./scripts/manage_cdn.sh structure

# Upload common JavaScript libraries (example)
./scripts/manage_cdn.sh upload ~/Downloads/jquery-3.6.0.min.js /cdn/js/jquery/3.6.0/jquery.min.js

# Upload BlueGenes assets
./scripts/manage_cdn.sh sync ./bluegenes-static /cdn/bluegenes

# Upload mine-specific assets
./scripts/manage_cdn.sh sync ./alliancemine-assets /cdn/mines/alliancemine

# Check CDN status
./scripts/manage_cdn.sh status

# List CDN contents
./scripts/manage_cdn.sh list
```

CDN URLs will be accessible at:
- `https://yourdomain.com/cdn/js/jquery/3.6.0/jquery.min.js`
- `https://yourdomain.com/cdn/bluegenes/app.js`
- `https://yourdomain.com/cdn/mines/alliancemine/logo.png`

**CDN Features:**
- 1-year browser caching for immutable assets
- CORS enabled for cross-origin requests
- Gzip compression
- Directory browsing enabled
- Replaces the need for separate t2.nano CDN instance

## Step 10: Start All Services

```bash
# Start all services
docker-compose up -d

# Monitor logs
docker-compose logs -f

# Check status
docker-compose ps
```

## Step 11: Verify Deployment

Check each service:

```bash
# Health check
curl http://localhost/health

# AllianceMine
curl http://localhost:9001/alliancemine/service/version

# WormMine
curl http://localhost:9002/wormmine/service/version

# Solr
curl http://localhost:8983/solr/admin/cores?action=STATUS

# BlueGenes
curl http://localhost:5000/
```

External access (replace with your domain):

- BlueGenes: https://yourdomain.com
- AllianceMine: https://yourdomain.com/alliancemine
- WormMine: https://yourdomain.com/wormmine
- Solr Admin: https://yourdomain.com/solr

## Monitoring

### Container Status

```bash
# Run the built-in monitoring script
./monitor.sh

# Or use docker commands directly
docker stats
docker-compose ps
```

### Resource Usage

```bash
# Memory
free -h

# Disk
df -h /data

# CPU
top

# Network
netstat -tulpn
```

### Logs

```bash
# All services
docker-compose logs -f

# Specific service
docker-compose logs -f wormmine

# Last 100 lines
docker-compose logs --tail=100 alliancemine

# Nginx access logs
docker exec nginx-proxy tail -f /var/log/nginx/access.log
```

### Log Rotation

**CRITICAL**: Tomcat logs can grow to 40GB+ and fill the disk, causing 504 errors. Set up logrotate:

```bash
sudo tee /etc/logrotate.d/intermine-logs << 'EOF'
/data/mines/logs/wormmine/*.log
/data/mines/logs/alliancemine/*.log {
    daily
    rotate 7
    size 100M
    compress
    delaycompress
    missingok
    notifempty
    copytruncate
}
EOF
```

Verify with: `sudo logrotate -d /etc/logrotate.d/intermine-logs`

If disk is full, emergency cleanup:
```bash
# Check disk usage
df -h /

# Find large log files
du -sh /data/mines/logs/*

# Truncate logs (keeps file open, no restart needed)
sudo truncate -s 0 /data/mines/logs/wormmine/*.log
sudo truncate -s 0 /data/mines/logs/alliancemine/*.log

# Restart affected containers
docker restart wormmine alliancemine
```

### Database Monitoring

From your local machine with pg_top:

```bash
PGPASSWORD='your-password' pg_top \
  -h intermine-postgres.cmnnhlso7wdi.us-east-1.rds.amazonaws.com \
  -p 5432 \
  -U postgres \
  -d wormmine_final
```

## Adding More Mines

To add additional mines:

1. **Build and push Docker image to ECR**

2. **Add service to docker-compose.yml**:

```yaml
  newmine:
    image: 100225593120.dkr.ecr.us-east-1.amazonaws.com/agr_newmine:latest
    container_name: newmine-tomcat
    networks:
      - intermine
    ports:
      - "9007:8080"
    environment:
      - MINE_NAME=newmine
      - CATALINA_OPTS=-Xmx2g -Xms2g -XX:+UseG1GC
      - RDS_HOST=${RDS_HOST}
      - RDS_PORT=${RDS_PORT}
      - RDS_USER=${RDS_USER}
      - RDS_PASSWORD=${RDS_PASSWORD}
      - SOLR_URL=http://solr:8983/solr/newmine
    volumes:
      - /data/mines/newmine:/data
    deploy:
      resources:
        limits:
          memory: 2500m
          cpus: '2'
    restart: unless-stopped
    depends_on:
      - solr
```

3. **Add upstream and location to nginx.conf**:

```nginx
upstream newmine {
    server newmine-tomcat:8080;
}

location /newmine {
    proxy_pass http://newmine/newmine;
    proxy_set_header Host $host;
    proxy_set_header X-Real-IP $remote_addr;
    proxy_read_timeout 600s;
}
```

4. **Add to BlueGenes config**:

```clojure
:newmine
{:name "NewMine"
 :service {:root "https://yourdomain.com/newmine"}}
```

5. **Restart services**:

```bash
docker-compose up -d
docker exec nginx-proxy nginx -s reload
```

## Troubleshooting

### Out of Memory

Check memory allocation:

```bash
docker stats --no-stream
free -h
```

Reduce memory per mine if needed in docker-compose.yml:

```yaml
environment:
  - CATALINA_OPTS=-Xmx1536m -Xms1536m -XX:+UseG1GC
```

### Tomcat Not Starting

Check logs:

```bash
docker-compose logs wormmine
```

Common issues:
- Database connection failure (check RDS credentials)
- Out of memory (reduce heap size)
- Port conflict (check ports in use)

### Nginx 502 Bad Gateway

Verify backend is running:

```bash
docker ps | grep tomcat
curl http://localhost:9001/alliancemine/service/version
```

Check nginx error logs:

```bash
docker exec nginx-proxy tail -f /var/log/nginx/error.log
```

### Solr Connection Issues

Check Solr is running:

```bash
curl http://localhost:8983/solr/admin/cores?action=STATUS
```

Verify cores exist:

```bash
docker exec intermine-solr solr healthcheck -c alliancemine
```

## Backup and Maintenance

### Database Backups

Handled by RDS automated backups.

### Data Volume Backups

Create EBS snapshot:

```bash
# Find volume ID
VOLUME_ID=$(aws ec2 describe-volumes \
  --filters "Name=attachment.instance-id,Values=INSTANCE_ID" \
            "Name=attachment.device,Values=/dev/sdf" \
  --query 'Volumes[0].VolumeId' \
  --output text)

# Create snapshot
aws ec2 create-snapshot \
  --volume-id $VOLUME_ID \
  --description "InterMine data volume backup $(date +%Y%m%d)" \
  --tag-specifications 'ResourceType=snapshot,Tags=[{Key=Name,Value=InterMine-Data-Backup}]'
```

### Updates

Update Docker images:

```bash
# Pull latest images
docker-compose pull

# Restart with new images
docker-compose up -d

# Clean up old images
docker image prune -a
```

## Cost Optimization

**Current configuration**:
- c7i.4xlarge: ~$496/month (on-demand)
- 200GB EBS gp3: ~$16/month
- **Total**: ~$512/month

**Savings options**:
1. **Savings Plans**: 1-year commitment saves 30-40%
2. **Reserved Instances**: 1-year saves 40%, 3-year saves 60%
3. **Spot Instances**: Save up to 90% (for dev/test environments)

## Security Checklist

- [ ] SSL certificates configured
- [ ] Security group restricts access to necessary ports only
- [ ] Solr admin interface restricted to internal network
- [ ] RDS password stored in AWS Secrets Manager
- [ ] CloudWatch monitoring enabled
- [ ] Automated backups configured
- [ ] IAM roles follow least privilege principle
- [ ] Regular security updates applied
- [ ] Log rotation configured (prevents disk full outages)

## Support

For issues or questions:
- GitHub: https://github.com/alliance-genome/agr_intermine_builder/issues
- Alliance Genome Resources: https://www.alliancegenome.org/contact

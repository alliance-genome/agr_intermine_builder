#!/bin/bash

# Launch multi-tenant InterMine EC2 instance
# Solr installed locally, Tomcat containers per mine, Caddy for HTTPS

set -e

# Configuration
INSTANCE_TYPE="c7i.4xlarge"
REGION="us-east-1"
KEY_NAME="AGR-ssl3"
SUBNET_ID="subnet-ff838bd5"
SECURITY_GROUP_IDS="sg-21ac675b sg-0415cab61ab6b45c5"
IAM_INSTANCE_PROFILE="S3DataAccess"

# Get latest Amazon Linux 2023 AMI
AMI_ID=$(aws ec2 describe-images --region "$REGION" --owners amazon \
    --filters "Name=name,Values=al2023-ami-2023*-x86_64" "Name=state,Values=available" \
    --query 'Images | sort_by(@, &CreationDate) | [-1].ImageId' --output text)

if [ -z "$AMI_ID" ] || [ "$AMI_ID" == "None" ]; then
    echo "ERROR: Could not find Amazon Linux 2023 AMI"
    exit 1
fi
echo "Using AMI: $AMI_ID"

# Storage - runtime only
ROOT_VOLUME_SIZE=50
DATA_VOLUME_SIZE=30

# Tags
PROJECT="AllianceMine"
ENVIRONMENT="production"

USER_DATA=$(cat <<'EOF'
#!/bin/bash
set -e

# Update system
yum update -y
yum install -y docker git wget java-11-amazon-corretto

# Start Docker
systemctl start docker
systemctl enable docker
usermod -a -G docker ec2-user

# Install Docker Compose
curl -L "https://github.com/docker/compose/releases/latest/download/docker-compose-$(uname -s)-$(uname -m)" -o /usr/local/bin/docker-compose
chmod +x /usr/local/bin/docker-compose

# ============================================
# Install Solr 8.11.2
# ============================================
cd /opt
wget -q https://archive.apache.org/dist/lucene/solr/8.11.2/solr-8.11.2.tgz
tar xzf solr-8.11.2.tgz
./solr-8.11.2/bin/install_solr_service.sh solr-8.11.2.tgz
rm solr-8.11.2.tgz

# Start Solr
systemctl enable solr
systemctl start solr

# ============================================
# Install Caddy
# ============================================
yum install -y yum-plugin-copr
yum copr enable -y @caddy/caddy
yum install -y caddy
systemctl enable caddy

# ============================================
# Create directory structure
# ============================================
mkdir -p /data/mines/logs
chown -R ec2-user:ec2-user /data

# ============================================
# Build InterMine Tomcat image
# ============================================
mkdir -p /opt/intermine-tomcat
cat > /opt/intermine-tomcat/Dockerfile <<'DOCKERFILE'
FROM tomcat:9-jdk11

# Copy manager from webapps.dist to webapps (base image keeps apps in webapps.dist)
RUN cp -r /usr/local/tomcat/webapps.dist/manager /usr/local/tomcat/webapps/ || true

# Remove default webapps we dont need
RUN rm -rf /usr/local/tomcat/webapps/ROOT /usr/local/tomcat/webapps/docs /usr/local/tomcat/webapps/examples /usr/local/tomcat/webapps/host-manager

# Configure tomcat-users.xml
RUN printf '<?xml version="1.0" encoding="UTF-8"?>\n<tomcat-users>\n  <role rolename="manager-gui"/>\n  <role rolename="manager-script"/>\n  <user username="manager" password="manager" roles="manager-gui,manager-script"/>\n</tomcat-users>' > /usr/local/tomcat/conf/tomcat-users.xml

# Configure context.xml for InterMine
RUN printf '<?xml version="1.0" encoding="UTF-8"?>\n<Context sessionCookiePath="/" useHttpOnly="false" clearReferencesStopTimerThreads="true">\n  <WatchedResource>WEB-INF/web.xml</WatchedResource>\n</Context>' > /usr/local/tomcat/conf/context.xml

# Allow manager access from any IP
RUN mkdir -p /usr/local/tomcat/webapps/manager/META-INF && \
    printf '<?xml version="1.0" encoding="UTF-8"?>\n<Context antiResourceLocking="false" privileged="true">\n  <Valve className="org.apache.catalina.valves.RemoteAddrValve" allow=".*"/>\n</Context>' > /usr/local/tomcat/webapps/manager/META-INF/context.xml

# Configure server.xml with UTF-8 encoding
RUN sed -i 's/Connector port="8080"/Connector port="8080" URIEncoding="UTF-8"/' /usr/local/tomcat/conf/server.xml

# Set JAVA_OPTS for InterMine
ENV JAVA_OPTS="-Dorg.apache.el.parser.SKIP_IDENTIFIER_CHECK=true -Xmx4g -Xms2g"
ENV CATALINA_OPTS="-Dorg.apache.el.parser.SKIP_IDENTIFIER_CHECK=true"

# Create .intermine directory
RUN mkdir -p /root/.intermine

EXPOSE 8080
CMD ["catalina.sh", "run"]
DOCKERFILE

cd /opt/intermine-tomcat
docker build -t intermine-tomcat:latest .

# ============================================
# Create mine management scripts
# ============================================

# Script to add a new mine
cat > /usr/local/bin/add-mine <<'ADDMINE'
#!/bin/bash
set -e

MINE_NAME=$1
PORT=$2
DOMAIN=$3  # Optional - only needed if using Caddy for HTTPS

if [ -z "$MINE_NAME" ] || [ -z "$PORT" ]; then
    echo "Usage: add-mine <mine_name> <port> [domain]"
    echo "Example: add-mine wormmine 8081"
    exit 1
fi

echo "Adding mine: $MINE_NAME on port $PORT"

# Create Solr cores (InterMine needs search + autocomplete)
sudo -u solr /opt/solr/bin/solr create_core -c ${MINE_NAME}-search -d /opt/solr/server/solr/configsets/_default || true
sudo -u solr /opt/solr/bin/solr create_core -c ${MINE_NAME}-autocomplete -d /opt/solr/server/solr/configsets/_default || true

# Create logs directory
mkdir -p /data/mines/logs/${MINE_NAME}

# Start container (WAR deployed via cargoRedeployRemote from build image)
docker run -d \
    --name $MINE_NAME \
    --restart unless-stopped \
    -p ${PORT}:8080 \
    -v /data/mines/logs/${MINE_NAME}:/usr/local/tomcat/logs \
    -e JAVA_OPTS="-Dorg.apache.el.parser.SKIP_IDENTIFIER_CHECK=true -Xmx4g -Xms2g" \
    intermine-tomcat:latest

echo "Container $MINE_NAME started on port $PORT"
echo "Tomcat manager: http://localhost:${PORT}/manager/html (manager/manager)"
echo ""
echo "Solr cores created:"
echo "  Search:       http://localhost:8983/solr/${MINE_NAME}-search"
echo "  Autocomplete: http://localhost:8983/solr/${MINE_NAME}-autocomplete"

# Add to Caddy config if domain provided
if [ -n "$DOMAIN" ] && ! grep -q "$DOMAIN" /etc/caddy/Caddyfile 2>/dev/null; then
    cat >> /etc/caddy/Caddyfile <<CADDY

${DOMAIN} {
    reverse_proxy localhost:${PORT}
}
CADDY
    systemctl reload caddy
    echo "Added Caddy config for $DOMAIN"
fi

echo ""
echo "Done! Deploy WAR via cargoRedeployRemote from build image"
ADDMINE
chmod +x /usr/local/bin/add-mine

# Script to remove a mine
cat > /usr/local/bin/remove-mine <<'REMOVEMINE'
#!/bin/bash
MINE_NAME=$1

if [ -z "$MINE_NAME" ]; then
    echo "Usage: remove-mine <mine_name>"
    exit 1
fi

docker stop $MINE_NAME 2>/dev/null || true
docker rm $MINE_NAME 2>/dev/null || true
echo "Removed container $MINE_NAME"
echo "Note: WAR, properties, and Solr core preserved. Delete manually if needed."
REMOVEMINE
chmod +x /usr/local/bin/remove-mine

# Script to list mines
cat > /usr/local/bin/list-mines <<'LISTMINES'
#!/bin/bash
echo "=== Running Mines ==="
docker ps --filter "ancestor=intermine-tomcat:latest" --format "table {{.Names}}\t{{.Status}}\t{{.Ports}}"
echo ""
echo "=== Solr Cores ==="
curl -s "http://localhost:8983/solr/admin/cores?action=STATUS" | grep -o '"name":"[^"]*"' | cut -d'"' -f4
echo ""
echo "=== Available WARs ==="
ls -la /data/mines/wars/
LISTMINES
chmod +x /usr/local/bin/list-mines

# ============================================
# Initialize Caddy config
# ============================================
cat > /etc/caddy/Caddyfile <<'CADDYFILE'
# InterMine Multi-Tenant Caddy Configuration
# Mines are added automatically by add-mine script

# Global options
{
    email admin@alliancegenome.org
}
CADDYFILE

systemctl start caddy

# ============================================
# ECR login for pulling images if needed
# ============================================
aws ecr get-login-password --region us-east-1 | docker login --username AWS --password-stdin 100225593120.dkr.ecr.us-east-1.amazonaws.com 2>/dev/null || true

echo "Setup complete!" > /tmp/user-data-complete
EOF
)

# Launch instance
echo "Launching multi-tenant InterMine instance..."

INSTANCE_ID=$(aws ec2 run-instances \
    --region "$REGION" \
    --image-id "$AMI_ID" \
    --instance-type "$INSTANCE_TYPE" \
    --key-name "$KEY_NAME" \
    --security-group-ids $SECURITY_GROUP_IDS \
    --subnet-id "$SUBNET_ID" \
    --iam-instance-profile "Name=$IAM_INSTANCE_PROFILE" \
    --block-device-mappings \
        "DeviceName=/dev/xvda,Ebs={VolumeSize=$ROOT_VOLUME_SIZE,VolumeType=gp3,DeleteOnTermination=true}" \
        "DeviceName=/dev/sdf,Ebs={VolumeSize=$DATA_VOLUME_SIZE,VolumeType=gp3,DeleteOnTermination=false}" \
    --tag-specifications \
        "ResourceType=instance,Tags=[{Key=Name,Value=InterMine-MultiTenant},{Key=Project,Value=$PROJECT},{Key=Environment,Value=$ENVIRONMENT}]" \
    --user-data "$USER_DATA" \
    --query 'Instances[0].InstanceId' \
    --output text)

echo "Instance: $INSTANCE_ID"
aws ec2 wait instance-running --region "$REGION" --instance-ids "$INSTANCE_ID"

PUBLIC_IP=$(aws ec2 describe-instances \
    --region "$REGION" \
    --instance-ids "$INSTANCE_ID" \
    --query 'Reservations[0].Instances[0].PublicIpAddress' \
    --output text)

echo ""
echo "========================================"
echo "Instance ready: $INSTANCE_ID"
echo "Public IP: $PUBLIC_IP"
echo "========================================"
echo ""
echo "SSH: ssh -i ~/.ssh/${KEY_NAME}.pem ec2-user@$PUBLIC_IP"
echo ""
echo "Wait ~5 min for setup, then:"
echo ""
echo "  # Add mine (Solr core + Tomcat container + Caddy)"
echo "  ssh ec2-user@$PUBLIC_IP 'sudo add-mine wormmine 8081 wormmine.alliancegenome.org'"
echo ""
echo "  # Deploy from build image: ./gradlew cargoRedeployRemote"
echo ""
echo "  # Solr URL for mine properties: http://$PUBLIC_IP:8983/solr/<mine>"
echo ""
echo "  # List mines: ssh ec2-user@$PUBLIC_IP 'list-mines'"
echo "========================================"

#!/bin/bash

# Launch multi-tenant InterMine EC2 instance
# Instance type: c7i.4xlarge (16 vCPUs, 32GB RAM)
# Purpose: Run multiple InterMine instances (Tomcat containers), Solr, and BlueGenes

set -e

# Configuration
INSTANCE_TYPE="c7i.4xlarge"
AMI_ID="ami-0c55b159cbfafe1f0"  # Amazon Linux 2023 AMI - UPDATE THIS for your region
REGION="us-east-1"
KEY_NAME="your-key-pair"  # UPDATE THIS
SECURITY_GROUP="sg-xxxxxxxxx"  # UPDATE THIS - needs ports 22, 80, 443, 8080, 8983
SUBNET_ID="subnet-xxxxxxxxx"  # UPDATE THIS
IAM_INSTANCE_PROFILE="arn:aws:iam::100225593120:instance-profile/EC2-ECR-Access"  # For ECR access

# Storage configuration
ROOT_VOLUME_SIZE=100  # GB - for OS, Docker images, logs
DATA_VOLUME_SIZE=200  # GB - for mine data, Solr indexes

# Tags
PROJECT="AllianceMine"
ENVIRONMENT="production"
TEAM="Alliance Genome Resources"
COST_CENTER="InterMine"

# User data script for instance initialization
USER_DATA=$(cat <<'EOF'
#!/bin/bash

# Update system
yum update -y

# Install Docker
yum install -y docker
systemctl start docker
systemctl enable docker
usermod -a -G docker ec2-user

# Install Docker Compose
curl -L "https://github.com/docker/compose/releases/latest/download/docker-compose-$(uname -s)-$(uname -m)" -o /usr/local/bin/docker-compose
chmod +x /usr/local/bin/docker-compose

# Install AWS CLI v2
curl "https://awscli.amazonaws.com/awscli-exe-linux-x86_64.zip" -o "awscliv2.zip"
unzip awscliv2.zip
./aws/install
rm -rf aws awscliv2.zip

# Install PostgreSQL client for debugging
amazon-linux-extras install postgresql14 -y

# Create data directory
mkdir -p /data/mines
mkdir -p /data/solr
mkdir -p /data/bluegenes
chown -R ec2-user:ec2-user /data

# Mount additional EBS volume if attached
DEVICE="/dev/nvme1n1"
if [ -b "$DEVICE" ]; then
    # Check if volume has a filesystem
    if ! blkid "$DEVICE"; then
        mkfs -t ext4 "$DEVICE"
    fi

    # Mount to /data
    mount "$DEVICE" /data

    # Add to fstab for persistence
    UUID=$(blkid -s UUID -o value "$DEVICE")
    echo "UUID=$UUID /data ext4 defaults,nofail 0 2" >> /etc/fstab

    # Recreate directories after mount
    mkdir -p /data/mines /data/solr /data/bluegenes
    chown -R ec2-user:ec2-user /data
fi

# Configure Docker daemon for better logging
cat > /etc/docker/daemon.json <<DOCKER_CONFIG
{
  "log-driver": "json-file",
  "log-opts": {
    "max-size": "10m",
    "max-file": "3"
  },
  "storage-driver": "overlay2"
}
DOCKER_CONFIG

systemctl restart docker

# ECR login
aws ecr get-login-password --region us-east-1 | docker login --username AWS --password-stdin 100225593120.dkr.ecr.us-east-1.amazonaws.com

# Create systemd service for docker-compose management
cat > /etc/systemd/system/intermine-stack.service <<SERVICE
[Unit]
Description=InterMine Multi-Tenant Stack
After=docker.service
Requires=docker.service

[Service]
Type=oneshot
RemainAfterExit=yes
WorkingDirectory=/home/ec2-user/intermine
ExecStart=/usr/local/bin/docker-compose up -d
ExecStop=/usr/local/bin/docker-compose down
User=ec2-user

[Install]
WantedBy=multi-user.target
SERVICE

# Enable CloudWatch agent for monitoring
wget https://s3.amazonaws.com/amazoncloudwatch-agent/amazon_linux/amd64/latest/amazon-cloudwatch-agent.rpm
rpm -U ./amazon-cloudwatch-agent.rpm
rm amazon-cloudwatch-agent.rpm

# Create initial monitoring script
cat > /home/ec2-user/monitor.sh <<'MONITOR'
#!/bin/bash
echo "=== Docker Container Status ==="
docker ps --format "table {{.Names}}\t{{.Status}}\t{{.Ports}}"

echo -e "\n=== Memory Usage ==="
free -h

echo -e "\n=== Disk Usage ==="
df -h /data

echo -e "\n=== Docker Stats ==="
docker stats --no-stream
MONITOR

chmod +x /home/ec2-user/monitor.sh
chown ec2-user:ec2-user /home/ec2-user/monitor.sh

# Signal completion
echo "EC2 initialization complete" > /tmp/user-data-complete
EOF
)

# Launch instance
echo "Launching c7i.4xlarge instance for multi-tenant InterMine deployment..."

INSTANCE_ID=$(aws ec2 run-instances \
    --region "$REGION" \
    --image-id "$AMI_ID" \
    --instance-type "$INSTANCE_TYPE" \
    --key-name "$KEY_NAME" \
    --security-group-ids "$SECURITY_GROUP" \
    --subnet-id "$SUBNET_ID" \
    --iam-instance-profile "Name=EC2-ECR-Access" \
    --block-device-mappings \
        "DeviceName=/dev/xvda,Ebs={VolumeSize=$ROOT_VOLUME_SIZE,VolumeType=gp3,DeleteOnTermination=true,Iops=3000,Throughput=125}" \
        "DeviceName=/dev/sdf,Ebs={VolumeSize=$DATA_VOLUME_SIZE,VolumeType=gp3,DeleteOnTermination=false,Iops=3000,Throughput=125}" \
    --tag-specifications \
        "ResourceType=instance,Tags=[
            {Key=Name,Value=InterMine-MultiTenant-Production},
            {Key=Project,Value=$PROJECT},
            {Key=Environment,Value=$ENVIRONMENT},
            {Key=Team,Value=$TEAM},
            {Key=CostCenter,Value=$COST_CENTER},
            {Key=Purpose,Value=Multi-tenant InterMine deployment},
            {Key=ManagedBy,Value=agr_intermine_builder}
        ]" \
        "ResourceType=volume,Tags=[
            {Key=Name,Value=InterMine-MultiTenant-Volume},
            {Key=Project,Value=$PROJECT},
            {Key=Environment,Value=$ENVIRONMENT},
            {Key=VolumeType,Value=Root}
        ]" \
    --user-data "$USER_DATA" \
    --monitoring Enabled=true \
    --query 'Instances[0].InstanceId' \
    --output text)

if [ -z "$INSTANCE_ID" ]; then
    echo "ERROR: Failed to launch instance"
    exit 1
fi

echo "✓ Instance launched: $INSTANCE_ID"
echo "  Waiting for instance to start..."

# Wait for instance to be running
aws ec2 wait instance-running --region "$REGION" --instance-ids "$INSTANCE_ID"

# Get instance details
INSTANCE_INFO=$(aws ec2 describe-instances \
    --region "$REGION" \
    --instance-ids "$INSTANCE_ID" \
    --query 'Reservations[0].Instances[0].[PublicIpAddress,PrivateIpAddress,State.Name]' \
    --output text)

PUBLIC_IP=$(echo "$INSTANCE_INFO" | cut -f1)
PRIVATE_IP=$(echo "$INSTANCE_INFO" | cut -f2)
STATE=$(echo "$INSTANCE_INFO" | cut -f3)

echo ""
echo "================================"
echo "Instance Details"
echo "================================"
echo "Instance ID:    $INSTANCE_ID"
echo "Instance Type:  $INSTANCE_TYPE"
echo "State:          $STATE"
echo "Public IP:      $PUBLIC_IP"
echo "Private IP:     $PRIVATE_IP"
echo "Region:         $REGION"
echo ""
echo "Configuration:"
echo "  - vCPUs:      16"
echo "  - Memory:     32 GB"
echo "  - Root Vol:   $ROOT_VOLUME_SIZE GB (gp3)"
echo "  - Data Vol:   $DATA_VOLUME_SIZE GB (gp3)"
echo ""
echo "Memory Allocation Plan:"
echo "  - Tomcat containers:  ~24 GB (8-12 mines × 2-2.5 GB each)"
echo "  - Solr:               2-3 GB"
echo "  - BlueGenes:          1 GB"
echo "  - System:             3-4 GB"
echo ""
echo "Tags:"
echo "  Project:      $PROJECT"
echo "  Environment:  $ENVIRONMENT"
echo "  Team:         $TEAM"
echo ""
echo "SSH Connection:"
echo "  ssh -i ~/.ssh/$KEY_NAME.pem ec2-user@$PUBLIC_IP"
echo ""
echo "Next Steps:"
echo "  1. Wait 2-3 minutes for user-data script to complete"
echo "  2. SSH to instance"
echo "  3. Clone agr_intermine_builder repository"
echo "  4. Configure docker-compose.yml for multiple mines"
echo "  5. Pull images from ECR and start services"
echo ""
echo "Monitor initialization:"
echo "  ssh -i ~/.ssh/$KEY_NAME.pem ec2-user@$PUBLIC_IP 'tail -f /var/log/cloud-init-output.log'"
echo "================================"

# Save instance info to file
cat > instance-info.txt <<INFO
Instance ID: $INSTANCE_ID
Instance Type: $INSTANCE_TYPE
Public IP: $PUBLIC_IP
Private IP: $PRIVATE_IP
Region: $REGION
Launch Time: $(date)

SSH Command:
ssh -i ~/.ssh/$KEY_NAME.pem ec2-user@$PUBLIC_IP

Tags:
  Project: $PROJECT
  Environment: $ENVIRONMENT
  Team: $TEAM
  Cost Center: $COST_CENTER
INFO

echo "Instance information saved to instance-info.txt"

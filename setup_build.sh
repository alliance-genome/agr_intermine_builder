#!/bin/bash

# Add error handling function
handle_error() {
    echo "Error: $1"
    exit 1
}

# Check required environment variable
[ -z "$PGPASSWORD" ] && handle_error "PGPASSWORD environment variable is not set"

# Authenticate with AWS ECR
ECR_REGISTRY="100225593120.dkr.ecr.us-east-1.amazonaws.com"
aws ecr get-login-password --region us-east-1 | \
    docker login \
        --username AWS \
        --password-stdin \
        "$ECR_REGISTRY" || \
    handle_error "AWS ECR authentication failed"


# Create the network if it doesn't exist
docker network ls | grep -w intermine || \
    docker network create intermine || \
    handle_error "Failed to create docker network"


CONTAINER_NAME="agr.local.intermine_builder"

# Check and remove existing builder container
if [ $(docker ps -aq -f name=^/${CONTAINER_NAME}$) ]; then
    echo "Found existing builder container - removing..."
    docker stop ${CONTAINER_NAME}
    docker rm ${CONTAINER_NAME}
fi

# Find the PostgreSQL container
PG_CONTAINER=$(docker ps \
    --filter name=postgres \
    --filter name=local \
    --format "{{.Names}}" | head -n1)

[ -z "$PG_CONTAINER" ] && handle_error "PostgreSQL container not found. Make sure it's running."

# Get PostgreSQL container IP
PG_IP=$(docker inspect -f '{{range .NetworkSettings.Networks}}{{.IPAddress}}{{end}}' $PG_CONTAINER)
[ -z "$PG_IP" ] && handle_error "Could not get IP address for PostgreSQL container."

echo "Using PostgreSQL container: $PG_CONTAINER (IP: $PG_IP)"



# Get AWS credentials from local config
AWS_KEY=$(aws configure get aws_access_key_id)
AWS_SECRET=$(aws configure get aws_secret_access_key)
AWS_REGION=$(aws configure get region)

# Run the intermine builder
docker run \
    --name "${CONTAINER_NAME}" \
    --net intermine \
    --rm \
    -v "$(pwd)/data:/root/data" \
    -e PGPASSWORD="$PGPASSWORD" \
    -e AWS_ACCESS_KEY_ID="$AWS_KEY" \
    -e AWS_SECRET_ACCESS_KEY="$AWS_SECRET" \
    -e AWS_DEFAULT_REGION="$AWS_REGION" \
    --log-driver=gelf \
    --log-opt gelf-address=udp://logs.alliancegenome.org:12201 \
    "$ECR_REGISTRY/agr_intermine_builder_env:stage" \
    ./local_build_db_all "$PG_IP" postgres || \
    handle_error "Docker run command failed"

echo "Build process completed successfully."

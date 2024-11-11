#!/bin/bash
# Add error handling
set -e

# Source docker authentication
if ! ./docker_auth; then
    echo "Failed to authenticate with Docker" >&2
    exit 1
fi

# Create the network if it doesn't exist
docker network ls | grep -w intermine || docker network create intermine

# Make container name a variable for easier maintenance
CONTAINER_NAME="agr.local.intermine_builder"

# Check if container exists
if [ $(docker ps -aq -f name=^/${CONTAINER_NAME}$) ]; then
    echo "Stopping and removing existing container '${CONTAINER_NAME}'..."
    docker stop ${CONTAINER_NAME} || true
    docker rm ${CONTAINER_NAME} || true
fi

docker run \
  --name "agr.local.intermine_builder" \
  --net intermine \
  --rm \
  -v "/data:/root/data" \
  --log-driver=gelf --log-opt gelf-address=udp://logs.alliancegenome.org:12201 \
  "100225593120.dkr.ecr.us-east-1.amazonaws.com/agr_intermine_builder_env:stage" \
  ./local_dump_db_to_S3_only postgres postgres
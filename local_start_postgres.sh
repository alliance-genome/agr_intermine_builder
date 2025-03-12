#!/bin/bash
set -e  # Exit on error

./docker_auth

# Define the local directory for PostgreSQL data
PG_DATA_DIR="/home/ec2-user/pg_data"

# Create the network if it doesn't exist
docker network ls | grep -w intermine || docker network create intermine

# Check if the directory exists, if not, create it
if [ ! -d "$PG_DATA_DIR" ]; then
    echo "Creating directory $PG_DATA_DIR"
    mkdir -p "$PG_DATA_DIR"
fi

# Check if a container named "agr.local.alliancemine.postgres.server" already exists
if [ $(docker ps -aq -f name=^/agr.local.alliancemine.postgres.server$) ]; then
    echo "Stopping existing PostgreSQL container..."
    docker stop agr.local.alliancemine.postgres.server || echo "Failed to stop container"
    docker rm agr.local.alliancemine.postgres.server || echo "Failed to remove container"
    echo "Removed existing container named 'agr.local.alliancemine.postgres.server'"
fi

# Run the Docker container with the volume mounted for persistence in detached mode
docker run \
  -d \
  --name agr.local.alliancemine.postgres.server \
  --net intermine \
  -p 5432:5432 \
  --log-driver=gelf --log-opt gelf-address=udp://logs.alliancegenome.org:12201 \
  -e PGDATA=/var/lib/postgresql/data \
  -e POSTGRES_PASSWORD=${POSTGRES_PASSWORD:-postgres} \
  --health-cmd="pg_isready -U postgres" \
  --health-interval=10s \
  --health-timeout=5s \
  --health-retries=5 \
  -v "$PG_DATA_DIR:/var/lib/postgresql/data" \
  100225593120.dkr.ecr.us-east-1.amazonaws.com/agr_intermine_postgres_env:stage

# Wait for container to be healthy
echo "Waiting for PostgreSQL to start..."
timeout 30s bash -c 'until docker container inspect -f "{{.State.Health.Status}}" agr.local.alliancemine.postgres.server | grep -q "healthy"; do sleep 1; done' || {
    echo "PostgreSQL failed to start within 30 seconds"
    exit 1
}

echo "PostgreSQL container is ready"

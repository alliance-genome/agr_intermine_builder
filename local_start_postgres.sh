#!/bin/bash
./docker_auth

# Define the local directory for PostgreSQL data
PG_DATA_DIR="/home/core/pg_data"

# Create the network if it doesn't exist
docker network ls | grep -w intermine || docker network create intermine

# Check if the directory exists, if not, create it
if [ ! -d "$PG_DATA_DIR" ]; then
    echo "Creating directory $PG_DATA_DIR"
    mkdir -p "$PG_DATA_DIR"
fi

# Check if a container named "agr.local.alliancemine.postgres.server" already exists
if [ $(docker ps -aq -f name=^/agr.local.alliancemine.postgres.server$) ]; then
    # Stop the container if it is running
    docker stop agr.local.alliancemine.postgres.server
    # Remove the container after stopping
    docker rm agr.local.alliancemine.postgres.server
    echo "Removed existing container named 'agr.local.alliancemine.postgres.server'"
fi

# Run the Docker container with the volume mounted for persistence in detached mode
docker run \
  -d \
  --name agr.local.alliancemine.postgres.server \
  --net intermine \
  -e PGDATA=/var/lib/postgresql/data \
  -v "$PG_DATA_DIR:/var/lib/postgresql/data" \
  100225593120.dkr.ecr.us-east-1.amazonaws.com/agr_intermine_postgres_env:stage

#!/bin/bash

# Define the local directory for PostgreSQL data
PG_DATA_DIR="$HOME/docker/pg_data"

# Create the network if it doesn't exist
docker network ls | grep -w intermine || docker network create intermine

# Check if the directory exists, if not, create it
if [ ! -d "$PG_DATA_DIR" ]; then
    echo "Creating directory $PG_DATA_DIR"
    mkdir -p "$PG_DATA_DIR"
fi

# Check if a container named "local.postgres.server" already exists
if [ $(docker ps -aq -f name=^/local.postgres.server$) ]; then
    # Stop the container if it is running
    docker stop local.postgres.server
    # Remove the container after stopping
    docker rm local.postgres.server
    echo "Removed existing container named 'local.postgres.server'"
fi

# Run the Docker container with the volume mounted for persistence in detached mode
docker run \
  -d \
  --name local.postgres.server \
  --net intermine \
  -p 5432:5432 \
  -e POSTGRES_PASSWORD=mysecretpassword \
  -e PGDATA=/var/lib/postgresql/data \
  -v "$PG_DATA_DIR:/var/lib/postgresql/data" \
  postgres:13

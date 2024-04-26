#!/bin/bash

# Define the local directory for PostgreSQL data
PG_DATA_DIR="/home/core/pg_data"

# Check if the directory exists, if not, create it
if [ ! -d "$PG_DATA_DIR" ]; then
    echo "Creating directory $PG_DATA_DIR"
    mkdir -p "$PG_DATA_DIR"
fi

# Check if a container named "postgres" already exists
if [ $(docker ps -aq -f name=^/postgres$) ]; then
    # Stop the container if it is running
    docker stop postgres
    # Remove the container after stopping
    docker rm postgres
    echo "Removed existing container named 'postgres'"
fi

# Run the Docker container with the volume mounted for persistence in detached mode
docker run \
  -d \
  --name postgres \
  --net local \
  -e PGDATA=/var/lib/postgresql/data \
  -v "$PG_DATA_DIR:/var/lib/postgresql/data" \
  100225593120.dkr.ecr.us-east-1.amazonaws.com/agr_intermine_postgres_env:stage

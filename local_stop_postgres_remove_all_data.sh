#!/bin/bash

# Define the local directory for PostgreSQL data
PG_DATA_DIR="/home/ec2-user/pg_data"

# Check if a container named "postgres" is running
if docker ps -aq -f name=^/agr.local.alliancemine.postgres.server$ > /dev/null 2>&1; then
    echo "Stopping and removing the 'agr.local.alliancemine.postgres.server' container..."
    # Stop the container if it is running
    docker stop agr.local.alliancemine.postgres.server || echo "Failed to stop container"
    # Remove the container after stopping
    docker rm agr.local.alliancemine.postgres.server || echo "Failed to remove container"
    echo "Container 'agr.local.alliancemine.postgres.server' has been removed."
else
    echo "No 'agr.local.alliancemine.postgres.server' container is currently running."
fi

# Check if the data directory exists and remove it
if [ -d "$PG_DATA_DIR" ]; then
    echo "Removing the PostgreSQL data directory at $PG_DATA_DIR..."
    sudo rm -rf "$PG_DATA_DIR" || echo "Failed to remove data directory"
    echo "Data directory has been removed."
else
    echo "No data directory at $PG_DATA_DIR to remove."
fi

#!/bin/bash

# Define the local directory for PostgreSQL data
PG_DATA_DIR="/home/core/pg_data"

# Check if a container named "postgres" is running
if [ $(docker ps -aq -f name=^/postgres$) ]; then
    echo "Stopping and removing the 'postgres' container..."
    # Stop the container if it is running
    docker stop postgres
    # Remove the container after stopping
    docker rm postgres
    echo "Container 'postgres' has been removed."
else
    echo "No 'postgres' container is currently running."
fi

# Check if the data directory exists and remove it
if [ -d "$PG_DATA_DIR" ]; then
    echo "Removing the PostgreSQL data directory at $PG_DATA_DIR..."
    rm -rf "$PG_DATA_DIR"
    echo "Data directory has been removed."
else
    echo "No data directory at $PG_DATA_DIR to remove."
fi

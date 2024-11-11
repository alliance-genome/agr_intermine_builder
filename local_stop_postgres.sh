#!/bin/bash

CONTAINER_NAME="agr.local.alliancemine.postgres.server"

# Check if container exists (running or stopped)
if docker ps -a --format '{{.Names}}' | grep -q "^${CONTAINER_NAME}$"; then
    echo "Found container '${CONTAINER_NAME}'"
    
    # Check if container is running
    if docker ps --format '{{.Names}}' | grep -q "^${CONTAINER_NAME}$"; then
        echo "Stopping container..."
        if ! docker stop ${CONTAINER_NAME}; then
            echo "Error: Failed to stop container" >&2
            exit 1
        fi
    else
        echo "Container is already stopped"
    fi
    
    echo "Removing container..."
    if ! docker rm ${CONTAINER_NAME}; then
        echo "Error: Failed to remove container" >&2
        exit 1
    fi
    echo "Container '${CONTAINER_NAME}' has been successfully removed"
else
    echo "No container named '${CONTAINER_NAME}' exists"
fi
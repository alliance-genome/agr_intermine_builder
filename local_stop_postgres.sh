#!/bin/bash

# Check if a container named "postgres" is running
if [ $(docker ps -aq -f name=^/agr.local.alliancemine.postgres.server$) ]; then
    echo "Stopping and removing the 'agr.local.alliancemine.postgres.server' container..."
    # Stop the container if it is running
    docker stop agr.local.alliancemine.postgres.server
    # Remove the container after stopping
    docker rm agr.local.alliancemine.postgres.server
    echo "Container 'agr.local.alliancemine.postgres.server' has been removed."
else
    echo "No 'agr.local.alliancemine.postgres.server' container is currently running."
fi
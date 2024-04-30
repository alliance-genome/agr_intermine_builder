#!/bin/bash

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
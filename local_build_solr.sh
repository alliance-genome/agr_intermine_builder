#!/bin/bash
./docker_auth

# Create the network if it doesn't exist
docker network ls | grep -w intermine || docker network create intermine

# Check if a container named "agr.local.intermine_builder" already exists
if [ $(docker ps -aq -f name=^/agr.local.alliancemine.loaddata$) ]; then
    # Stop the container if it is running
    docker stop agr.local.alliancemine.loaddata
    # Remove the container after stopping
    docker rm agr.local.alliancemine.loaddata
    echo "Removed existing container named 'agr.local.alliancemine.loaddata'"
fi

# Launch Loaddata container
docker run --name agr.local.alliancemine.loaddata \
    --net intermine \
    -v db_backup_volume:/root/data \
    -v "$PG_DATA_DIR:/var/lib/postgresql/data" \
    100225593120.dkr.ecr.us-east-1.amazonaws.com/agr_intermine_builder_env:stage \
    ./local_load_db_build_solr
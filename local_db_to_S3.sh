#!/bin/bash
./docker_auth

# Create the network if it doesn't exist
docker network ls | grep -w intermine || docker network create intermine

# Check if a container named "agr.local.intermine_builder" already exists
if [ $(docker ps -aq -f name=^/agr.local.intermine_builder$) ]; then
    # Stop the container if it is running
    docker stop agr.local.intermine_builder
    # Remove the container after stopping
    docker rm agr.local.intermine_builder
    echo "Removed existing container named 'agr.local.intermine_builder'"
fi

docker run \
  --name "agr.local.intermine_builder" \
  --net intermine \
  --rm \
  -v "/data:/root/data" \
  "100225593120.dkr.ecr.us-east-1.amazonaws.com/agr_intermine_builder_env:stage" \
  ./local_dump_db_to_S3_only postgres postgres
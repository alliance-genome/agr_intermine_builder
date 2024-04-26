#!/bin/bash

# Check if a container named "agr.local.intermine_builder" already exists
if [ $(docker ps -aq -f name=^/agr.local.intermine_builder$) ]; then
    # Stop the container if it is running
    docker stop agr.local.intermine_builder
    # Remove the container after stopping
    docker rm agr.local.intermine_builder
    echo "Removed existing container named 'agr.local.intermine_builder'"
fi

# Run the Docker container with the volume mounted for persistence and drop into a bash shell
docker run \
  -it \
  --name "agr.local.intermine_builder" \
  --net local \
  --rm \
  -v "/data:/root/data" \
  "100225593120.dkr.ecr.us-east-1.amazonaws.com/agr_intermine_builder_env:stage" \
  bash

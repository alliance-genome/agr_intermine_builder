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

# Pull secrets file from AWS
echo "Pulling secrets file from AWS."
aws secretsmanager get-secret-value --region=us-east-1 --secret-id IntermineLocalPropertiesFile --query SecretString --output text > ./alliancemine.properties

# Run the Docker container with the volume mounted for persistence and drop into a bash shell
docker run \
  -it \
  --name "agr.local.intermine_builder" \
  --net intermine \
  --rm \
  -v "/data:/root/data" \
  -v "$(pwd)/alliancemine.properties:/root/alliancemine/alliancemine.properties" \
  "100225593120.dkr.ecr.us-east-1.amazonaws.com/agr_intermine_builder_env:stage" \
  bash

# Optionally remove the secrets file if you want to ensure it's not left on the host
rm -f ./alliancemine.properties

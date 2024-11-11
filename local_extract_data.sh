#!/bin/bash

# Execute docker authentication
if ! ./docker_auth; then
    echo "Docker authentication failed"
    exit 1
fi

# Variables
ALLIANCE_VERSION="7.4.0"
MEMORY="31g"

# Create the network if it doesn't exist
docker network ls | grep -w intermine || docker network create intermine

# Check if /data directory exists
if [ ! -d "/data" ]; then
    echo "Error: /data directory not found"
    exit 1
fi

docker run \
  --name "agr.local.data_extractor" \
  --net intermine \
  --memory="${MEMORY}" \
  --memory-swap="${MEMORY}" \
  -v "/data:/data" \
  -e ALLIANCE_RELEASE="${ALLIANCE_VERSION}" \
  -e EXTRACTOR_OUTPUTDIR="/data" \
  -e NEO4J_HOST="stage-neo4j.alliancegenome.org" \
  --log-driver=gelf --log-opt gelf-address=udp://logs.alliancegenome.org:12201 \
  --rm \
  "100225593120.dkr.ecr.us-east-1.amazonaws.com/agr_java_software:stage" \
  java -Xms"${MEMORY}" -Xmx"${MEMORY}" -DDEFAULT_LOG_LEVEL=DEBUG \
  -jar agr_intermine_data_extractor/target/agr_intermine_data_extractor-jar-with-dependencies.jar

#!/bin/bash

# Use a directory in the user's home folder
DATA_DIR="$HOME/docker_data"

# Ensure the data directory exists
mkdir -p "$DATA_DIR"

# Create the network if it doesn't exist
docker network ls | grep -w intermine || docker network create intermine

# Authenticate with ECR (do this immediately before docker run)
aws ecr get-login-password --region us-east-1 | docker login --username AWS --password-stdin 100225593120.dkr.ecr.us-east-1.amazonaws.com

# Run the container
docker run \
  --name "agr.local.data_extractor" \
  --net intermine \
  --platform linux/amd64 \
  -v "$DATA_DIR:/data" \
  -e ALLIANCE_RELEASE="7.2.0" \
  -e EXTRACTOR_OUTPUTDIR="/data" \
  -e NEO4J_HOST="stage-neo4j.alliancegenome.org" \
  --log-driver=gelf --log-opt gelf-address=udp://logs.alliancegenome.org:12201 \
  --rm \
  100225593120.dkr.ecr.us-east-1.amazonaws.com/agr_java_software:stage \
  java -Xms"8g" -Xmx"8g" -DDEFAULT_LOG_LEVEL=DEBUG -jar agr_intermine_data_extractor/target/agr_intermine_data_extractor-jar-with-dependencies.jar

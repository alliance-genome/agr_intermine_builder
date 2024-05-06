#!/bin/bash
./docker_auth

# Create the network if it doesn't exist
docker network ls | grep -w intermine || docker network create intermine

docker run \
  --name "agr.local.data_extractor" \
  --net intermine \
  -v "/data:/data" \
  -e ALLIANCE_RELEASE="7.2.0" \
  -e EXTRACTOR_OUTPUTDIR="/data" \
  -e NEO4J_HOST="stage-neo4j.alliancegenome.org" \
  --log-driver=gelf --log-opt gelf-address=udp://logs.alliancegenome.org:12201 \
  --rm \
  "100225593120.dkr.ecr.us-east-1.amazonaws.com/agr_java_software:stage" \
  java -Xms"31g" -Xmx"31g" -DDEFAULT_LOG_LEVEL=DEBUG -jar agr_intermine_data_extractor/target/agr_intermine_data_extractor-jar-with-dependencies.jar

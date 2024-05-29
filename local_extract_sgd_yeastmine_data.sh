#!/bin/bash
./docker_auth

# Create the network if it doesn't exist
docker network ls | grep -w intermine || docker network create intermine

aws s3 cp s3://agr-db-backups/alliancemine/intermine/ /data/intermine --recursive

